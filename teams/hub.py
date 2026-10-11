"""Team hub data: record, schedule, leaders — from bundled nflverse tables.

All functions degrade to empty/None (never raise) when the tables are
missing, so the Teams page renders an honest \"not available\" state.
"""
from __future__ import annotations


def team_record(schedules_df, team_abbr: str, season: int) -> dict:
    """W/L/T from final scores. Unplayed games (null scores) don't count."""
    import polars as pl

    try:
        df = schedules_df.filter(pl.col("season") == season)
    except Exception:
        return {"team": team_abbr, "season": season, "wins": 0, "losses": 0,
                "ties": 0, "games": 0}
    played = df.filter(
        pl.col("home_score").is_not_null() & pl.col("away_score").is_not_null()
    )
    w = l = t = 0
    for r in played.to_dicts():
        home = r.get("home_team") == team_abbr
        away = r.get("away_team") == team_abbr
        if not (home or away):
            continue
        mine = r["home_score"] if home else r["away_score"]
        theirs = r["away_score"] if home else r["home_score"]
        if mine is None or theirs is None:
            continue
        if mine > theirs:
            w += 1
        elif mine < theirs:
            l += 1
        else:
            t += 1
    return {"team": team_abbr, "season": season, "wins": w, "losses": l,
            "ties": t, "games": w + l + t}


def team_schedule(schedules_df, team_abbr: str, season: int,
                  week: int) -> list[dict]:
    """Upcoming games (week >= current), soonest first."""
    import polars as pl

    try:
        df = schedules_df.filter(
            (pl.col("season") == season)
            & (pl.col("week") >= week)
            & ((pl.col("home_team") == team_abbr)
               | (pl.col("away_team") == team_abbr))
        ).sort(["week"])
    except Exception:
        return []
    out = []
    for r in df.to_dicts():
        home = r.get("home_team") == team_abbr
        out.append({
            "week": r.get("week"),
            "opponent": r.get("away_team") if home else r.get("home_team"),
            "home_away": "vs" if home else "@",
            "date": str(r.get("gameday") or r.get("start_time") or ""),
        })
    return out


def team_leaders(player_stats_df, team_abbr: str, season: int,
                 top_n: int = 3) -> dict:
    """Team leaders in pass/rush/receiving yards (regular season)."""
    import polars as pl

    out: dict = {"pass_yds": [], "rush_yds": [], "rec_yds": []}
    try:
        df = player_stats_df.filter(
            (pl.col("season") == season)
            & (pl.col("season_type") == "REG")
        )
    except Exception:
        return out
    # Team column name varies by table build; try the common ones.
    team_col = next((c for c in ("recent_team", "team", "posteam")
                     if c in df.columns), None)
    if team_col is None:
        return out
    df = df.filter(pl.col(team_col) == team_abbr)
    name_col = "player_display_name" if "player_display_name" in df.columns else None
    if name_col is None:
        return out

    def leaders(col: str) -> list[dict]:
        if col not in df.columns:
            return []
        agg = (
            df.group_by(name_col)
            .agg(pl.col(col).sum().alias("yds"))
            .filter(pl.col("yds") > 0)
            .sort("yds", descending=True)
            .head(top_n)
        )
        return [{"name": r[name_col], "yds": int(r["yds"])}
                for r in agg.to_dicts()]

    out["pass_yds"] = leaders("passing_yards")
    out["rush_yds"] = leaders("rushing_yards")
    out["rec_yds"] = leaders("receiving_yards")
    return out
