"""Formation detail from charted play-by-play — honestly labeled.

What the free nflverse tables actually carry:
  - shotgun / no_huddle flags (every play)
  - run_location (LEFT / MIDDLE / RIGHT), run_gap (GUARD / TACKLE / END)
  - pass_location (short/deep + left/middle/right codes)

What they do NOT carry: personnel groupings (11/12/21 personnel) or
formation names. We compute run/pass splits *by* shotgun and directional
tendencies instead of faking personnel — and we say so in HONEST_LABEL.
"""
from __future__ import annotations

HONEST_LABEL = (
    "Formation proxies, not charted personnel: true personnel groupings "
    "(11/12/21 personnel) aren't published in the free nflverse tables, so "
    "we don't guess. Below: how often they line up in shotgun / no-huddle, "
    "run-vs-pass out of each look, and where runs and passes go."
)

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
    n = df.height
    if n == 0:
        return None
    return round(df.filter(cond).height / n, 3)


def formation_detail(pbp_df, team: str, seasons: list[int] | None = None) -> dict:
    """Shotgun/no-huddle usage, run/pass by look, run direction, pass depth.

    Returns a dict with rates (0-1) and share tables. Empty dict values
    (None) when the columns or snaps are missing — never raises, so the
    UI degrades to \"not available\" instead of crashing.
    """
    import polars as pl

    df = _snaps(pbp_df, team, seasons)
    out: dict = {"team": team, "snaps": df.height, "honest_label": HONEST_LABEL,
                 "shotgun_rate": None, "no_huddle_rate": None,
                 "run_direction": [], "run_gap": [], "pass_location": [],
                 "red_zone_run_rate": None}
    if df.height == 0:
        return out

    cols = df.columns
    # --- Shotgun: usage + run/pass split by look ---
    if "shotgun" in cols:
        sg = df.filter(pl.col("shotgun") == 1)
        uc = df.filter(pl.col("shotgun") == 0)
        out["shotgun_rate"] = _share(df, pl.col("shotgun") == 1)
        out["shotgun_snaps"] = sg.height
        out["under_center_snaps"] = uc.height
        out["run_rate_shotgun"] = _share(sg, pl.col("play_type") == "run")
        out["run_rate_under_center"] = _share(uc, pl.col("play_type") == "run")
    else:
        out["shotgun_rate"] = None

    # --- No-huddle ---
    if "no_huddle" in cols:
        out["no_huddle_rate"] = _share(df, pl.col("no_huddle") == 1)
    else:
        out["no_huddle_rate"] = None

    # --- Run direction ---
    if "run_location" in cols:
        runs = df.filter(pl.col("play_type") == "run")
        locs = (
            runs.filter(pl.col("run_location").is_not_null())
            .group_by("run_location")
            .agg(pl.len().alias("n"))
            .sort("n", descending=True)
        )
        total = locs["n"].sum()
        out["run_direction"] = [
            {"direction": r["run_location"], "share": round(r["n"] / total, 3),
             "n": r["n"]}
            for r in locs.to_dicts()
        ] if total else []
    else:
        out["run_direction"] = []

    # --- Run gap ---
    if "run_gap" in cols:
        runs = df.filter(pl.col("play_type") == "run")
        gaps = (
            runs.filter(pl.col("run_gap").is_not_null())
            .group_by("run_gap")
            .agg(pl.len().alias("n"))
            .sort("n", descending=True)
        )
        total = gaps["n"].sum()
        out["run_gap"] = [
            {"gap": r["run_gap"], "share": round(r["n"] / total, 3), "n": r["n"]}
            for r in gaps.to_dicts()
        ] if total else []
    else:
        out["run_gap"] = []

    # --- Pass location / depth ---
    if "pass_location" in cols:
        passes = df.filter(pl.col("play_type") == "pass")
        locs = (
            passes.filter(pl.col("pass_location").is_not_null())
            .group_by("pass_location")
            .agg(pl.len().alias("n"))
            .sort("n", descending=True)
        )
        total = locs["n"].sum()
        out["pass_location"] = [
            {"location": r["pass_location"], "share": round(r["n"] / total, 3),
             "n": r["n"]}
            for r in locs.to_dicts()
        ] if total else []
    else:
        out["pass_location"] = []

    # --- Red-zone run/pass ---
    if "yardline_100" in cols:
        rz = df.filter(pl.col("yardline_100") <= 20)
        out["red_zone_snaps"] = rz.height
        out["red_zone_run_rate"] = _share(rz, pl.col("play_type") == "run")
    else:
        out["red_zone_run_rate"] = None

    return out
