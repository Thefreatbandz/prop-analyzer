"""NBA data layer — free NBA stats via nba_api, cached locally as parquet.

Mirrors projections/nflverse.py exactly: parquet cache first, download on
miss/stale (24h TTL), and a failed download NEVER takes the app down — a
cached copy is served (even stale) with a warning; the exception only
propagates when there is nothing on disk to serve.

Covers the last 3 seasons (enough for recency-weighted form). Offseason
(no games yet for the current season) returns an empty frame, never a
crash — the engine skips players with no projection honestly.
"""
from __future__ import annotations

import os
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "nba")
# nba_api season strings, most recent first.
SEASONS = ["2025-26", "2024-25", "2023-24"]
# Current preseason (2026-27): games happening NOW, ahead of the Oct 20
# regular-season tip. Pulled separately and tagged is_preseason=1 so the
# distribution builder can weight/label it honestly — preseason minutes
# are limited and rotations experimental, so it's signal with an asterisk.
PRESEASON_SEASON = "2026-27"
PRESEASON_TTL = 6 * 60 * 60  # games nightly — refresh faster than regular data
MAX_AGE_SECONDS = 24 * 60 * 60

# Columns we keep from the game log, in a stable order.
GAME_COLS = ["game_date", "season", "matchup", "team_abbr",
             "MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "is_preseason"]

# nba_api's raw column names -> our GAME_COLS.
_RAW_COLS = {
    "GAME_DATE": "game_date",
    "MATCHUP": "matchup",
    "TEAM_ABBREVIATION": "team_abbr",
    "MIN": "MIN",
    "PTS": "PTS",
    "REB": "REB",
    "AST": "AST",
    "FG3M": "FG3M",
    "STL": "STL",
    "BLK": "BLK",
}


def _path(name: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, f"{name}.parquet")


def _fresh(path: str) -> bool:
    return os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE_SECONDS


def _warn(msg: str, *args):
    import logging
    logging.warning(msg, *args)


def _player_index(force: bool = False):
    """All NBA players (id + full name), cached as parquet.

    nba_api's static list is bundled with the package, but we cache it
    anyway so name resolution never depends on package internals.
    """
    import polars as pl

    path = _path("player_index")
    if not force and _fresh(path):
        return pl.read_parquet(path)
    try:
        from nba_api.stats.static import players as _sp
        rows = [{"player_id": p["id"], "full_name": p["full_name"]}
                for p in _sp.get_players()]
        df = pl.DataFrame(rows)
    except Exception as e:
        if os.path.exists(path):
            _warn("nba player index build failed (%s); serving cached copy", e)
            return pl.read_parquet(path)
        raise
    try:
        df.write_parquet(path)
    except Exception as e:
        _warn("could not write nba player index cache (%s)", e)
    return df


def resolve_player_id(name: str) -> int | None:
    """nba_api player id for a display name ("LeBron James").

    Exact match first, then punctuation-blind ("A.J. Brown" vs "AJ Brown").
    Returns None when unknown — callers treat that as "no data", not an error.
    """
    import polars as pl

    try:
        idx = _player_index()
    except Exception:
        return None
    hit = idx.filter(pl.col("full_name") == name)
    if hit.height:
        return int(hit["player_id"][0])

    def _norm(s: str) -> str:
        import re
        import unicodedata
        # NFKD decomposes accented chars (Dončić -> Doncic), then we drop
        # the combining marks — "Luka Doncic" must find "Luka Dončić".
        s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z ]+", "", s.lower()).strip()

    want = _norm(name)
    if not want:
        return None
    for r in idx.to_dicts():
        if _norm(r.get("full_name")) == want:
            return int(r["player_id"])
    # Last-name + first-initial fallback ("James" is ambiguous; skip those).
    cands = [r for r in idx.to_dicts()
             if _norm(r.get("full_name", "").split()[-1]) == want.split()[-1]]
    if len(cands) == 1:
        return int(cands[0]["player_id"])
    return None


