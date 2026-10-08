"""Builder + premium-tier tests: SGP pricing, saved builds, watchlist,
line-movement detection, backtest lab. All on synthetic data.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import polars as pl
import pytest

from builder import legs as blegs
from builder import saves as bsaves
from alerts import watchlist as wl
from backtest import lab as blab
from ui import cards as ui_cards


def _dists():
    return {
        "Josh Allen": {
            "player_pass_yds": {"mean": 270.0, "std": 45.0, "n": 20},
        }
    }


def test_price_leg_over_high_line_is_likely():
    leg = blegs.price_leg("Josh Allen", "player_pass_yds", "over",
                          200.0, _dists(), sims=2000)
    assert leg is not None
    assert leg["fair_p"] > 0.9  # 270 avg vs 200 line


def test_price_leg_under_high_line_is_likely():
    leg = blegs.price_leg("Josh Allen", "player_pass_yds", "under",
                          350.0, _dists(), sims=2000)
    assert leg is not None
    assert leg["fair_p"] > 0.9


def test_price_leg_unknown_player_is_none():
    assert blegs.price_leg("Nobody Here", "player_pass_yds", "over",
                           250.0, _dists()) is None


def test_combine_legs_is_naive_product_with_caution():
    out = blegs.combine_legs([0.6, 0.5])
    assert out["combined_p"] == pytest.approx(0.30)
    assert out["method"] == "naive_product"
    assert "upper bound" in out["caution"].lower()


def test_correlation_note_is_honest():
    assert "upper bound" in blegs.CORRELATION_NOTE.lower()
    assert "correlat" in blegs.CORRELATION_NOTE.lower()


def test_sgp_ev_math():
    # 30% fair at +260 (3.6x): EV = 0.3*3.6 - 1 = +8%.
    out = blegs.sgp_ev(0.30, 260)
    assert out["ev_pct"] == pytest.approx(8.0)
    assert "caution" in out


def _tmpdb():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def test_saves_roundtrip():
    path = _tmpdb()
    legs = [{"player": "Josh Allen", "market": "player_pass_yds",
             "side": "over", "line": 267.5, "fair_p": 0.58}]
    bid = bsaves.save_build("Sunday special", legs, 0.58, 260, 8.0,
                            path=path)
    assert bid > 0
    got = bsaves.list_builds(path=path)
    assert len(got) == 1 and got[0]["name"] == "Sunday special"
    assert got[0]["legs"][0]["player"] == "Josh Allen"
    bsaves.delete_build(got[0]["id"], path=path)
    assert bsaves.list_builds(path=path) == []


def test_saves_reject_empty():
    path = _tmpdb()
    with pytest.raises(ValueError):
        bsaves.save_build("", [{"player": "x"}], path=path)
    with pytest.raises(ValueError):
        bsaves.save_build("name", [], path=path)


def test_watchlist_add_remove():
    path = _tmpdb()
    wl.add_watch("Josh Allen", "player_pass_yds", path=path)
    wl.add_watch("Josh Allen", "player_pass_yds", path=path)  # idempotent
    got = wl.list_watch(path=path)
    assert len(got) == 1
    wl.remove_watch("Josh Allen", "player_pass_yds", path=path)
    assert wl.list_watch(path=path) == []


def _board(line, over, under, book="draftkings"):
    return [{"player": "Josh Allen", "market": "player_pass_yds",
             "books": [{"book": book, "line": line,
                        "over": over, "under": under}]}]


def test_detect_line_movement():
    path = _tmpdb()
    wl.add_watch("Josh Allen", "player_pass_yds", path=path)
    wl.snapshot_board(_board(267.5, -110, -110), path=path)
    alerts = wl.detect_movements(_board(269.5, -110, -110), path=path)
    assert len(alerts) == 1
    assert any("line" in r for r in alerts[0]["reasons"])


def test_detect_odds_movement():
    path = _tmpdb()
    wl.add_watch("Josh Allen", "player_pass_yds", path=path)
    wl.snapshot_board(_board(267.5, -110, -110), path=path)
    alerts = wl.detect_movements(_board(267.5, -125, -105), path=path)
    assert len(alerts) == 1
    assert any("over" in r for r in alerts[0]["reasons"])


def test_detect_ignores_small_moves():
    path = _tmpdb()
    wl.add_watch("Josh Allen", "player_pass_yds", path=path)
    wl.snapshot_board(_board(267.5, -110, -110), path=path)
    # 1.0 pt line move and 5c odds move are both under thresholds.
    assert wl.detect_movements(_board(268.5, -115, -105),
                               path=path) == []


def test_detect_no_snapshot_no_alerts():
    path = _tmpdb()
    assert wl.detect_movements(_board(300.0, -110, -110), path=path) == []


def _lab_df():
    rows = []
    yds = [240.0, 265.0, 250.0, 275.0, 245.0, 260.0, 255.0, 270.0]
    for w in range(1, 9):
        rows.append({"player_display_name": "Test QB", "season": 2026,
                     "week": w, "season_type": "REG",
                     "passing_yards": yds[w - 1], "rushing_yards": 20.0,
                     "receptions": 0.0, "receiving_yards": 0.0,
                     "passing_tds": 2.0, "rushing_tds": 0.0,
                     "receiving_tds": 0.0})
    return pl.DataFrame(rows)


def test_lab_runs_and_scores():
    res = blab.run_lab(_lab_df(), 2026, 5, 6)
    assert res["n_predictions"] > 0
    assert 0.0 <= res["brier"] <= 1.0
    assert res["buckets"]  # buckets populated
    assert "not a betting" in res["note"].lower() or "P&L" in res["note"]


def test_lab_reports_per_market():
    res = blab.run_lab(_lab_df(), 2026, 5, 6)
    assert set(res["markets"]) == set(blab.LAB_STATS)
    for m in res["markets"].values():
        assert {"n", "brier", "base_rate", "buckets"} <= set(m)


def test_lab_is_walk_forward_no_lookahead():
    # _weighted_dist for week 5 must ignore weeks 5+ (constant 250s
    # everywhere, so use a spike to detect leakage).
    games = [(2026, w, 250.0 if w < 5 else 999.0) for w in range(1, 9)]
    d = blab._weighted_dist(games, 2026, 5)
    assert d is not None
    assert d["mean"] == pytest.approx(250.0)
    assert d["n"] == 4  # weeks 1-4 only


def test_premium_lock_html():
    html = ui_cards.premium_lock_html("Backtest lab", ["Calibration"])
    assert "Premium" in html and "Backtest lab" in html


def _log_graded(db, price, closing, result, ev=5.0):
    pick = {
        "type": "prop", "player": "P", "side": "over", "label": "Yds",
        "book": "b", "line": 250.0, "price": price,
        "fair_prob": 0.56, "ev_pct": ev,
    }
    pid = db.log_pick(pick)
    db.set_closing(pid, closing)
    db.grade_result(pid, result)
    return pid


def test_track_record_math_and_gate(tmp_path, monkeypatch):
    import tracker.db as db

    monkeypatch.setattr(db, "DB", str(tmp_path / "t.db"))
    # 2 wins + 1 loss (graded) + 1 logged-but-ungraded.
    _log_graded(db, -110, -130, "win")
    _log_graded(db, -110, -105, "win")
    _log_graded(db, -110, -110, "loss")
    pid4 = db.log_pick({
        "type": "prop", "player": "Q", "side": "under", "label": "Yds",
        "book": "b", "line": 60.0, "price": -110,
        "fair_prob": 0.55, "ev_pct": 4.0,
    })

    tr = db.track_record()
    assert tr["picks_logged"] == 4
    assert tr["picks_graded"] == 3
    assert tr["win_rate"] == pytest.approx(2 / 3, abs=0.001)
    # 2 wins at -110 (0.909u each) - 1 loss (1u) = +0.818u on 3u staked.
    assert tr["profit_units"] == pytest.approx(0.82, abs=0.01)
    assert tr["roi"] == pytest.approx(0.818 / 3, abs=0.01)
    # CLV: -110 -> -130 moved our way twice (positive), -110 -> -110 flat.
    assert tr["avg_clv_pts"] is not None and tr["avg_clv_pts"] > 0
    # Gate: 3 of 100, not done.
    assert tr["gate_target"] == 100
    assert not tr["gate_done"]
    assert tr["picks_until_real_money"] == 97
    # The ungraded pick doesn't move the numbers.
    assert db.track_record()["picks_graded"] == 3
    db.grade_result(pid4, "push")
    assert db.track_record()["picks_graded"] == 4


def test_track_record_empty_is_honest(tmp_path, monkeypatch):
    import tracker.db as db

    monkeypatch.setattr(db, "DB", str(tmp_path / "t.db"))
    tr = db.track_record()
    assert tr["picks_logged"] == 0
    assert tr["win_rate"] is None
    assert tr["roi"] is None
    assert not tr["gate_done"]
