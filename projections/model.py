"""Per-player stat distributions from nflverse weekly box scores.

The core idea (Learn-mode style):
  A player's "true" level for a stat isn't just their season average.
  Recent games matter more than old ones (form changes, injuries, new
  coordinators), so we take a RECENCY-WEIGHTED mean and std:
    weight(game) = 0.5 ** (weeks_ago / half_life)
  With half_life = 8 weeks, a game 8 weeks ago counts half as much as
  last week's game. Then we shrink small samples toward the position
  average so a 2-game hot streak doesn't fool the model.

Injury adjustment (locked decision — accuracy is the product):
  Out        -> no projection at all (flag: DO_NOT_BET)
  Doubtful   -> mean * 0.55, std * 1.30, flag
  Questionable -> mean * 0.85, std * 1.15, flag
"""
from __future__ import annotations

import math

# Book market key -> (nflverse column, positions that qualify)
STAT_MAP = {
    "player_pass_yds": ("passing_yards", {"QB"}),
    "player_pass_tds": ("passing_tds", {"QB"}),
    "player_rush_yds": ("rushing_yards", {"QB", "RB", "WR", "TE"}),
    "player_receptions": ("receptions", {"WR", "TE", "RB"}),
    "player_rec_yds": ("receiving_yards", {"WR", "TE", "RB"}),
    "player_rush_tds": ("rushing_tds", {"QB", "RB", "WR", "TE"}),
    "player_rec_tds": ("receiving_tds", {"WR", "TE", "RB"}),
}

MIN_GAMES = 4  # below this, shrink hard toward the position baseline
HALF_LIFE_WEEKS = 8.0


def _weeks_ago(season: int, week: int, cur_season: int, cur_week: int) -> float:
    # Rough: 18 weeks per season (17 games + bye). Good enough for weighting.
    return (cur_season - season) * 18.0 + (cur_week - week)


def player_distribution(player_stats_df, player_name: str, stat_col: str,
                        cur_season: int, cur_week: int,
                        half_life: float = HALF_LIFE_WEEKS) -> dict | None:
    """Recency-weighted (mean, std, n) for one player's stat. None if no data."""
    import polars as pl

    games = (
        player_stats_df.filter(
            (pl.col("player_display_name") == player_name)
            & (pl.col("season_type") == "REG")
            & (pl.col(stat_col).is_not_null())
        )
        .select(["season", "week", stat_col])
        .sort(["season", "week"])
    )
    if games.height == 0:
        return None

    rows = games.to_dicts()
    weights, values = [], []
    for r in rows:
        ago = _weeks_ago(r["season"], r["week"], cur_season, cur_week)
        if ago < 0:  # future game — skip (shouldn't happen)
            continue
        w = 0.5 ** (ago / half_life)
        weights.append(w)
        values.append(float(r[stat_col]))

    n = len(values)
    if n == 0:
        return None
    wsum = sum(weights)
    mean = sum(v * w for v, w in zip(values, weights)) / wsum
    var = sum(w * (v - mean) ** 2 for v, w in zip(values, weights)) / wsum
    std = math.sqrt(max(var, 1e-9))

    # Shrinkage: few games -> pull toward a conservative baseline so the
    # model doesn't overreact to a tiny sample. (Baseline = weighted mean
    # itself here; with more data we'd use the position average.)
    if n < MIN_GAMES:
        shrink = n / MIN_GAMES  # 0..1
        std = std / max(shrink, 0.25)  # widen = less confident

    return {"mean": mean, "std": std, "n": n}


def injury_status(injuries_df, player_name: str, team: str,
                  season: int, week: int) -> str | None:
    """Latest injury report status for a player ('Out', 'Doubtful',
    'Questionable', ...), or None if not on the report ( = healthy)."""
    import polars as pl

    rep = injuries_df.filter(
        (pl.col("full_name") == player_name)
        & (pl.col("season") == season)
        & (pl.col("week") <= week)
    ).sort("week")
    if rep.height == 0:
        # Try last-name match — books and nflverse don't always agree on
        # "Josh Allen" vs "Allen, Josh".
        last = player_name.split()[-1]
        rep = injuries_df.filter(
            (pl.col("last_name") == last)
            & (pl.col("team") == team)
            & (pl.col("season") == season)
            & (pl.col("week") <= week)
        ).sort("week")
    if rep.height == 0:
        return None
    return rep.to_dicts()[-1].get("report_status")


def apply_injury_adjustment(dist: dict, status: str | None) -> dict:
    """Downgrade the projection for injury risk. Returns dist + flags."""
    out = dict(dist)
    out["injury_status"] = status
    out["injury_flag"] = None
    if not status:
        return out
    s = status.lower()
    if "out" in s:
        out["do_not_bet"] = True
        out["injury_flag"] = "OUT — no bet"
    elif "doubtful" in s:
        out["mean"] = dist["mean"] * 0.55
        out["std"] = dist["std"] * 1.30
        out["injury_flag"] = "Doubtful — projection cut 45%, std widened"
    elif "questionable" in s:
        out["mean"] = dist["mean"] * 0.85
        out["std"] = dist["std"] * 1.15
        out["injury_flag"] = "Questionable — projection cut 15%, std widened"
    return out
