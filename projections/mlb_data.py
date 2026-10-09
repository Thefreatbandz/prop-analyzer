"""MLB data layer — free MLB stats via pybaseball statcast, cached as parquet.

Mirrors projections/nflverse.py exactly: parquet cache first, download on
miss/stale (24h TTL), and a failed download NEVER takes the app down — a
cached copy is served (even stale) with a warning; the exception only
propagates when there is nothing on disk to serve.

Statcast is pitch-level, so we aggregate to per-game rows here:
  batter : H, HR, TB (total bases), SO, BB, SB, RBI
  pitcher: SO, outs recorded, H allowed, BB allowed

Honest gaps (v1): runs scored (batter) and earned runs (pitcher) are NOT
derivable from pitch-level events without full game state — those markets
get no distribution and the engine skips them, never fakes them.
FanGraphs endpoints are blocked from some networks; statcast is the
$0 backbone that works everywhere.
"""
from __future__ import annotations

import os
import re
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "mlb")
MAX_AGE_SECONDS = 24 * 60 * 60

# Pull window: current + prior season in one statcast call per player.
# (Statcast pitch data starts 2015; one call per player keeps it fast.)
SEASON_START = "2025-03-01"

BATTER_COLS = ["game_date", "G", "H", "HR", "TB", "SO", "BB", "SB", "RBI"]
PITCHER_COLS = ["game_date", "G", "SO", "outs", "H_allowed", "BB"]

_HIT_EVENTS = {"single", "double", "triple", "home_run"}
_SO_EVENTS = {"strikeout", "strikeout_double_play"}
_OUT_EVENTS = {
    "strikeout", "strikeout_double_play", "field_out", "force_out",
    "groundout", "flyout", "lineout", "pop_out", "double_play",
    "grounded_into_double_play", "triple_play", "sac_fly", "sac_bunt",
    "fielders_choice_out", "caught_stealing_2b", "caught_stealing_3b",
    "caught_stealing_home", "pickoff_1b", "pickoff_2b", "pickoff_3b",
}
_TB_MAP = {"single": 1, "double": 2, "triple": 3, "home_run": 4}


def _path(name: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, f"{name}.parquet")


def _fresh(path: str) -> bool:
    return os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE_SECONDS


def _warn(msg: str, *args):
    import logging
    logging.warning(msg, *args)


def _mlbam_via_stats_api(first: str, last: str) -> int | None:
    """Fallback ID resolution via the free MLB Stats API.

    pybaseball's Chadwick register occasionally misses active players
    (e.g. Jose Ramirez in the 2026 register). The MLB API is authoritative
    for current IDs.
    """
    try:
        import requests
        r = requests.get(
            "https://statsapi.mlb.com/api/v1/people/search",
            params={"names": f"{first} {last}"},
            timeout=15,
        )
        r.raise_for_status()
        people = r.json().get("people", [])
        if people:
            return int(people[0]["id"])
    except Exception as e:
        _warn("MLB Stats API lookup failed for %s %s (%s)", first, last, e)
    return None


def _lookup_cache_path() -> str:
    return _path("playerid_lookup")


def resolve_mlbam_id(first: str, last: str) -> int | None:
    """MLBAM id for a player name, cached in parquet.

    pybaseball's playerid_lookup re-downloads its table every call (~30s),
    so we cache per-name hits forever (IDs don't change).
    """
    import polars as pl

    key = f"{first.strip().lower()}|{last.strip().lower()}"
    path = _lookup_cache_path()
    try:
        cache = (pl.read_parquet(path) if os.path.exists(path)
                 else pl.DataFrame({"key": [], "mlbam_id": []},
                                   schema={"key": pl.Utf8, "mlbam_id": pl.Int64}))
        hit = cache.filter(pl.col("key") == key)
    except Exception:
        # Corrupt or schema-drifted cache (e.g. an Object-dtype key from
        # an older build) must never crash resolution — fall through and
        # re-resolve, then rewrite the cache cleanly.
        hit = pl.DataFrame({"key": [], "mlbam_id": []},
                           schema={"key": pl.Utf8, "mlbam_id": pl.Int64})
    if hit.height:
        return int(hit["mlbam_id"][0])

    try:
        from pybaseball import playerid_lookup
        lk = playerid_lookup(last, first)
        if lk is not None and len(lk) > 0:
            # Most recent stint first — take the first row's MLBAM id.
            mlbam = int(lk.iloc[0]["key_mlbam"])
        else:
            mlbam = _mlbam_via_stats_api(first, last)
    except Exception as e:
        _warn("mlbam lookup failed for %s %s (%s)", first, last, e)
        return None
    if mlbam is None:
        return None
    try:
        cache = pl.concat([cache, pl.DataFrame(
            {"key": [key], "mlbam_id": [mlbam]})])
        cache.write_parquet(path)
    except Exception as e:
        _warn("could not write mlbam lookup cache (%s)", e)
    return mlbam


