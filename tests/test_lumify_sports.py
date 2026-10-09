"""Sport plumbing for the Lumify adapter (NFL/NBA/MLB).

Pins: sport param on list_events/fetch_props/get_player_props/load_sample,
sport-keyed cache entries, per-sport market maps, sample boards, and the
invalid-sport guard. The NFL default path must keep working untouched.
"""
import json
import os

import pytest

from odds import lumify


def _sample_path(sport):
    return os.path.join(os.path.dirname(lumify.__file__),
                        "samples", f"{sport}_player_props.json")


def test_invalid_sport_rejected():
    for fn in (lumify.load_sample, lumify._check_sport):
        with pytest.raises(ValueError):
            fn("nhl")
    with pytest.raises(ValueError):
        lumify.get_player_props(sport="nba2k")


def test_sample_boards_exist_and_load():
    for sport in ("nfl", "nba", "mlb"):
        assert os.path.exists(_sample_path(sport)), f"missing {sport} sample"
        board = lumify.load_sample(sport)
        assert board["props"], f"{sport} sample has no props"


def test_nba_market_map():
    board = lumify.load_sample("nba")
    props = lumify.normalize(board, sport="nba")
    by_player = {p["player"]: p for p in props}
    assert by_player["LeBron James"]["market"] == "player_points"
    assert by_player["Luka Doncic"]["market"] == "player_pra"
    assert by_player["Stephen Curry"]["market"] == "player_threes"
    assert by_player["Jrue Holiday"]["market"] == "player_steals"
    assert by_player["LeBron James"]["label"] == "Points"


def test_mlb_market_map():
    board = lumify.load_sample("mlb")
    props = lumify.normalize(board, sport="mlb")
    by_key = {(p["player"], p["market"]) for p in props}
    assert ("Aaron Judge", "player_hits") in by_key
    assert ("Aaron Judge", "player_home_runs") in by_key
    assert ("Gerrit Cole", "player_so_pitcher") in by_key
    assert ("Shane Bieber", "player_outs_recorded") in by_key


def test_unmapped_market_kept_raw():
    # Markets with no model mapping keep their raw key and are skipped
    # honestly downstream — never silently mis-mapped.
    board = {"props": [{
        "player": "X", "market": "some_future_market", "line": 1.5,
        "books": [{"book": "draftkings", "line": 1.5, "over": -110, "under": -110}],
    }]}
    props = lumify.normalize(board, sport="nba")
    assert props[0]["market"] == "some_future_market"


def test_list_events_passes_sport(monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(params or {})

        class R:
            def raise_for_status(self): pass

            def json(self): return {"events": []}
        return R()

    monkeypatch.setattr(lumify.requests, "get", fake_get)
    monkeypatch.setattr(lumify, "_key", lambda: "lmfy-test")
    assert lumify.list_events(sport="mlb") == []
    assert seen.get("sport") == "mlb"
    assert lumify.list_events() == []  # default still NFL
    assert seen.get("sport") == "nfl"


def test_fetch_props_cache_key_includes_sport(monkeypatch, tmp_path):
    keys = []

    def fake_cached_get(source, key, ttl, fetcher, force=False):
        keys.append((source, key))
        return {"props": []}

    monkeypatch.setattr(lumify, "cached_get", fake_cached_get)
    monkeypatch.setattr(lumify, "_key", lambda: "lmfy-test")
    lumify.fetch_props("evt1", sport="nba")
    lumify.fetch_props("evt1", sport="nfl")
    assert ("lumify", "nba_props_evt1") in keys
    assert ("lumify", "nfl_props_evt1") in keys
    # Same event id across sports must NOT share a cache entry.
    assert keys[0] != keys[1]


def test_get_player_props_no_key_serves_sample(monkeypatch):
    monkeypatch.setattr(lumify, "_key", lambda: None)
    for sport in ("nfl", "nba", "mlb"):
        board = lumify.get_player_props(sport=sport)
        assert board["props"], f"{sport} fell back to empty, not sample"


def test_normalize_default_is_nfl():
    # Old callers that don't pass sport keep the NFL behavior.
    board = lumify.load_sample()
    props = lumify.normalize(board)
    assert props[0]["market"] == "player_pass_yds"


def test_get_player_props_skips_dead_events(monkeypatch):
    # 2026-10-09: MLB's first listed event had no posted props while the
    # third did — blind-first selection broke the whole sport scan.
    # get_player_props must skip to the first event with actual props.
    import odds.lumify as lum

    dead = {"id": "e1", "name": "Dead Game", "status": "scheduled"}
    live = {"id": "e2", "name": "Live Game", "status": "scheduled"}
    monkeypatch.setattr(lum, "list_events", lambda status="scheduled", sport="nfl": [dead, live])

    def fake_fetch(event_id, sport="nfl", force=False):
        if event_id == "e1":
            return {"player_props": [], "available": False}
        return {"player_props": [{"player": "P", "market": "hits", "line": 0.5,
                                  "books": {"dk": {"over": -110, "under": -110}}}],
                "available": True}

    monkeypatch.setattr(lum, "fetch_props", fake_fetch)
    monkeypatch.setattr(lum, "_key", lambda: "fake-key")
    board = lum.get_player_props(sport="mlb")
    props = board.get("player_props", [])
    assert len(props) == 1 and props[0]["player"] == "P"


def test_get_player_props_all_dead_returns_honest_empty(monkeypatch):
    import odds.lumify as lum

    dead = {"id": "e1", "name": "Dead Game", "status": "scheduled"}
    monkeypatch.setattr(lum, "list_events", lambda status="scheduled", sport="nfl": [dead])
    monkeypatch.setattr(lum, "fetch_props",
                        lambda event_id, sport="nfl", force=False: {"player_props": []})
    monkeypatch.setattr(lum, "_key", lambda: "fake-key")
    board = lum.get_player_props(sport="mlb")
    assert board.get("player_props", board.get("props", [])) == []
    assert "note" in board
