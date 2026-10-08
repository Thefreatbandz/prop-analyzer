"""nflverse data layer — free NFL stats, cached locally as parquet.

Covers the locked data window: 2015 season through present. Data refreshes
nightly during the season, so cached files older than 24h are re-pulled.
No API key needed — this is the $0 backbone of the projections.
"""
from __future__ import annotations

import os
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "nflverse")
SEASONS = list(range(2015, 2027))  # 2015–present (locked decision)
MAX_AGE_SECONDS = 24 * 60 * 60


def _path(name: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, f"{name}.parquet")


def _fresh(path: str) -> bool:
    return os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE_SECONDS


def _load(name: str, loader, seasons: list[int], force: bool = False):
    """Generic pull-or-load: parquet cache first, nflverse on miss/stale."""
    import polars as pl

    # Cache key includes the season range — a 2024-2025 slice must never
    # masquerade as the full 2015-2026 window.
    key = f"{name}_{seasons[0]}_{seasons[-1]}"
    path = _path(key)
    if not force and _fresh(path):
        return pl.read_parquet(path)
    import nflreadpy as nfl

    df = loader(seasons=seasons)
    if not isinstance(df, pl.DataFrame):
        df = pl.from_pandas(df)
    df.write_parquet(path)
    return df


def player_stats(seasons: list[int] | None = None, force: bool = False):
    """Weekly player box scores (passing/rushing/receiving yards, TDs, ...)."""
    import nflreadpy as nfl

    seasons = seasons or SEASONS
    return _load("player_stats", nfl.load_player_stats, seasons, force)


def injuries(seasons: list[int] | None = None, force: bool = False):
    """Weekly injury reports (report_status: Questionable/Doubtful/Out...)."""
    import nflreadpy as nfl

    seasons = seasons or SEASONS
    return _load("injuries", nfl.load_injuries, seasons, force)


def snap_counts(seasons: list[int] | None = None, force: bool = False):
    """Snap counts — usage trends feed the recency weighting."""
    import nflreadpy as nfl

    seasons = seasons or SEASONS
    return _load("snap_counts", nfl.load_snap_counts, seasons, force)


def rosters(season: int | None = None, force: bool = False):
    """Current rosters (default: latest season in the window)."""
    import nflreadpy as nfl

    season = season or SEASONS[-1]
    return _load(f"rosters_{season}", nfl.load_rosters, [season], force)


def schedules(seasons: list[int] | None = None, force: bool = False):
    """Game schedules + dates (used to find the current NFL week)."""
    import nflreadpy as nfl

    seasons = seasons or SEASONS[-3:]  # only recent seasons needed
    return _load("schedules", nfl.load_schedules, seasons, force)


def pbp(seasons: list[int] | None = None, force: bool = False):
    """Charted play-by-play. REG+POST only — nflverse does NOT chart
    preseason games (verified 2026-10-07: schedules list no PRE games,
    player_stats has season_type REG/POST only). Used for tendencies.

    Big files (~50MB/season); default to the recent window only.
    """
    import nflreadpy as nfl

    seasons = seasons or SEASONS[-3:]
    return _load("pbp", nfl.load_pbp, seasons, force)


def teams(force: bool = False):
    """Team metadata (includes a few historical rows — filter to the
    32 current teams via players.get_teams). Note: load_teams takes no
    seasons argument, so it bypasses the generic _load helper."""
    import nflreadpy as nfl
    import polars as pl

    path = _path("teams")
    if not force and _fresh(path):
        return pl.read_parquet(path)
    df = nfl.load_teams()
    if not isinstance(df, pl.DataFrame):
        df = pl.from_pandas(df)
    df.write_parquet(path)
    return df


def depth_charts(season: int | None = None, force: bool = False):
    """Weekly depth charts (season only — no preseason charting in
    the free data)."""
    import nflreadpy as nfl

    season = season or SEASONS[-1]
    return _load(f"depth_charts_{season}", nfl.load_depth_charts, [season], force)
