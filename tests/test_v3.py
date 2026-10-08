"""v3 feature tests — search, suggestions, moneyline-degraded state, and
dashboard boot. All on synthetic data (zero downloads, zero keys) except
the AppTest boot, which uses local caches + sample boards.

Note (2026-10-07, Tbandz): personal/opinion favorites were REMOVED —
suggestions are 100% data-driven (EV + news). Social "favorited by
people" needs accounts + backend and is not built or faked.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import polars as pl
import pytest

from odds import the_odds_api
from players import search, suggest


# ---------- synthetic fixtures ----------
def _rosters():
    return pl.DataFrame(
        [
            {"full_name": "Josh Allen", "first_name": "Josh", "last_name": "Allen",
             "team": "BUF", "position": "QB", "jersey_number": 17},
            {"full_name": "Allen Lazard", "first_name": "Allen", "last_name": "Lazard",
             "team": "NYJ", "position": "WR", "jersey_number": 10},
            {"full_name": "Lamar Jackson", "first_name": "Lamar", "last_name": "Jackson",
             "team": "BAL", "position": "QB", "jersey_number": 8},
            {"full_name": "Ja'Marr Chase", "first_name": "Ja'Marr", "last_name": "Chase",
             "team": "CIN", "position": "WR", "jersey_number": 1},
        ]
    )


def _prop_picks():
    return [
        {"type": "prop", "player": "Josh Allen", "team": "BUF",
         "market": "player_pass_yds", "label": "Passing yards",
         "side": "over", "line": 267.5, "price": -110, "ev_pct": 4.2},
        {"type": "prop", "player": "Josh Allen", "team": "BUF",
         "market": "player_rush_yds", "label": "Rushing yards",
         "side": "over", "line": 32.5, "price": -105, "ev_pct": 2.1},
        {"type": "prop", "player": "Lamar Jackson", "team": "BAL",
         "market": "player_pass_yds", "label": "Passing yards",
         "side": "under", "line": 240.5, "price": 100, "ev_pct": 6.8},
    ]


def _news():
    return [
        {"headline": "Lamar Jackson limited in practice with knee issue",
         "description": "Ravens QB Jackson missed drills", "link": "x", "published": "t"},
        {"headline": "Bills prepare for Sunday",
         "description": "Josh Allen speaks to media about the matchup", "link": "y", "published": "t"},
    ]


# ---------- search ----------
def test_search_partial_name():
    hits = search.search_players(_rosters(), "allen")
    names = [h["name"] for h in hits]
    assert "Josh Allen" in names and "Allen Lazard" in names
    # Starts-with outranks contains: "Allen Lazard" first for "allen".
    assert names[0] == "Allen Lazard"


def test_search_case_insensitive():
    hits = search.search_players(_rosters(), "CHASE")
    assert [h["name"] for h in hits] == ["Ja'Marr Chase"]


def test_search_carries_team_and_position():
    hits = search.search_players(_rosters(), "lamar")
    assert hits[0]["team"] == "BAL" and hits[0]["position"] == "QB"


def test_search_no_result_and_empty_query():
    assert search.search_players(_rosters(), "zzzznobody") == []
    assert search.search_players(_rosters(), "") == []
    assert search.search_players(_rosters(), "   ") == []


def test_search_limit():
    hits = search.search_players(_rosters(), "a", limit=2)
    assert len(hits) == 2


# ---------- suggestions ----------
def test_suggest_from_ev_ranked_unique():
    sugs = suggest.suggest_from_ev(_prop_picks())
    assert [s["name"] for s in sugs] == ["Lamar Jackson", "Josh Allen"]
    assert sugs[0]["ev_pct"] == 6.8
    assert "under 240.5" in sugs[0]["reason"]


def test_suggest_trending_counts_mentions():
    sugs = suggest.suggest_trending(_news(), _rosters())
    names = [s["name"] for s in sugs]
    assert "Lamar Jackson" in names and "Josh Allen" in names
    assert all("In the news" in s["reason"] for s in sugs)


def test_suggestions_merge_dedupes_and_labels():
    sugs = suggest.suggestions(_prop_picks(), _news(), _rosters())
    names = [s["name"] for s in sugs]
    assert len(names) == len(set(names))  # no duplicates
    assert names[0] == "Lamar Jackson"  # EV signal first
    assert all(s["source"] in ("ev", "news") for s in sugs)
    assert all("reason" in s and s["reason"] for s in sugs)


# ---------- moneyline degraded state ----------
def test_moneyline_no_key_degrades(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    games, note = the_odds_api.get_moneylines_strict()
    assert games == []
    assert note is not None
    assert "props only" in note.lower()


def test_moneyline_unreachable_degrades(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "fake-key-for-test")
    def _boom(*a, **k):
        raise ConnectionError("dns down")
    monkeypatch.setattr(the_odds_api, "fetch_live", _boom)
    games, note = the_odds_api.get_moneylines_strict()
    assert games == []
    assert note is not None and "didn't come through" in note
    # User-safe copy: no key names, no exception types for the public.
    assert "ODDS_API_KEY" not in note and "Error" not in note


def test_moneyline_adapter_intact_for_key_arrival():
    # The classic path still exists: sample fallback + normalize untouched.
    board = the_odds_api.load_sample()
    games = the_odds_api.normalize(board)
    assert isinstance(games, list)


# ---------- dashboard boot ----------
def test_dashboard_boots_with_new_views(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "")
    monkeypatch.setenv("LUMIFY_API_KEY", "")
    from streamlit.testing.v1 import AppTest

    app_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
    at = AppTest.from_file(app_path, default_timeout=180)
    at.run()
    assert not at.exception, f"dashboard raised: {at.exception}"
    labels = []
    try:
        labels = [t.label for t in at.tabs]
    except Exception:
        pass
    if labels:  # label introspection is best-effort across versions
        for want in ("Scan", "Track Record", "Builder", "Alerts", "Players",
                     "Compare"):
            assert want in labels, f"missing tab: {want} in {labels}"
        assert "Favorites" not in labels, \
            "personal favorites were removed — tab must be gone"
    # The degraded-moneyline notice must render, not crash.
    infos = [str(getattr(i, "value", "")) for i in at.info]
    assert any("props only" in v.lower() for v in infos), \
        "expected the moneyline-degraded notice in the Scan tab"