def resolve_player(name: str) -> int | None:
    """MLBAM id from a display name ("Aaron Judge"). None when unknown."""
    parts = (name or "").strip().split()
    if len(parts) < 2:
        return None
    return resolve_mlbam_id(parts[0], parts[-1])


def _rbi_from_des(des: str | None, event: str | None) -> int:
    """RBI for one plate appearance from its statcast description.

    Format: "Aaron Judge homers (18) on a fly ball to left field. Ben Rice
    scores. Cody Bellinger scores." — each "<Name> scores" is one RBI, and
    the batter always drives himself in on a home run.
    """
    if not des or (isinstance(des, float) and des != des):
        # NaN is truthy, so `not des` alone is NOT enough — statcast uses
        # NaN for empty text fields and it would reach re.findall below.
        return 1 if event == "home_run" else 0
    n = len(re.findall(r"\bscores\b", str(des)))
    if event == "home_run":
        n += 1  # the batter scores himself; des only lists other runners
    return n


def _empty_batter():
    import polars as pl
    return pl.DataFrame(schema={c: pl.Int64 for c in BATTER_COLS}
                        | {"game_date": pl.Utf8})


def _empty_pitcher():
    import polars as pl
    return pl.DataFrame(schema={c: pl.Int64 for c in PITCHER_COLS}
                        | {"game_date": pl.Utf8})


def batter_game_log(name: str, force: bool = False):
    """Per-game batting log, newest first. Empty (not a crash) when the
    player is unknown or statcast has no rows (offseason)."""
    import polars as pl

    pid = resolve_player(name)
    if pid is None:
        return _empty_batter()
    safe = "".join(c if c.isalnum() else "_" for c in name)[:48]
    path = _path(f"bat_{safe}_{pid}")
    if not force and _fresh(path):
        return pl.read_parquet(path)

    try:
        from pybaseball import statcast_batter
        import datetime as _dt
        end = _dt.date.today().isoformat()
        df = statcast_batter(SEASON_START, end, pid)
    except Exception as e:
        if os.path.exists(path):
            _warn("statcast batter pull failed for %s (%s); serving cache", name, e)
            return pl.read_parquet(path)
        return _empty_batter()
    if df is None or df.empty:
        return _empty_batter() if not os.path.exists(path) else pl.read_parquet(path)

    rows = []
    for game_date, g in df.groupby("game_date"):
        pa = g[g["events"].notna()]  # one terminal event per plate appearance
        rbi = sum(_rbi_from_des(d, ev) for d, ev in
                  zip(pa["des"], pa["events"]))
        sb = int(g["events"].str.contains("stolen_base", na=False).sum())
        rows.append({
            "game_date": str(game_date),
            "G": 1,
            "H": int(pa["events"].isin(_HIT_EVENTS).sum()),
            "HR": int((pa["events"] == "home_run").sum()),
            "TB": int(sum(_TB_MAP.get(ev, 0) for ev in pa["events"])),
            "SO": int(pa["events"].isin(_SO_EVENTS).sum()),
            "BB": int((pa["events"] == "walk").sum()),
            "SB": sb,
            "RBI": rbi,
        })
    out = pl.DataFrame(rows).sort("game_date", descending=True)
    try:
        out.write_parquet(path)
    except Exception as e:
        _warn("could not write mlb batter cache for %s (%s)", name, e)
    return out


def pitcher_game_log(name: str, force: bool = False):
    """Per-game pitching log, newest first. Empty (not a crash) when the
    player is unknown or statcast has no rows."""
    import polars as pl

    pid = resolve_player(name)
    if pid is None:
        return _empty_pitcher()
    safe = "".join(c if c.isalnum() else "_" for c in name)[:48]
    path = _path(f"pit_{safe}_{pid}")
    if not force and _fresh(path):
        return pl.read_parquet(path)

    try:
        from pybaseball import statcast_pitcher
        import datetime as _dt
        end = _dt.date.today().isoformat()
        df = statcast_pitcher(SEASON_START, end, pid)
    except Exception as e:
        if os.path.exists(path):
            _warn("statcast pitcher pull failed for %s (%s); serving cache", name, e)
            return pl.read_parquet(path)
        return _empty_pitcher()
    if df is None or df.empty:
        return _empty_pitcher() if not os.path.exists(path) else pl.read_parquet(path)

    rows = []
    for game_date, g in df.groupby("game_date"):
        pa = g[g["events"].notna()]
        rows.append({
            "game_date": str(game_date),
            "G": 1,
            "SO": int(pa["events"].isin(_SO_EVENTS).sum()),
            "outs": int(pa["events"].isin(_OUT_EVENTS).sum()),
            "H_allowed": int(pa["events"].isin(_HIT_EVENTS).sum()),
            "BB": int((pa["events"] == "walk").sum()),
        })
    out = pl.DataFrame(rows).sort("game_date", descending=True)
    try:
        out.write_parquet(path)
    except Exception as e:
        _warn("could not write mlb pitcher cache for %s (%s)", name, e)
    return out
