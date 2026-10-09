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

# NBA book market key -> nba_data game-log column. player_pra is a
# computed combo (PTS+REB+AST), handled specially by the builder.
NBA_STAT_MAP = {
    "player_points": "PTS",
    "player_rebounds": "REB",
    "player_assists": "AST",
    "player_threes": "FG3M",
    "player_steals": "STL",
    "player_blocks": "BLK",
    "player_pra": "PRA",  # computed
}

# MLB book market key -> mlb_data game-log column.
# Honest gaps (v1): runs (batter) and earned_runs (pitcher) are NOT
# derivable from pitch-level statcast without full game state — they are
# deliberately absent here, so the builder skips those markets instead
# of faking a distribution.
MLB_BATTER_STAT_MAP = {
    "player_hits": "H",
    "player_home_runs": "HR",
    "player_rbis": "RBI",
    "player_total_bases": "TB",
    "player_stolen_bases": "SB",
    "player_so_batter": "SO",
}
MLB_PITCHER_STAT_MAP = {
    "player_so_pitcher": "SO",
    "player_outs_recorded": "outs",
    "player_hits_allowed": "H_allowed",
}

# Below this many games, the distribution is flagged low-sample — the
# model will still rank it, but the UI says so out loud (same honesty
# bar as the NFL degenerate-sides note).
LOW_SAMPLE_GAMES = 8


def game_log_distribution(values: list[float],
                          half_life_games: float = 12.0) -> dict | None:
    """Recency-weighted (mean, std, n) from a chronological game log.

    values: oldest -> newest. weight(game) = 0.5 ** (games_ago / half_life).
    Same shrinkage philosophy as player_distribution: tiny samples get a
    widened std so the model doesn't overreact, plus an explicit
    low_sample flag when n < LOW_SAMPLE_GAMES.
    """
    vals = [float(v) for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return None
    weights = [0.5 ** ((n - 1 - i) / half_life_games) for i in range(n)]
    wsum = sum(weights)
    mean = sum(v * w for v, w in zip(vals, weights)) / wsum
    var = sum(w * (v - mean) ** 2 for v, w in zip(vals, weights)) / wsum
    std = math.sqrt(max(var, 1e-9))
    if n < MIN_GAMES:
        shrink = n / MIN_GAMES
        std = std / max(shrink, 0.25)
    out = {"mean": mean, "std": std, "n": n}
    if n < LOW_SAMPLE_GAMES:
        out["low_sample"] = True
        out["sample_flag"] = (f"Small sample ({n} games) — treat this "
                              f"projection with extra caution.")
    return out

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
