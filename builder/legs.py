"""Prop builder (SGP-style) pricing.

A "same-game parlay" (SGP) combines several legs — e.g. Josh Allen
over 267.5 pass yards AND James Cook over 64.5 rush yards — into one
bet at one combined price. This module prices each leg with our model
and combines them.

Learn mode — the math:
  * Each leg gets a fair probability from the Monte Carlo engine
    (same as the Scan tab): P(Allen over 267.5) = 58%.
  * The NAIVE combined probability multiplies them: 0.58 × 0.52 = 30%.
  * Then the honesty part (below): legs in the same game are
    CORRELATED, so the naive number OVERSTATES the truth.

HONESTY REQUIREMENT (Tbandz's rule): always show the naive number AND
the correlation caution. Never present the product as the true
probability — it is an UPPER BOUND.
"""
from __future__ import annotations

# Shown next to every combined probability. Non-negotiable.
CORRELATION_NOTE = (
    "Same-game legs are correlated — they move together. If Allen throws "
    "for 350 yards, Cook probably didn't grind out 120 on the ground in "
    "the same game. Simple multiplication treats the legs as independent, "
    "which OVERSTATES the true probability. Treat the combined number as "
    "an upper bound, not the truth."
)

# Markets the builder supports (subset of the model's STAT_MAP that
# makes sense as SGP legs).
BUILDER_MARKETS = {
    "player_pass_yds": "Passing yards",
    "player_pass_tds": "Passing TDs",
    "player_rush_yds": "Rushing yards",
    "player_rush_tds": "Rushing TDs",
    "player_receptions": "Receptions",
    "player_rec_yds": "Receiving yards",
    "player_rec_tds": "Receiving TDs",
}


def price_leg(player: str, market: str, side: str, line: float,
              distributions: dict, sims: int = 10_000) -> dict | None:
    """Fair probability for one leg. None if we have no projection.

    distributions: {player: {market: {"mean","std","n",...}}} — the same
    shape the Scan tab uses (sample or live).
    """
    from projections.montecarlo import prob_over, prob_under, stable_seed

    dist = (distributions.get(player) or {}).get(market)
    if not dist or dist.get("do_not_bet"):
        return None
    mean, std = dist["mean"], dist["std"]
    seed = stable_seed(player, market, side, line)
    if side == "over":
        fair_p = prob_over(mean, std, line, n=sims, seed=seed)
    else:
        fair_p = prob_under(mean, std, line, n=sims, seed=seed)
    return {
        "player": player,
        "market": market,
        "label": BUILDER_MARKETS.get(market, market),
        "side": side,
        "line": line,
        "fair_p": round(fair_p, 4),
        "mean": round(mean, 1),
        "std": round(std, 1),
        "n_games": dist.get("n"),
    }


def combine_legs(fair_ps: list[float]) -> dict:
    """Naive combined probability = product of leg probabilities.

    Returns the product plus the honesty framing. Callers MUST display
    CORRELATION_NOTE alongside this number.
    """
    combined = 1.0
    for p in fair_ps:
        combined *= p
    return {
        "combined_p": round(combined, 4),
        "n_legs": len(fair_ps),
        "method": "naive_product",
        "caution": CORRELATION_NOTE,
    }


def sgp_ev(combined_p: float, book_american: float) -> dict:
    """EV of the SGP vs the book's combined price.

    book_american: the SGP odds the book offers (e.g. +260). Entered by
    the user — we never place the bet, we only do the math.
    """
    from engine.odds_math import american_to_decimal, ev_percent

    dec = american_to_decimal(book_american)
    ev = ev_percent(combined_p, dec)
    return {
        "combined_p": round(combined_p, 4),
        "book_american": book_american,
        "book_decimal": round(dec, 3),
        "ev_pct": round(ev * 100, 2),
        "caution": CORRELATION_NOTE,
    }