def player_game_log(name: str, force: bool = False):
    """Per-game log for one player across SEASONS, newest first.

    Returns a polars DataFrame with GAME_COLS. Empty (0 rows, same schema)
    when the player is unknown or no games exist yet (offseason) — never
    raises for "no data", so the scan degrades honestly.
    """
    import polars as pl

    pid = resolve_player_id(name)
    if pid is None:
        return pl.DataFrame(schema={c: pl.Utf8 for c in GAME_COLS})

    safe = "".join(c if c.isalnum() else "_" for c in name)[:48]
    path = _path(f"gamelog_{safe}_{pid}")
    if not force and _fresh(path):
        return pl.read_parquet(path)

    frames = []
    try:
        from nba_api.stats.endpoints import playergamelog
        for season in SEASONS:
            try:
                df = playergamelog.PlayerGameLog(
                    player_id=pid, season=season).get_data_frames()[0]
            except Exception as e:
                _warn("nba game log pull failed for %s %s (%s)", name, season, e)
                continue
            if df is None or df.empty:
                continue
            df = df.copy()
            df["season"] = season
            # Rename nba_api's UPPERCASE columns to our schema; keep only
            # the columns we know (extra columns are ignored, missing ones
            # become null and are coerced below).
            df = df.rename(columns={k: v for k, v in _RAW_COLS.items()
                                    if k in df.columns})
            # No TEAM_ABBREVIATION in this endpoint — derive from MATCHUP
            # ("LAL vs. UTA" -> "LAL").
            if "team_abbr" not in df.columns and "matchup" in df.columns:
                df["team_abbr"] = (df["matchup"].astype(str)
                                   .str.extract(r"^([A-Z]{2,3})")[0])
            keep = [c for c in GAME_COLS if c in df.columns]
            frames.append(df[keep])
    except Exception as e:
        if os.path.exists(path):
            _warn("nba game log failed for %s (%s); serving cached copy", name, e)
            return pl.read_parquet(path)
        return pl.DataFrame(schema={c: pl.Utf8 for c in GAME_COLS})

    if not frames:
        if os.path.exists(path):
            return pl.read_parquet(path)
        return pl.DataFrame(schema={c: pl.Utf8 for c in GAME_COLS})

    import pandas as pd
    combined = pd.concat(frames, ignore_index=True)
    # Newest first; coerce numerics (nba_api sometimes returns strings).
    combined["game_date"] = pd.to_datetime(combined["game_date"], errors="coerce")
    combined = combined.sort_values("game_date", ascending=False)
    for c in ("MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK"):
        if c in combined.columns:
            combined[c] = pd.to_numeric(combined[c], errors="coerce").fillna(0)
    combined["is_preseason"] = 0
    out = pl.from_pandas(combined[[c for c in GAME_COLS if c in combined.columns]])
    try:
        out.write_parquet(path)
    except Exception as e:
        _warn("could not write nba game log cache for %s (%s)", name, e)
    return out


def preseason_game_log(name: str, force: bool = False):
    """2026-27 preseason game log for one player, newest first.

    Same GAME_COLS schema as player_game_log plus is_preseason=1.
    Empty (not an error) when the preseason hasn't started, the player
    didn't play, or the pull fails — the scan degrades honestly.
    Cached separately with a 6h TTL since games happen nightly.
    """
    import polars as pl

    pid = resolve_player_id(name)
    if pid is None:
        return pl.DataFrame(schema={c: pl.Utf8 for c in GAME_COLS})

    safe = "".join(c if c.isalnum() else "_" for c in name)[:48]
    path = _path(f"preseason_{safe}_{pid}")
    if not force and os.path.exists(path):
        import time
        if time.time() - os.path.getmtime(path) < PRESEASON_TTL:
            return pl.read_parquet(path)

    try:
        from nba_api.stats.endpoints import playergamelog
        df = playergamelog.PlayerGameLog(
            player_id=pid, season=PRESEASON_SEASON,
            season_type_all_star="Pre Season").get_data_frames()[0]
    except Exception as e:
        _warn("nba preseason pull failed for %s (%s)", name, e)
        if os.path.exists(path):
            return pl.read_parquet(path)
        return pl.DataFrame(schema={c: pl.Utf8 for c in GAME_COLS})
    if df is None or df.empty:
        return pl.DataFrame(schema={c: pl.Utf8 for c in GAME_COLS})

    import pandas as pd
    df = df.copy()
    df["season"] = PRESEASON_SEASON + " PRE"
    df = df.rename(columns={k: v for k, v in _RAW_COLS.items()
                            if k in df.columns})
    if "team_abbr" not in df.columns and "matchup" in df.columns:
        df["team_abbr"] = (df["matchup"].astype(str)
                           .str.extract(r"^([A-Z]{2,3})")[0])
    keep = [c for c in GAME_COLS if c in df.columns or c == "is_preseason"]
    df = df[[c for c in keep if c in df.columns]]
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    df = df.sort_values("game_date", ascending=False)
    for c in ("MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["is_preseason"] = 1
    out = pl.from_pandas(df[[c for c in GAME_COLS if c in df.columns]])
    try:
        out.write_parquet(path)
    except Exception as e:
        _warn("could not write nba preseason cache for %s (%s)", name, e)
    return out


def full_game_log(name: str, force: bool = False):
    """Regular-season log + preseason games on top, newest first.

    This is what the distribution builder uses: preseason is the freshest
    signal available before opening night, tagged is_preseason=1 so
    callers can label it honestly.
    """
    import polars as pl

    reg = player_game_log(name, force=force)
    pre = preseason_game_log(name, force=force)
    if pre.height == 0:
        return reg
    if reg.height == 0:
        return pre
    # Union schemas (preseason always has is_preseason; reg now does too).
    cols = GAME_COLS
    reg = reg.select([c for c in cols if c in reg.columns])
    pre = pre.select([c for c in cols if c in pre.columns])
    combined = pl.concat([pre, reg], how="diagonal")
    return combined.sort("game_date", descending=True)
