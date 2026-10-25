"""Tests for The Edge: parlay grouping, odds math, status, learning."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edge import (combined_prob, learning_summary, leg_market,
                  leg_progress, load_parlays, parlay_odds, parlay_status,
                  progress_text)


def _fake_game(status, detail, stats_by_player):
    """One game in live.espn boxscore shape.

    stats_by_player: {display_name: {category: stats_list}}.
    """
    from live.espn import norm_name

    cats: dict = {}
    for name, cat_stats in stats_by_player.items():
        for cat, stats in cat_stats.items():
            cats.setdefault(cat, {})[norm_name(name)] = {
                "name": name, "stats": stats}
    return {"status": status, "detail": detail,
            "boxscore": {"KC": cats}}


def test_leg_market_maps_labels_and_passthrough():
    assert leg_market({"stat": "passing yards", "market": ""}) == "player_pass_yds"
    assert leg_market({"stat": "receptions", "market": ""}) == "player_receptions"
    assert leg_market({"stat": "Receiving TDs", "market": ""}) == "player_rec_tds"
    assert leg_market({"stat": "passing yards",
                       "market": "player_pass_yds"}) == "player_pass_yds"
    assert leg_market({"stat": "mystery stat", "market": ""}) == ""


def test_leg_progress_live_over_states():
    leg = {"player": "Patrick Mahomes", "side": "over", "line": 200.0,
           "stat": "passing yards", "market": ""}
    # passing stats: C/ATT/YDS/YPA/TD/INT/SACKS/RTG -> YDS index 1.
    live_game = _fake_game("live", "Q3 4:12", {
        "Patrick Mahomes": {"passing": ["20/28", 180, 6.4, 2, 0, 1, 110.0]}})
    prog = leg_progress(leg, [live_game])
    assert prog["state"] == "live" and prog["current"] == 180.0
    assert progress_text(leg, prog, "2026-10-25", "2026-10-25") == (
        "180 / 200 passing yards — needs 20 more")
    hit_game = _fake_game("live", "Q4 2:00", {
        "Patrick Mahomes": {"passing": ["24/32", 215, 6.7, 2, 0, 1, 112.0]}})
    prog = leg_progress(leg, [hit_game])
    assert progress_text(leg, prog, "2026-10-25", "2026-10-25").startswith("HIT")


def test_leg_progress_under_spare_and_lost_and_final():
    leg = {"player": "Josh Jacobs", "side": "under", "line": 80.5,
           "stat": "rushing yards", "market": ""}
    # rushing stats: CAR/YDS/YPA/TD/LONG -> YDS index 1.
    live_game = _fake_game("live", "Q2 8:00", {
        "Josh Jacobs": {"rushing": [9, 45, 5.0, 0, 12]}})
    prog = leg_progress(leg, [live_game])
    assert progress_text(leg, prog, "2026-10-25", "2026-10-25") == (
        "45 / 80.5 rushing yards — 35.5 to spare")
    lost_game = _fake_game("live", "Q4 1:00", {
        "Josh Jacobs": {"rushing": [20, 88, 4.4, 1, 15]}})
    prog = leg_progress(leg, [lost_game])
    assert "leg lost" in progress_text(leg, prog, "2026-10-25", "2026-10-25")
    final_game = _fake_game("final", "Final", {
        "Josh Jacobs": {"rushing": [18, 70, 3.9, 0, 14]}})
    prog = leg_progress(leg, [final_game])
    assert prog["state"] == "final"
    assert "ready to grade" in progress_text(
        leg, prog, "2026-10-25", "2026-10-26")


def test_leg_progress_no_stats_and_not_started_and_untrackable():
    leg = {"player": "Nobody", "side": "over", "line": 10.0,
           "stat": "receiving yards", "market": ""}
    prog = leg_progress(leg, [_fake_game("live", "Q1", {})])
    assert prog["state"] == "no_stats"
    assert progress_text(leg, prog, "2026-10-25", "2026-10-25") == "no stats yet"
    assert progress_text(leg, prog, "2026-10-26", "2026-10-25") == "not started"
    weird = {"player": "Nobody", "side": "over", "line": 10.0,
             "stat": "mystery stat", "market": ""}
    prog = leg_progress(weird, [])
    assert prog["state"] == "untrackable"
    assert "unavailable" in progress_text(weird, prog, None, "2026-10-25")


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
    for i, row in enumerate(rows, start=1):
        (name, player, side, line, book, price, prob, ev,
         result) = row[:9]
        label, market = row[9] if len(row) > 9 else ("stat", "")
        detail = {"player": player, "side": side, "line": line,
                  "label": label, "market": market, "book": book,
                  "price": price, "fair_prob": prob, "ev_pct": ev,
                  "type": "prop"}
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


def _draft_leg(player, side, line, stat, price, prob):
    return {"player": player, "side": side, "line": line, "stat": stat,
            "market": "", "book": "caesars", "price": price,
            "fair_prob": prob, "ev_pct": None}


def test_validate_draft_blocks_short_duplicate_and_nameless():
    from edge import low_prob_legs, validate_draft

    one = [_draft_leg("A", "over", 10.0, "passing yards", -110, 0.6)]
    assert "need at least 2 legs" in validate_draft(one, "P")
    two = [_draft_leg("A", "over", 10.0, "passing yards", -110, 0.6),
           _draft_leg("A", "over", 20.0, "passing yards", -110, 0.6)]
    assert any("duplicate" in e for e in validate_draft(two, "P"))
    ok = [_draft_leg("A", "over", 10.0, "passing yards", -110, 0.6),
          _draft_leg("B", "under", 5.0, "rushing yards", -110, 0.6)]
    assert validate_draft(ok, "P") == []
    assert "parlay name required" in validate_draft(ok, "   ")
    # Same player, different stat is fine.
    ok2 = [_draft_leg("A", "over", 10.0, "passing yards", -110, 0.6),
           _draft_leg("A", "over", 5.0, "rushing yards", -110, 0.6)]
    assert validate_draft(ok2, "P") == []


def test_low_prob_legs_warn_only():
    from edge import low_prob_legs, validate_draft

    draft = [_draft_leg("A", "over", 10.0, "passing yards", -110, 0.5),
             _draft_leg("B", "under", 5.0, "rushing yards", -110, 0.7)]
    assert [d["player"] for d in low_prob_legs(draft)] == ["A"]
    # A sub-55% leg warns but does not block the save.
    assert validate_draft(draft, "P") == []


def test_draft_combined_prob_and_odds():
    draft = [_draft_leg("Mahomes", "over", 200.0, "passing yards",
                        -197, 0.83),
             _draft_leg("Kupp", "over", 10.0, "receiving yards",
                        -420, 0.875),
             _draft_leg("Horton", "over", 10.0, "receiving yards",
                        -150, 0.729)]
    assert abs(combined_prob(draft) - 0.83 * 0.875 * 0.729) < 1e-9
    assert parlay_odds(draft) == 211
    draft[0]["fair_prob"] = None
    assert combined_prob(draft) is None  # unknown prob -> no combined number


def _grade_db(tmp_path, rows):
    """DB with parlay legs; returns path. Rows use _make_db format."""
    return _make_db(tmp_path / "g.db", rows)


def _fake_sb_and_bs():
    """Scoreboard + boxscores for 2026-10-25: KC@SEA final, GB@DET final."""
    from live.espn import norm_name

    def bs(players):
        cats: dict = {}
        for name, cat_stats in players.items():
            for cat, stats in cat_stats.items():
                cats.setdefault(cat, {})[norm_name(name)] = {
                    "name": name, "stats": stats}
        return {"KC": cats}  # team key is irrelevant to the lookup

    sb = [
        {"id": "g1", "away": "KC", "home": "SEA", "status": "final",
         "detail": "Final"},
        {"id": "g2", "away": "GB", "home": "DET", "status": "final",
         "detail": "Final"},
    ]
    boxes = {
        "g1": bs({
            "Patrick Mahomes": {"passing": ["24/32", 215, 6.7, 2, 0, 1, 112.0]},
            "Cooper Kupp": {"receiving": [3, 14, 4.7, 0, 9, 5]},
        }),
        "g2": bs({
            "Jared Goff": {"passing": ["28/35", 240, 6.9, 2, 1, 0, 105.0]},
            "Jahmyr Gibbs": {"rushing": [15, 68, 4.5, 1, 20]},
            "Josh Jacobs": {"rushing": [18, 70, 3.9, 0, 14]},
        }),
    }
    return sb, boxes


def test_grade_pending_final_win_loss_and_void(tmp_path, monkeypatch):
    import tracker.db as tdb
    from edge import grade_pending

    db = _grade_db(tmp_path, [
        ("SNF", "Patrick Mahomes", "over", 200.0, "caesars", -197, 0.83,
         25.13, None, ("passing yards", "player_pass_yds")),
        ("SNF", "Cooper Kupp", "over", 20.0, "caesars", -420, 0.875,
         8.28, None, ("receiving yards", "player_rec_yds")),
        ("SNF", "Ghost Player", "over", 10.0, "caesars", -110, 0.6,
         5.0, None, ("receiving yards", "player_rec_yds")),
    ])
    sb, boxes = _fake_sb_and_bs()
    monkeypatch.setattr(tdb, "DB", db)
    rep = grade_pending(db, lambda d: sb, lambda e: boxes[e])
    graded = {(leg["player"], res) for _, leg, res, _ in rep["graded"]}
    assert ("Patrick Mahomes", "win") in graded  # 215 > 200
    assert ("Cooper Kupp", "loss") in graded  # 14 < 20
    assert len(rep["voided"]) == 1  # Ghost: no game, all final -> push
    # Grades persisted.
    import sqlite3
    conn = sqlite3.connect(db)
    results = dict(conn.execute(
        "SELECT id, result FROM picks ORDER BY id").fetchall())
    conn.close()
    assert results == {1: "win", 2: "loss", 3: "push"}


def test_grade_pending_played_but_no_category_entry_is_zero(tmp_path,
                                                            monkeypatch):
    import tracker.db as tdb
    from edge import grade_pending

    # Kupp has a rushing entry only; his receiving leg is 0 yards.
    from live.espn import norm_name
    sb = [{"id": "g1", "away": "KC", "home": "SEA", "status": "final",
           "detail": "Final"}]
    boxes = {"g1": {"KC": {"rushing": {
        norm_name("Cooper Kupp"): {"name": "Cooper Kupp",
                                   "stats": [1, 5, 5.0, 0, 5]}}}}}
    db = _grade_db(tmp_path, [
        ("SNF", "Cooper Kupp", "under", 10.0, "caesars", -110, 0.6,
         5.0, None, ("receiving yards", "player_rec_yds")),
    ])
    monkeypatch.setattr(tdb, "DB", db)
    rep = grade_pending(db, lambda d: sb, lambda e: boxes[e])
    assert rep["graded"][0][2] == "win"  # 0 < 10, not a void
    assert rep["graded"][0][3] == 0.0


def test_grade_pending_skips_live_and_pre(tmp_path, monkeypatch):
    import tracker.db as tdb
    from edge import grade_pending

    sb = [{"id": "g1", "away": "KC", "home": "SEA", "status": "live",
           "detail": "Q3"},
          {"id": "g2", "away": "DAL", "home": "PHI", "status": "pre",
           "detail": "Mon 8:15"}]
    boxes = {"g1": {}, "g2": {}}
    db = _grade_db(tmp_path, [
        ("SNF", "Patrick Mahomes", "over", 200.0, "caesars", -197, 0.83,
         25.13, None, ("passing yards", "player_pass_yds")),
    ])
    monkeypatch.setattr(tdb, "DB", db)
    # Mahomes not in any boxscore and not all games final -> pending.
    rep = grade_pending(db, lambda d: sb, lambda e: boxes[e])
    assert rep["graded"] == [] and len(rep["skipped_pending"]) == 1


def test_grade_pending_hypothetical_extras_reported_not_written(
        tmp_path, monkeypatch):
    import tracker.db as tdb
    from edge import grade_pending

    sb, boxes = _fake_sb_and_bs()
    db = _grade_db(tmp_path, [
        ("GB-DET 2026-10-25 PAPER-HYPOTHETICAL", "Jared Goff", "over",
         225.5, "HYPOTHETICAL", -110, 0.824, 0.0, None,
         ("passing yards", "player_pass_yds")),
    ])
    monkeypatch.setattr(tdb, "DB", db)
    rep = grade_pending(db, lambda d: sb, lambda e: boxes[e])
    # Goff graded from the tracker; Gibbs/Jacobs reported, not written.
    assert rep["graded"][0][2] == "win"  # 240 > 225.5
    hyp = {e["player"]: (s, implied)
           for e, s, implied in rep["hypothetical"]}
    assert hyp["Jahmyr Gibbs"] == (68.0, "win")  # 68 > 50.5 over
    assert hyp["Josh Jacobs"] == (70.0, "win")  # 70 < 80.5 under
    import sqlite3
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM picks").fetchone()[0]
    conn.close()
    assert n == 1  # extras never inserted
