"""Player profiles — the "baseball card" for every rostered NFL player.

Learn-mode tour:
  - get_teams()       -> the 32 current teams (nflverse lists a few
                         historical ones too, so we filter by "has a
                         current roster").
  - get_roster()      -> every rostered player: name, position, team,
                         jersey, status.
  - find_player()     -> bio lookup by name (fuzzy on last name).
  - game_log()        -> weekly stat lines, most recent first, with a
                         last 5 / 10 / 15 toggle.
  - season_averages() -> per-game averages for one season.
  - upcoming_matchup()-> next scheduled game for a team.

All functions take DataFrames and return plain Python — that keeps them
unit-testable with synthetic data (see tests/test_v2.py).
"""
from __future__ import annotations

# Stat columns shown in game logs, in display order. Intersected with
# whatever the nflverse table actually has (columns shift over years).
GAMELOG_COLS = [
    "passing_yards", "passing_tds", "passing_interceptions",
    "rushing_yards", "rushing_tds", "carries",
    "receptions", "targets", "receiving_yards", "receiving_tds",
    "receiving_air_yards", "receiving_yards_after_catch",
]

VALID_WINDOWS = (5, 10, 15)


def _cols(df, want: list[str]) -> list[str]:
    have = set(df.columns)
    return [c for c in want if c in have]


def get_teams(teams_df, rosters_df) -> list[dict]:
    """The 32 current teams. nflverse's team table keeps historical rows
    (OAK, STL, SD...), so a team counts as current only if it has players
    on the latest roster."""
    import polars as pl

    current_abbrs = set(rosters_df["team"].unique().to_list())
    rows = []
    for r in teams_df.to_dicts():
        abbr = r.get("team_abbr")
        if abbr in current_abbrs:
            rows.append(
                {
                    "abbr": abbr,
                    "name": r.get("team_name"),
                    "nick": r.get("team_nick"),
                    "conf": r.get("team_conf"),
                    "division": r.get("team_division"),
                }
            )
    rows.sort(key=lambda r: r["abbr"])
    return rows


def get_roster(rosters_df, team_abbr: str | None = None) -> list[dict]:
    """Every rostered player (optionally one team)."""
    import polars as pl

    df = rosters_df
    if team_abbr:
        df = df.filter(pl.col("team") == team_abbr)
    out = []
    for r in df.to_dicts():
        out.append(
            {
                "name": r.get("full_name"),
                "first": r.get("first_name"),
                "last": r.get("last_name"),
                "team": r.get("team"),
                "position": r.get("position"),
                "depth_position": r.get("depth_chart_position"),
                "jersey": r.get("jersey_number"),
                "status": r.get("status"),
            }
        )
    out.sort(key=lambda p: (p["team"] or "", p["position"] or "", p["name"] or ""))
    return out


def find_player(rosters_df, name: str) -> dict | None:
    """Bio lookup. Exact full-name match first, then last-name fallback
    (books write 'Josh Allen', nflverse sometimes 'Allen, Josh')."""
    import polars as pl

    hit = rosters_df.filter(pl.col("full_name") == name)
    if hit.height == 0:
        last = name.split()[-1]
        hit = rosters_df.filter(pl.col("last_name") == last)
    if hit.height == 0:
        return None
    r = hit.to_dicts()[0]
    return {
        "name": r.get("full_name"),
        "team": r.get("team"),
        "position": r.get("position"),
        "depth_position": r.get("depth_chart_position"),
        "jersey": r.get("jersey_number"),
        "status": r.get("status"),
        "status_detail": r.get("status_description_abbr"),
    }


def game_log(player_stats_df, player_name: str, last_n: int = 10) -> list[dict]:
    """Weekly stat lines, most recent first. last_n in {5, 10, 15}.

    Each row: season, week, team, opponent + the stat columns.
    Bye weeks simply don't appear (no row = didn't play).
    """
    import polars as pl

    if last_n not in VALID_WINDOWS:
        raise ValueError(f"last_n must be one of {VALID_WINDOWS}")
    cols = ["season", "week", "team", "opponent_team"] + _cols(player_stats_df, GAMELOG_COLS)
    games = (
        player_stats_df.filter(
            (pl.col("player_display_name") == player_name)
            & (pl.col("season_type") == "REG")
        )
        .select(cols)
        .sort(["season", "week"], descending=True)
        .head(last_n)
    )
    return games.to_dicts()


def season_averages(player_stats_df, player_name: str, season: int) -> dict:
    """Per-game averages for one season (REG only)."""
    import polars as pl

    cols = _cols(player_stats_df, GAMELOG_COLS)
    games = player_stats_df.filter(
        (pl.col("player_display_name") == player_name)
        & (pl.col("season") == season)
        & (pl.col("season_type") == "REG")
    )
    n = games.height
    if n == 0:
        return {"games": 0}
    avgs = {"games": n}
    for c in cols:
        vals = [v for v in games[c].to_list() if v is not None]
        avgs[c] = round(sum(vals) / n, 1) if vals else 0.0
    # Derived per-game rates people actually ask about.
    avgs["yards_per_carry"] = _safe_div(avgs.get("rushing_yards", 0), avgs.get("carries", 0))
    avgs["yards_per_reception"] = _safe_div(avgs.get("receiving_yards", 0), avgs.get("receptions", 0))
    avgs["catch_rate"] = _safe_div(avgs.get("receptions", 0), avgs.get("targets", 0))
    return avgs


def _safe_div(a: float, b: float) -> float | None:
    return round(a / b, 2) if b else None


def upcoming_matchup(schedules_df, team_abbr: str, season: int, week: int) -> dict | None:
    """Next scheduled game for a team at/after (season, week).

    Returns {opponent, home_away, date, week} or None if the season's over.
    """
    import polars as pl

    sched = schedules_df.filter(
        ((pl.col("home_team") == team_abbr) | (pl.col("away_team") == team_abbr))
        & (
            (pl.col("season") > season)
            | ((pl.col("season") == season) & (pl.col("week") >= week))
        )
    ).sort(["season", "week"])
    if sched.height == 0:
        return None
    g = sched.to_dicts()[0]
    home = g["home_team"] == team_abbr
    return {
        "opponent": g["away_team"] if home else g["home_team"],
        "home_away": "vs" if home else "@",
        "date": str(g.get("gameday")),
        "week": g["week"],
        "season": g["season"],
    }


def latest_injury_status(injuries_df, player_name: str, team: str,
                         season: int, week: int) -> dict | None:
    """Latest injury report row for a player (shared with the news tab)."""
    import polars as pl

    rep = injuries_df.filter(
        (pl.col("full_name") == player_name)
        & (pl.col("season") == season)
        & (pl.col("week") <= week)
    ).sort("week")
    if rep.height == 0:
        last = player_name.split()[-1]
        rep = injuries_df.filter(
            (pl.col("last_name") == last)
            & (pl.col("team") == team)
            & (pl.col("season") == season)
            & (pl.col("week") <= week)
        ).sort("week")
    if rep.height == 0:
        return None
    r = rep.to_dicts()[-1]
    return {
        "status": r.get("report_status"),
        "details": r.get("report_details") or r.get("injury"),
        "week": r.get("week"),
    }
