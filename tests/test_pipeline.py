"""End-to-end pipeline test on SAMPLE data — zero keys, zero downloads.

Exercises: sample odds load -> normalize -> sample distributions ->
Monte Carlo -> rank_props / rank_moneylines -> tracker log/grade/CLV.
"""
import json
import os
import tempfile

import engine.picks as picks_mod
from engine.odds_math import american_to_decimal
from odds import lumify, the_odds_api
from projections.montecarlo import prob_over


def _sample_dists():
    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "projections", "samples", "player_distributions.json",
    )
    with open(path) as f:
        return json.load(f)["projections"]


def test_moneyline_pipeline_sample():
    board = the_odds_api.get_moneylines()  # no key -> sample
    games = the_odds_api.normalize(board)
    assert len(games) == 2
    assert games[0]["home"] == "Kansas City Chiefs"
    assert "pinnacle" in games[0]["books"]
    ranked = picks_mod.rank_moneylines(games, min_ev=0.0)
    # Every pick must carry the math explanation and a sane EV
    for p in ranked:
        assert p["type"] == "moneyline"
        assert "math" in p and "EV" in p["math"]
        assert isinstance(p["ev_pct"], float)
    # Sanity: best book is never worse than the worst book
    assert all(p["shop_uplift_pct"] >= 0 for p in ranked)


def test_props_pipeline_sample():
    board = lumify.get_player_props()  # no key -> sample
    props = lumify.normalize(board)
    assert len(props) == 5
    dists = _sample_dists()
    ranked = picks_mod.rank_props(props, dists, min_ev=-1.0, sims=2000)
    assert len(ranked) > 0
    # Mahomes is Questionable in the sample dists -> flag must surface
    mahomes = [p for p in ranked if p["player"] == "Patrick Mahomes"]
    assert mahomes and mahomes[0]["injury_flag"] is not None
    # EV ordering: sorted desc
    evs = [p["ev_pct"] for p in ranked]
    assert evs == sorted(evs, reverse=True)


def test_montecarlo_sanity():
    # Mean well above the line -> high over prob; far below -> low.
    assert prob_over(300, 40, 267.5, n=5000, seed=1) > 0.7
    assert prob_over(200, 40, 267.5, n=5000, seed=1) < 0.1
    # Deterministic with seed
    a = prob_over(270, 45, 267.5, n=2000, seed=42)
    b = prob_over(270, 45, 267.5, n=2000, seed=42)
    assert a == b


def test_tracker_log_grade_clv(tmp_path, monkeypatch):
    import tracker.db as db

    monkeypatch.setattr(db, "DB", str(tmp_path / "t.db"))
    pick = {
        "type": "prop", "player": "Josh Allen", "side": "over",
        "label": "Passing yards", "book": "draftkings", "line": 267.5,
        "price": -110, "fair_prob": 0.56, "ev_pct": 3.5,
    }
    pid = db.log_pick(pick, game_date="2026-10-12")
    assert pid is not None
    # Closing line moved our way: -110 -> -130 (shorter = market agrees)
    db.set_closing(pid, -130)
    clv = db.clv_for(pid)
    assert clv is not None and clv > 0, f"expected positive CLV, got {clv}"
    db.grade_result(pid, "win")
    s = db.weekly_summary(days=365)
    assert s["picks_graded"] == 1
    assert s["win_rate"] == 1.0
    assert s["profit_units"] > 0
    assert s["picks_until_real_money"] == 99
