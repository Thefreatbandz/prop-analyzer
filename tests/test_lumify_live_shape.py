"""Regression tests for the live Lumify API shape (found 2026-10-08).

The live /v1/events/{id}/player-props payload differs from our sample:
- books is a DICT keyed by book name (not a list of dicts), with the line
  at the prop level: {"draftkings": {"over": -110, "under": -105}}
- market keys are short (passing_yards, receiving_yards, ...) not player_*
- no label / team fields on each prop
- GET /v1/events without status=scheduled returns recent finals, so the
  "first upcoming event" logic found nothing to scan.

These tests pin the adapter behavior against that shape.
"""
from odds import lumify

LIVE_BOARD = {
    "event_id": "19689",
    "available": True,
    "sport": "nfl",
    "status": "scheduled",
    "player_props": [
        {
            "player": "Dak Prescott",
            "player_id": 244921,
            "market": "passing_yards",
            "line": 263.5,
            "books": {
                "pinnacle": {"over": -134, "under": 106},
                "draftkings": {"over": -112, "under": -112},
            },
        },
        {
            "player": "CeeDee Lamb",
            "player_id": 244912,
            "market": "receiving_yards",
            "line": 80.5,
            "books": {"draftkings": {"over": -113, "under": -111}},
        },
        {
            # combo market: no model distribution -> raw key kept, skipped honestly
            "player": "Dak Prescott",
            "player_id": 244921,
            "market": "pass_rush_yards",
            "line": 276.5,
            "books": {"draftkings": {"over": None, "under": -112}},
        },
        {
            # book with no prices on either side -> dropped
            "player": "Jalon Daniels",
            "player_id": 999001,
            "market": "passing_yards",
            "line": 210.5,
            "books": {"fanduel": {"over": None, "under": None}},
        },
    ],
}


def test_normalize_live_dict_books():
    props = lumify.normalize(LIVE_BOARD)
    # The all-null book row drops out entirely
    assert len(props) == 3
    dak = [p for p in props if p["player"] == "Dak Prescott"
           and p["market"] == "player_pass_yds"][0]
    assert dak["label"] == "Passing Yards"
    assert dak["books"] == [
        {"book": "pinnacle", "line": 263.5, "over": -134, "under": 106},
        {"book": "draftkings", "line": 263.5, "over": -112, "under": -112},
    ]


def test_live_markets_map_to_canonical_keys():
    props = lumify.normalize(LIVE_BOARD)
    by_player_market = {(p["player"], p["market"]): p for p in props}
    assert ("CeeDee Lamb", "player_rec_yds") in by_player_market
    # combo market keeps its raw key (engine skips: no distribution)
    assert ("Dak Prescott", "pass_rush_yards") in by_player_market
    combo = by_player_market[("Dak Prescott", "pass_rush_yards")]
    assert combo["label"] == "Pass + Rush Yards"
    # one-sided book row survives with the null side intact
    assert combo["books"] == [
        {"book": "draftkings", "line": 276.5, "over": None, "under": -112}
    ]


def test_sample_shape_still_works():
    board = lumify.load_sample()
    props = lumify.normalize(board)
    assert len(props) == 5
    allen = [p for p in props if p["player"] == "Josh Allen"][0]
    assert allen["market"] == "player_pass_yds"
    assert allen["label"] == "Passing yards"


def test_list_events_requests_scheduled(monkeypatch):
    seen = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"events": [{"id": 1, "status": "scheduled"}]}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen["params"] = params
        return Resp()

    monkeypatch.setattr(lumify.requests, "get", fake_get)
    monkeypatch.setattr(lumify, "_key", lambda: "lmfy-test")
    monkeypatch.setattr(lumify, "cached_get",
                        lambda source, key, ttl, fetcher, force=False: fetcher())
    events = lumify.list_events()
    assert seen["params"]["status"] == "scheduled"
    assert events == [{"id": 1, "status": "scheduled"}]


def test_get_player_props_full_slate(monkeypatch):
    """Default: every upcoming event with posted props is merged."""
    events = [
        {"id": 1, "status": "scheduled",
         "competitors": [{"abbreviation": "DEN"}, {"abbreviation": "LAC"}]},
        {"id": 2, "status": "scheduled",
         "competitors": [{"abbreviation": "DET"}, {"abbreviation": "ARI"}]},
        {"id": 3, "status": "scheduled"},  # no props posted -> skipped free
    ]
    empty = {"event_id": "3", "available": False, "player_props": []}
    monkeypatch.setattr(lumify, "list_events",
                        lambda status="scheduled", sport="nfl": events)
    monkeypatch.setattr(
        lumify, "fetch_props",
        lambda eid, sport="nfl", force=False:
            dict(LIVE_BOARD, event_id=str(eid)) if eid in (1, 2) else empty)
    monkeypatch.setattr(lumify, "_key", lambda: "lmfy-test")
    board = lumify.get_player_props()
    assert len(board["events_covered"]) == 2
    props = lumify.normalize(board)
    assert len(props) == 6  # 3 per game x 2 games
    games = {p["game"] for p in props}
    assert games == {"DEN @ LAC", "DET @ ARI"}


def test_get_player_props_single_game_opt_out(monkeypatch):
    """full_slate=False keeps the old first-event-only behavior."""
    events = [
        {"id": 1, "status": "scheduled"},
        {"id": 2, "status": "scheduled"},
    ]
    monkeypatch.setattr(lumify, "list_events",
                        lambda status="scheduled", sport="nfl": events)
    monkeypatch.setattr(lumify, "fetch_props",
                        lambda eid, sport="nfl", force=False: LIVE_BOARD)
    monkeypatch.setattr(lumify, "_key", lambda: "lmfy-test")
    board = lumify.get_player_props(full_slate=False)
    assert len(board["events_covered"]) == 1  # first event only
    assert len(lumify.normalize(board)) == 3


def test_get_player_props_no_games_with_props(monkeypatch):
    events = [{"id": 1, "status": "scheduled"}]
    monkeypatch.setattr(lumify, "list_events",
                        lambda status="scheduled", sport="nfl": events)
    monkeypatch.setattr(lumify, "fetch_props",
                        lambda eid, sport="nfl", force=False:
                            {"event_id": "1", "available": False,
                             "player_props": []})
    monkeypatch.setattr(lumify, "_key", lambda: "lmfy-test")
    board = lumify.get_player_props()
    assert board["props"] == []
    assert "no" in board["note"] and "props" in board["note"]
