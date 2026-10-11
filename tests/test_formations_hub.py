"""Tests for tendencies/formations.py and teams/hub.py."""
import polars as pl
import pytest

from tendencies import formations as fmod
from teams import hub


def _pbp() -> pl.DataFrame:
    # Minimal fake play-by-play: 6 snaps for KC.
    return pl.DataFrame({
        "posteam": ["KC"] * 6,
        "play_type": ["pass", "pass", "run", "run", "pass", "run"],
        "season": [2026] * 6,
        "shotgun": [1, 1, 0, 0, 1, 0],
        "no_huddle": [0, 0, 0, 1, 0, 0],
        "run_location": [None, None, "left", "middle", None, "right"],
        "run_gap": [None, None, "guard", "tackle", None, "end"],
        "pass_location": ["left", "right", None, None, "middle", None],
        "yardline_100": [75, 60, 15, 10, 80, 50],
    })


def test_formation_detail_shotgun_splits():
    d = fmod.formation_detail(_pbp(), "KC")
    assert d["snaps"] == 6
    assert d["shotgun_rate"] == pytest.approx(0.5)
    # 3 shotgun snaps: all passes -> run rate 0.0
    assert d["run_rate_shotgun"] == pytest.approx(0.0, abs=0.01)
    # 3 under-center snaps: all runs -> run rate 1.0
    assert d["run_rate_under_center"] == pytest.approx(1.0, abs=0.01)
    assert d["no_huddle_rate"] == pytest.approx(1 / 6, abs=0.01)


def test_formation_detail_directions():
    d = fmod.formation_detail(_pbp(), "KC")
    dirs = {r["direction"]: r["share"] for r in d["run_direction"]}
    assert set(dirs) == {"left", "middle", "right"}
    assert sum(dirs.values()) == pytest.approx(1.0, abs=0.01)
    gaps = {r["gap"]: r["share"] for r in d["run_gap"]}
    assert set(gaps) == {"guard", "tackle", "end"}
    locs = {r["location"]: r["share"] for r in d["pass_location"]}
    assert set(locs) == {"left", "right", "middle"}


def test_formation_detail_empty_team():
    d = fmod.formation_detail(_pbp(), "NOBODY")
    assert d["snaps"] == 0
    assert d["shotgun_rate"] is None


def test_formation_detail_missing_columns():
    df = pl.DataFrame({"posteam": ["KC"], "play_type": ["run"],
                       "season": [2026]})
    d = fmod.formation_detail(df, "KC")
    assert d["snaps"] == 1
    assert d["shotgun_rate"] is None
    assert d["run_direction"] == []


def test_team_record():
    sched = pl.DataFrame({
        "season": [2026, 2026, 2026],
        "week": [1, 2, 3],
        "home_team": ["KC", "BUF", "KC"],
        "away_team": ["BUF", "KC", "DEN"],
        "home_score": [30, 20, 17],
        "away_score": [20, 24, 17],
    })
    r = hub.team_record(sched, "KC", 2026)
    assert (r["wins"], r["losses"], r["ties"]) == (2, 0, 1)


def test_team_record_unplayed_ignored():
    sched = pl.DataFrame({
        "season": [2026],
        "week": [9],
        "home_team": ["KC"],
        "away_team": ["DEN"],
        "home_score": [None],
        "away_score": [None],
    })
    r = hub.team_record(sched, "KC", 2026)
    assert r["games"] == 0


def test_team_schedule_upcoming_only():
    sched = pl.DataFrame({
        "season": [2026, 2026, 2026],
        "week": [4, 6, 7],
        "home_team": ["KC", "KC", "DEN"],
        "away_team": ["DEN", "LAC", "KC"],
        "gameday": ["2026-10-04", "2026-10-18", "2026-10-25"],
    })
    s = hub.team_schedule(sched, "KC", 2026, 6)
    assert len(s) == 2
    assert s[0]["opponent"] == "LAC" and s[0]["home_away"] == "vs"
    assert s[1]["opponent"] == "DEN" and s[1]["home_away"] == "@"


def test_home_renders_no_exceptions():
    # 2026-10-11: Home page referenced _gsched without importing it
    # (NameError) — the import only existed in the Scan tab. The landing
    # view must render clean since it's the default.
    import os
    from streamlit.testing.v1 import AppTest

    # app.py calls load_dotenv(): running it in-process leaks the repo's
    # .env (real LUMIFY_API_KEY) into os.environ, which flips later
    # lumify tests from sample to live mode. Snapshot and restore.
    _env = dict(os.environ)
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        at = AppTest.from_file(os.path.join(root, "app.py"), default_timeout=120)
        at.run()
        assert not at.exception, [str(e.value)[:120] for e in at.exception]
    finally:
        os.environ.clear()
        os.environ.update(_env)
