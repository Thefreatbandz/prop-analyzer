"""UI redesign tests — pick-card helpers in ui/cards.py.

Pure logic (no Streamlit boot): market mapping, hit counting,
shading, mini-bar HTML, pick filtering. All on synthetic data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import cards


def test_market_column_known_markets():
    assert cards.market_column("player_pass_yds") == "passing_yards"
    assert cards.market_column("player_rush_yds") == "rushing_yards"
    assert cards.market_column("player_rec_yds") == "receiving_yards"
    assert cards.market_column("player_receptions") == "receptions"


def test_market_column_unknown_is_none():
    # Unknown markets must degrade (no bars), never crash the card.
    assert cards.market_column("player_first_td") is None
    assert cards.market_column("") is None


def test_category_chips_cover_every_mapped_market():
    from projections import model as pmodel

    covered = {m for ms in cards.CATEGORY_MARKETS.values() for m in ms}
    for market in pmodel.STAT_MAP:
        assert market in covered, f"{market} has no chip"


def test_hit_stats_over():
    # 300, 280, 310 beat 267.5; 250, 200 don't.
    hits, n = cards.hit_stats([300, 250, 280, 200, 310], 267.5, "over")
    assert (hits, n) == (3, 5)


def test_hit_stats_under():
    # Under 267.5: 250 and 200 hit.
    hits, n = cards.hit_stats([300, 250, 280, 200, 310], 267.5, "under")
    assert (hits, n) == (2, 5)


def test_hit_stats_push_and_none():
    # Exactly on the line = push (counts as a game, not a hit).
    # None (didn't play) is skipped entirely.
    hits, n = cards.hit_stats([267.5, None, 300], 267.5, "over")
    assert (hits, n) == (1, 2)


def test_hit_shade_thresholds():
    assert cards.hit_shade(0.80) == "hit-good"
    assert cards.hit_shade(0.60) == "hit-good"
    assert cards.hit_shade(0.50) == "hit-mid"
    assert cards.hit_shade(0.40) == "hit-bad"
    assert cards.hit_shade(0.0) == "hit-bad"
    assert cards.hit_shade(None) == "hit-na"


def test_mini_bars_html_marks_hits_and_misses():
    html = cards.mini_bars_html([300, 200], 267.5, "over")
    assert html.count('class="mbar ') == 2
    assert 'mbar hit' in html and 'mbar miss' in html
    assert 'title="300"' in html


def test_mini_bars_html_empty():
    assert cards.mini_bars_html([], 267.5, "over") == ""
    assert cards.mini_bars_html([None, None], 267.5, "over") == ""


def _picks():
    return [
        {"type": "prop", "player": "Josh Allen", "market": "player_pass_yds",
         "side": "over", "ev_pct": 4.2},
        {"type": "prop", "player": "Josh Allen", "market": "player_rush_yds",
         "side": "over", "ev_pct": 3.1},
        {"type": "prop", "player": "Stefon Diggs", "market": "player_receptions",
         "side": "under", "ev_pct": 2.5},
        {"type": "moneyline", "team": "BUF", "ev_pct": 5.0},
    ]


def test_filter_picks_category():
    picks = _picks()
    got = cards.filter_picks(picks, "Pass Yds", "All")
    assert [p["market"] for p in got] == ["player_pass_yds"]


def test_filter_picks_side():
    picks = _picks()
    got = cards.filter_picks(picks, "All", "Under")
    assert len(got) == 1 and got[0]["side"] == "under"


def test_filter_picks_tds_groups_three_markets():
    picks = [
        {"type": "prop", "market": "player_pass_tds", "side": "over"},
        {"type": "prop", "market": "player_rush_tds", "side": "over"},
        {"type": "prop", "market": "player_rec_tds", "side": "over"},
        {"type": "prop", "market": "player_pass_yds", "side": "over"},
    ]
    got = cards.filter_picks(picks, "TDs", "All")
    assert len(got) == 3


def test_filter_picks_moneyline_only_under_all():
    picks = _picks()
    got = cards.filter_picks(picks, "All", "All")
    assert any(p["type"] == "moneyline" for p in got)
    got2 = cards.filter_picks(picks, "Rush Yds", "All")
    assert not any(p["type"] == "moneyline" for p in got2)


def test_get_player_props_skips_final_games(monkeypatch):
    # Real bug (2026-10-07): the adapter took events[0], which can be a
    # completed game with no props. It must skip finals.
    from odds import lumify

    monkeypatch.setenv("LUMIFY_API_KEY", "test-key")
    events = [
        {"id": 1, "name": "A at B", "status": "final"},
        {"id": 2, "name": "C at D", "status": "scheduled"},
    ]
    monkeypatch.setattr(lumify, "list_events", lambda: events)
    seen = {}

    def fake_fetch(event_id, force=False):
        seen["id"] = event_id
        return {"props": [], "available": True}

    monkeypatch.setattr(lumify, "fetch_props", fake_fetch)
    lumify.get_player_props()
    assert seen["id"] == 2


def test_get_player_props_no_upcoming_is_honest(monkeypatch):
    from odds import lumify

    monkeypatch.setenv("LUMIFY_API_KEY", "test-key")
    monkeypatch.setattr(
        lumify, "list_events",
        lambda: [{"id": 1, "name": "A at B", "status": "final"}])
    out = lumify.get_player_props()
    assert out["props"] == [] and "note" in out
