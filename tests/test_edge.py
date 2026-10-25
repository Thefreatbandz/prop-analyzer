"""Tests for The Edge: parlay grouping, odds math, status, learning."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edge import (combined_prob, learning_summary, load_parlays,
                  parlay_odds, parlay_status)


def _make_db(path, rows):
    db_path = str(path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE picks (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               logged_at REAL, game_date TEXT, type TEXT, label TEXT,
               book TEXT, line REAL, price REAL, fair_prob REAL,
               ev_pct REAL, closing_price REAL, result TEXT,
               profit_units REAL, detail TEXT)"""
    )
    for i, (name, player, side, line, book, price, prob, ev, result) in enumerate(rows, start=1):
        detail = {"player": player, "side": side, "line": line,
                  "label": "stat", "book": book, "price": price,
                  "fair_prob": prob, "ev_pct": ev, "type": "prop"}
        if name:
            detail["parlay"] = name
        conn.execute(
            "INSERT INTO picks (id, game_date, type, label, book, line,"
            " price, fair_prob, ev_pct, result, detail)"
            " VALUES (?, '2026-10-25', 'prop', 'stat', ?, ?, ?, ?, ?, ?, ?)",
            (i, book, line, price, prob, ev, result, json.dumps(detail)),
        )
    conn.commit()
    conn.close()
    return db_path


def test_grouping_ignores_non_parlay_picks(tmp_path):
    db = _make_db(tmp_path / "t.db", [
        ("SNF 3-legger", "A", "over", 10.0, "caesars", -110, 0.6, 5.0, None),
        (None, "B", "over", 20.0, "caesars", -110, 0.6, 5.0, None),
        ("SNF 3-legger", "C", "under", 5.0, "novig", -110, 0.7, 6.0, None),
    ])
    parlays = load_parlays(db)
    assert len(parlays) == 1
    assert parlays[0]["name"] == "SNF 3-legger"
    assert [leg["player"] for leg in parlays[0]["legs"]] == ["A", "C"]


def test_combined_prob_and_parlay_odds(tmp_path):
    # Mahomes -197, Kupp -420, Horton -150 -> ~53% and +211.
    db = _make_db(tmp_path / "t.db", [
        ("P", "Mahomes", "over", 200.0, "caesars", -197, 0.83, 25.13, None),
        ("P", "Kupp", "over", 10.0, "caesars", -420, 0.875, 8.28, None),
        ("P", "Horton", "over", 10.0, "caesars", -150, 0.729, 21.48, None),
    ])
    (parlay,) = load_parlays(db)
    assert abs(combined_prob(parlay["legs"]) - 0.83 * 0.875 * 0.729) < 1e-9
    assert parlay_odds(parlay["legs"]) == 211


def test_status_pending_then_won_and_lost(tmp_path):
    db = _make_db(tmp_path / "a.db", [
        ("P", "A", "over", 10.0, "caesars", -110, 0.6, 5.0, None),
        ("P", "B", "over", 10.0, "caesars", -110, 0.6, 5.0, "win"),
    ])
    (parlay,) = load_parlays(db)
    assert parlay_status(parlay) == "PENDING"
    db2 = _make_db(tmp_path / "b.db", [
        ("P", "A", "over", 10.0, "caesars", -110, 0.6, 5.0, "win"),
        ("P", "B", "over", 10.0, "caesars", -110, 0.6, 5.0, "push"),
    ])
    (parlay2,) = load_parlays(db2)
    assert parlay_status(parlay2) == "WON"  # wins + voids = won
    db3 = _make_db(tmp_path / "c.db", [
        ("P", "A", "over", 10.0, "caesars", -110, 0.6, 5.0, "win"),
        ("P", "B", "over", 10.0, "caesars", -110, 0.6, 5.0, "loss"),
    ])
    (parlay3,) = load_parlays(db3)
    assert parlay_status(parlay3) == "LOST"


def test_learning_summary_buckets_graded_legs(tmp_path):
    db = _make_db(tmp_path / "t.db", [
        ("P", "A", "over", 10.0, "caesars", -110, 0.6, 5.0, "win"),
        ("P", "B", "under", 10.0, "novig", -110, 0.6, 5.0, "loss"),
        ("P", "C", "over", 10.0, "caesars", -110, 0.6, 5.0, None),
    ])
    s = learning_summary(db)
    assert s["graded_legs"] == 2
    assert s["by_side"]["over"] == {"wins": 1, "losses": 0}
    assert s["by_side"]["under"] == {"wins": 0, "losses": 1}
    assert s["by_book"]["caesars"] == {"wins": 1, "losses": 0}


def test_missing_db_returns_empty():
    assert load_parlays("/nonexistent/dir/tracker.db") == []
