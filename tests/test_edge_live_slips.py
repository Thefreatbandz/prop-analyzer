"""Tests for the live slip view: leg status derivation, parlay live
state, progress bars, and the no-entry-means-0 rule."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edge import (LEG_STATUS_DISPLAY, derive_leg_status, leg_live_detail,
                  leg_live_text, leg_progress_fraction, parlay_live_state)


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


def _leg(player, side, line, stat):
    return {"player": player, "side": side, "line": line, "stat": stat,
            "market": ""}


# --- derive_leg_status ---

def test_derive_live_over_states():
    # passing stats: YDS index 1. Over below the line is losing
    # (needs more, not decided); past it is clinched; at it is live.
    assert derive_leg_status("over", 200.0, 180.0, "live") == "losing"
    assert derive_leg_status("over", 200.0, 200.0, "live") == "live"
    assert derive_leg_status("over", 200.0, 215.0, "live") == "won"


def test_derive_live_under_states():
    # Under below the line is winning (room to spare); past it the
    # leg is busted — the stat cannot come back down.
    assert derive_leg_status("under", 80.5, 45.0, "live") == "winning"
    assert derive_leg_status("under", 80.5, 80.5, "live") == "live"
    assert derive_leg_status("under", 80.5, 88.0, "live") == "lost"


def test_derive_final_states_and_push():
    assert derive_leg_status("over", 200.0, 215.0, "final") == "won"
    assert derive_leg_status("over", 200.0, 180.0, "final") == "lost"
    assert derive_leg_status("over", 200.0, 200.0, "final") == "push"
    assert derive_leg_status("under", 80.5, 70.0, "final") == "won"
    assert derive_leg_status("under", 80.5, 88.0, "final") == "lost"
    assert derive_leg_status("under", 80.5, 80.5, "final") == "push"


# --- leg_live_detail ---

def test_live_detail_over_losing_and_clinched():
    leg = _leg("Patrick Mahomes", "over", 200.0, "passing yards")
    game = _fake_game("live", "Q3 4:12", {
        "Patrick Mahomes": {"passing": ["20/28", 180, 6.4, 2, 0, 1, 110.0]}})
    det = leg_live_detail(leg, [game])
    assert det["status"] == "losing" and det["current"] == 180.0
    assert det["game_status"] == "live" and det["game_detail"] == "Q3 4:12"
    assert det["no_category_entry"] is False
    assert "needs 20 more" in leg_live_text(leg, det)
    hit = _fake_game("live", "Q4 2:00", {
        "Patrick Mahomes": {"passing": ["24/32", 215, 6.7, 2, 0, 1, 112.0]}})
    det = leg_live_detail(leg, [hit])
    assert det["status"] == "won" and det["current"] == 215.0
    assert leg_live_text(leg, det).startswith("HIT")


def test_live_detail_under_winning_and_busted():
    leg = _leg("Josh Jacobs", "under", 80.5, "rushing yards")
    game = _fake_game("live", "Q2 8:00", {
        "Josh Jacobs": {"rushing": [9, 45, 5.0, 0, 12]}})
    det = leg_live_detail(leg, [game])
    assert det["status"] == "winning" and det["current"] == 45.0
    assert "35.5 to spare" in leg_live_text(leg, det)
    bust = _fake_game("live", "Q4 1:00", {
        "Josh Jacobs": {"rushing": [20, 88, 4.4, 1, 15]}})
    det = leg_live_detail(leg, [bust])
    assert det["status"] == "lost" and det["current"] == 88.0
    assert "leg lost" in leg_live_text(leg, det)


def test_live_detail_no_category_entry_is_zero_not_void():
    # Kupp is in the boxscore (rushing entry) but has no receiving
    # entry: his receiving leg is 0 yards — a real zero, not a void.
    leg = _leg("Cooper Kupp", "under", 10.5, "receiving yards")
    game = _fake_game("live", "Q2 8:00", {
        "Cooper Kupp": {"rushing": [1, 5, 5.0, 0, 5]}})
    det = leg_live_detail(leg, [game])
    assert det["current"] == 0.0 and det["no_category_entry"] is True
    assert det["status"] == "winning"  # 0 < 10.5 under
    assert "no entry in this category" in leg_live_text(leg, det)
    # Same shape on an over: 0 yards is losing, not void.
    over = _leg("Cooper Kupp", "over", 64.5, "receiving yards")
    det = leg_live_detail(over, [game])
    assert det["current"] == 0.0 and det["status"] == "losing"


def test_live_detail_missing_data_never_crashes():
    leg = _leg("Nobody", "over", 10.0, "receiving yards")
    # Empty boxscore dict: no data, not a crash, not a void.
    det = leg_live_detail(leg, [_fake_game("live", "Q1", {})])
    assert det["status"] == "no_data" and det["current"] is None
    assert leg_live_text(leg, det) == "no stats yet"
    # No games at all: same.
    det = leg_live_detail(leg, [])
    assert det["status"] == "no_data"
    # Player absent from a populated boxscore: still no_data.
    other = _fake_game("live", "Q1", {
        "Someone Else": {"receiving": [1, 5, 5.0, 0, 5]}})
    det = leg_live_detail(leg, [other])
    assert det["status"] == "no_data"


def test_live_detail_untrackable_and_bad_inputs():
    weird = _leg("Nobody", "over", 10.0, "mystery stat")
    det = leg_live_detail(weird, [])
    assert det["status"] == "untrackable"
    assert "unavailable" in leg_live_text(weird, det)
    # Missing line or unknown side never crashes the slip view.
    assert leg_live_detail({**weird, "stat": "passing yards",
                            "line": None}, [])["status"] == "untrackable"
    assert leg_live_detail({**weird, "stat": "passing yards",
                            "side": "exactly"}, [])["status"] == "untrackable"


def test_live_detail_final_reports_ready_to_grade():
    leg = _leg("Josh Jacobs", "under", 80.5, "rushing yards")
    game = _fake_game("final", "Final", {
        "Josh Jacobs": {"rushing": [18, 70, 3.9, 0, 14]}})
    det = leg_live_detail(leg, [game])
    assert det["status"] == "won" and det["game_status"] == "final"
    assert "ready to grade" in leg_live_text(leg, det)
    push_game = _fake_game("final", "Final", {
        "Josh Jacobs": {"rushing": [18, 80.5, 3.9, 0, 14]}})
    det = leg_live_detail(leg, [push_game])
    assert det["status"] == "push"
    assert "push, ready to grade" in leg_live_text(leg, det)


# --- progress bar fraction ---

def test_progress_fraction():
    assert leg_progress_fraction(200.0, 100.0) == 0.5
    assert leg_progress_fraction(200.0, 0.0) == 0.0
    assert leg_progress_fraction(200.0, 250.0) == 1.0  # capped
    assert leg_progress_fraction(200.0, None) is None
    assert leg_progress_fraction(None, 100.0) is None
    assert leg_progress_fraction(0, 100.0) is None


# --- parlay live state ---

def test_parlay_live_state():
    assert parlay_live_state(["won", "won"]) == "WON"
    assert parlay_live_state(["won", "push"]) == "WON"  # push voids, not loses
    assert parlay_live_state(["push", "push"]) == "VOID"
    assert parlay_live_state(["won", "live"]) == "ALIVE"
    assert parlay_live_state(["winning", "losing"]) == "ALIVE"
    assert parlay_live_state(["won", "lost"]) == "DEAD"
    assert parlay_live_state(["lost", "winning"]) == "DEAD"  # one bust kills it
    assert parlay_live_state(["no_data", "winning"]) == "ALIVE"
    assert parlay_live_state([]) == "ALIVE"


def test_status_display_covers_every_status():
    # Every status the derivation can return has a label + color + bar.
    for s in ("won", "lost", "winning", "losing", "live", "push",
              "no_data", "untrackable"):
        label, color, fill = LEG_STATUS_DISPLAY[s]
        assert label and color.startswith("#") and fill.startswith("hit-")
