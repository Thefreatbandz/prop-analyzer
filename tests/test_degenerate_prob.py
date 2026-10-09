"""Degenerate model probabilities must never crash a scan.

Real case (2026-10-09, Sunday slate scan): fringe players with a few
identical games (e.g. n=3, std ~ 0.00005) make the Monte Carlo fair
probability collapse to exactly 0.0/1.0. ev_percent raises ValueError on
those, which used to kill the entire scan. These sides are now skipped
and counted loudly — noise stays noise, never a pick.
"""
import engine.picks as picks_mod


def _books(line, over=-110, under=-110):
    return [{"book": "draftkings", "line": line, "over": over, "under": under}]


def _prop(player, market, line):
    return {
        "player": player,
        "team": "XYZ",
        "market": market,
        "label": market,
        "books": _books(line),
    }


def test_degenerate_sides_skipped_not_crash():
    # Eli Raridon shape: mean 0.85, std 4.8e-05, line 1.5 -> P = exactly 0/1.
    board = [
        _prop("Eli Raridon", "player_receptions", 1.5),
        _prop("Real Player", "player_receptions", 4.5),
    ]
    dists = {
        "Eli Raridon": {
            "player_receptions": {"mean": 0.85, "std": 4.8e-05, "n": 3}
        },
        "Real Player": {
            "player_receptions": {"mean": 5.2, "std": 1.8, "n": 40}
        },
    }
    stats = {}
    ranked = picks_mod.rank_props(board, dists, min_ev=-1.0, sims=2000,
                                  stats=stats)
    # No crash; the fringe player's sides are gone, the real player survives.
    players = {p["player"] for p in ranked}
    assert "Eli Raridon" not in players
    assert "Real Player" in players
    # Loud: the skipped sides are counted.
    assert stats["degenerate_sides"] == 2


def test_degenerate_fades_skipped_not_crash():
    board = [_prop("Malachi Fields", "player_receptions", 2.5)]
    dists = {
        "Malachi Fields": {
            "player_receptions": {"mean": 2.0, "std": 3.2e-05, "n": 4}
        },
    }
    stats = {}
    fades = picks_mod.rank_fades(board, dists, max_ev=1.0, sims=2000,
                                 stats=stats)
    assert fades == []
    assert stats["degenerate_sides"] == 2


def test_healthy_dist_still_flags_edge():
    # A real edge must not be eaten by the guard.
    board = [_prop("Josh Allen", "player_pass_yds", 245.5)]
    dists = {
        "Josh Allen": {"player_pass_yds": {"mean": 278.4, "std": 44.2, "n": 34}}
    }
    stats = {}
    ranked = picks_mod.rank_props(board, dists, min_ev=0.0, sims=5000,
                                  stats=stats)
    assert len(ranked) >= 1
    assert stats["degenerate_sides"] == 0
    # stats is optional: omitting it keeps the old call shape working.
    ranked2 = picks_mod.rank_props(board, dists, min_ev=0.0, sims=5000)
    assert len(ranked2) >= 1
