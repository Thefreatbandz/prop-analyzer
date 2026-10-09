"""MLB data layer + distribution builder tests.

Statcast is mocked — these pin the pitch->game aggregation, the RBI
parsing, the ID-resolution fallbacks, and the honest-skip contract
(runs/earned_runs have no data source and must never get a distribution).
"""
import pandas as pd
import polars as pl
import pytest

from projections import build, mlb_data, model


def _fake_statcast_batter():
    # Two games of pitch-level rows. Terminal PA events only on last pitch.
    return pd.DataFrame([
        # Game 1: single (1 RBI: runner scores), strikeout, HR (2 RBI)
        {"game_date": "2026-09-14", "events": "single",
         "des": "Aaron Judge singles. Ben Rice scores."},
        {"game_date": "2026-09-14", "events": "strikeout",
         "des": "Aaron Judge strikes out swinging."},
        {"game_date": "2026-09-14", "events": "home_run",
         "des": "Aaron Judge homers (30). Cody Bellinger scores."},
        {"game_date": "2026-09-14", "events": None, "des": None},  # mid-PA pitch
        # Game 2: quiet
        {"game_date": "2026-09-13", "events": "field_out",
         "des": "Aaron Judge flies out."},
        {"game_date": "2026-09-13", "events": "walk",
         "des": "Aaron Judge walks."},
    ])


def _fake_statcast_pitcher():
    return pd.DataFrame([
        {"game_date": "2026-09-14", "events": "strikeout", "des": "x"},
        {"game_date": "2026-09-14", "events": "strikeout", "des": "x"},
        {"game_date": "2026-09-14", "events": "single", "des": "x"},
        {"game_date": "2026-09-14", "events": "groundout", "des": "x"},
        {"game_date": "2026-09-13", "events": "home_run", "des": "x"},
        {"game_date": "2026-09-13", "events": "walk", "des": "x"},
    ])


@pytest.fixture
def mock_mlb(monkeypatch, tmp_path):
    monkeypatch.setattr(mlb_data, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(mlb_data, "resolve_player",
                        lambda name: 999 if name == "Test Player" else None)

    import pybaseball
    monkeypatch.setattr(pybaseball, "statcast_batter",
                        lambda s, e, pid: _fake_statcast_batter())
    monkeypatch.setattr(pybaseball, "statcast_pitcher",
                        lambda s, e, pid: _fake_statcast_pitcher())
    return tmp_path


def test_rbi_from_des():
    assert mlb_data._rbi_from_des(
        "Aaron Judge homers (30). Cody Bellinger scores.", "home_run") == 2
    assert mlb_data._rbi_from_des(
        "Aaron Judge singles. Ben Rice scores.", "single") == 1
    assert mlb_data._rbi_from_des(
        "Aaron Judge strikes out swinging.", "strikeout") == 0
    assert mlb_data._rbi_from_des(None, "home_run") == 1  # solo shot, no des
    assert mlb_data._rbi_from_des(None, "single") == 0
    # statcast uses NaN for empty text — must never reach re (Benintendi bug).
    assert mlb_data._rbi_from_des(float("nan"), "single") == 0
    assert mlb_data._rbi_from_des(float("nan"), "home_run") == 1


def test_batter_aggregation(mock_mlb):
    log = mlb_data.batter_game_log("Test Player")
    assert log.height == 2
    g1 = log.filter(pl.col("game_date") == "2026-09-14").to_dicts()[0]
    assert g1["H"] == 2      # single + HR
    assert g1["HR"] == 1
    assert g1["TB"] == 5     # 1 + 4
    assert g1["SO"] == 1
    assert g1["BB"] == 0
    assert g1["RBI"] == 3    # 1 + 2
    g2 = log.filter(pl.col("game_date") == "2026-09-13").to_dicts()[0]
    assert g2["H"] == 0 and g2["BB"] == 1 and g2["RBI"] == 0
    # Newest first.
    assert log["game_date"][0] == "2026-09-14"


def test_pitcher_aggregation(mock_mlb):
    log = mlb_data.pitcher_game_log("Test Player")
    assert log.height == 2
    g1 = log.filter(pl.col("game_date") == "2026-09-14").to_dicts()[0]
    assert g1["SO"] == 2
    assert g1["outs"] == 3   # 2 K + groundout
    assert g1["H_allowed"] == 1
    g2 = log.filter(pl.col("game_date") == "2026-09-13").to_dicts()[0]
    assert g2["H_allowed"] == 1 and g2["BB"] == 1 and g2["outs"] == 0


def test_unknown_player_is_empty_not_crash(mock_mlb):
    assert mlb_data.batter_game_log("Nobody McNobody").height == 0
    assert mlb_data.pitcher_game_log("Nobody McNobody").height == 0


def test_stat_maps_cover_sample_markets():
    for m in ("player_hits", "player_home_runs", "player_rbis",
              "player_total_bases", "player_stolen_bases", "player_so_batter"):
        assert m in model.MLB_BATTER_STAT_MAP
    for m in ("player_so_pitcher", "player_outs_recorded", "player_hits_allowed"):
        assert m in model.MLB_PITCHER_STAT_MAP
    # Honest gaps: no data source, deliberately unmapped.
    assert "player_runs" not in model.MLB_BATTER_STAT_MAP
    assert "player_earned_runs" not in model.MLB_PITCHER_STAT_MAP


def test_build_mlb_distributions_shape(mock_mlb):
    dists = build.build_mlb_distributions([
        ("Test Player", "NYY", "player_hits"),
        ("Test Player", "NYY", "player_total_bases"),
        ("Test Player", "NYY", "player_so_pitcher"),  # pitcher market
        ("Test Player", "NYY", "player_runs"),        # unmapped -> skipped
        ("Nobody McNobody", "XXX", "player_hits"),    # unknown -> skipped
    ])
    assert set(dists) == {"Test Player"}
    assert dists["Test Player"]["player_hits"]["n"] == 2
    # Recency-weighted: newest game (H=2) outweighs the older (H=0).
    assert dists["Test Player"]["player_hits"]["mean"] == pytest.approx(1.0, abs=0.1)
    assert dists["Test Player"]["player_total_bases"]["mean"] == pytest.approx(2.5, abs=0.2)
    # Pitcher market resolves via the pitching log (same stubbed player).
    assert "player_so_pitcher" in dists["Test Player"]
    assert "player_runs" not in dists["Test Player"]


def test_mlbam_stats_api_fallback(monkeypatch, tmp_path):
    # Chadwick misses -> MLB Stats API fills the gap (Jose Ramirez case).
    monkeypatch.setattr(mlb_data, "DATA_DIR", str(tmp_path))

    import pybaseball

    def fake_lookup(last, first):
        return pd.DataFrame()  # Chadwick has nothing

    monkeypatch.setattr(pybaseball, "playerid_lookup", fake_lookup)

    class R:
        def raise_for_status(self): pass

        def json(self): return {"people": [{"id": 608070}]}

    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    assert mlb_data.resolve_mlbam_id("Jose", "Ramirez") == 608070
