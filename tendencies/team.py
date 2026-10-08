"""Team tendencies from nflverse charted play-by-play.

Learn-mode tour:
  - We only count real offensive snaps: play_type in {run, pass},
    which throws out kneels, spikes, punts and field goals.
  - Splits are plain shares: e.g. "on 3rd down, this team passes 68%".
  - Formation proxies: shotgun / no-huddle rates come straight from
    the PBP flags; motion rate needs the FTN charting table (optional —
    the function degrades gracefully without it).
  - Personnel groupings (11/12/21 personnel...) are NOT in the free
    PBP columns — we say so instead of faking it.
"""
from __future__ import annotations

SNAP_TYPES = ("run", "pass")


def _snaps(pbp_df, team: str, seasons: list[int] | None = None):
    import polars as pl

    df = pbp_df.filter(
        (pl.col("posteam") == team) & (pl.col("play_type").is_in(SNAP_TYPES))
    )
    if seasons:
        df = df.filter(pl.col("season").is_in(seasons))
    return df


def _share(df, cond) -> float | None:
    import polars as pl

    n = df.height
    if n == 0:
        return None
    return round(df.filter(cond).height / n, 3)


def run_pass_splits(pbp_df, team: str, seasons: list[int] | None = None) -> dict:
    """Run/pass shares: overall, by down, by distance bucket, red zone."""
    import polars as pl

    df = _snaps(pbp_df, team, seasons)
    if df.height == 0:
        return {"team": team, "snaps": 0}

    def bucket(ydstogo: float) -> str:
        if ydstogo <= 3:
            return "short (1-3)"
        if ydstogo <= 7:
            return "medium (4-7)"
        return "long (8+)"

    out: dict = {"team": team, "snaps": df.height}
    out["run_rate"] = _share(df, pl.col("play_type") == "run")
    out["pass_rate"] = _share(df, pl.col("play_type") == "pass")

    out["by_down"] = {}
    for d in (1, 2, 3, 4):
        sub = df.filter(pl.col("down") == d)
        out["by_down"][f"{d}st" if d == 1 else f"{d}nd" if d == 2 else f"{d}rd" if d == 3 else "4th"] = {
            "snaps": sub.height,
            "run_rate": _share(sub, pl.col("play_type") == "run"),
            "pass_rate": _share(sub, pl.col("play_type") == "pass"),
        }

    out["by_distance"] = {}
    for label in ("short (1-3)", "medium (4-7)", "long (8+)"):
        lo, hi = {"short (1-3)": (1, 3), "medium (4-7)": (4, 7), "long (8+)": (8, 99)}[label]
        sub = df.filter((pl.col("ydstogo") >= lo) & (pl.col("ydstogo") <= hi))
        out["by_distance"][label] = {
            "snaps": sub.height,
            "run_rate": _share(sub, pl.col("play_type") == "run"),
            "pass_rate": _share(sub, pl.col("play_type") == "pass"),
        }

    rz = df.filter(pl.col("yardline_100") <= 20)
    out["red_zone"] = {
        "snaps": rz.height,
        "run_rate": _share(rz, pl.col("play_type") == "run"),
        "pass_rate": _share(rz, pl.col("play_type") == "pass"),
    }
    return out


def formation_proxies(pbp_df, team: str, seasons: list[int] | None = None,
                      ftn_df=None) -> dict:
    """Formation tendencies, honestly labeled.

    Free data HAS: shotgun rate, no-huddle rate (PBP flags), motion rate
    (FTN charting, if you pass ftn_df).
    Free data does NOT have: personnel groupings (11/12/21...) or
    formation names — those columns aren't in the public tables.
    """
    import polars as pl

    df = _snaps(pbp_df, team, seasons)
    out: dict = {"team": team, "snaps": df.height}
    if df.height == 0:
        return out
    if "shotgun" in df.columns:
        out["shotgun_rate"] = _share(df, pl.col("shotgun") == 1)
    if "no_huddle" in df.columns:
        out["no_huddle_rate"] = _share(df, pl.col("no_huddle") == 1)
    if ftn_df is not None and "is_motion" in ftn_df.columns:
        m = ftn_df.filter(pl.col("posteam") == team)
        if seasons:
            m = m.filter(pl.col("season").is_in(seasons))
        out["motion_rate"] = _share(m, pl.col("is_motion") == 1) if m.height else None
    else:
        out["motion_rate"] = None
    out["personnel_groupings"] = None  # not in free data — see docstring
    out["personnel_note"] = (
        "Personnel groupings (11/12/21 personnel) aren't published in the "
        "free nflverse tables, so we don't guess. Shotgun / no-huddle / "
        "motion rates above are the honest proxies."
    )
    return out


def pace(pbp_df, team: str, seasons: list[int] | None = None) -> dict:
    """Tempo: offensive snaps per game, and median seconds between snaps.

    Seconds-between-snaps comes from game_seconds_remaining diffs within
    each game — a solid proxy for hurry-up vs huddle-up pace.
    """
    import polars as pl

    df = _snaps(pbp_df, team, seasons).sort(["game_id", "game_seconds_remaining"],
                                            descending=[False, True])
    if df.height == 0:
        return {"team": team, "snaps": 0}
    games = df["game_id"].n_unique()
    gaps = []
    prev_game, prev_t = None, None
    for gid, t in zip(df["game_id"].to_list(), df["game_seconds_remaining"].to_list()):
        if gid == prev_game and t is not None and prev_t is not None:
            gap = prev_t - t
            if 0 < gap < 120:  # filter clock weirdness (timeouts, quarter breaks)
                gaps.append(gap)
        prev_game, prev_t = gid, t
    gaps.sort()
    med = gaps[len(gaps) // 2] if gaps else None
    return {
        "team": team,
        "snaps": df.height,
        "games": games,
        "snaps_per_game": round(df.height / games, 1) if games else None,
        "median_seconds_per_snap": round(med, 1) if med else None,
    }
