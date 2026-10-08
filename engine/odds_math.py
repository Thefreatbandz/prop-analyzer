"""The odds math, explained like a teacher (Learn mode).

A bet's price tells you what the BOOK thinks. We need everything in the
same language — probabilities — before we can compare.

1. American odds -> implied probability
   A $110 bet to win $100 (-110) means you must win 110/210 of the time
   just to break even. So:  implied = risk / (risk + win).
     -110 -> 110 / (110 + 100) = 52.38%
     +150 -> 100 / (150 + 100) = 40.00%   (a $100 bet wins $150)

2. Strip the vig ("no-vig" / fair book price)
   Add both sides: 52.38% + 52.38% = 104.76%. That extra 4.76% is the
   book's cut (the vig). Divide each side by the total and they sum to
   100% — that's the book's TRUE opinion with its profit removed.

3. American odds -> decimal odds (for EV math)
   Decimal odds = total returned per $1 staked (stake included).
     -110 -> 1 + 100/110 = 1.909
     +150 -> 1 + 150/100 = 2.500

4. Expected value
   EV% = (fair_prob * decimal_odds) - 1
   If our model says 54% and the book pays 1.909: 0.54 * 1.909 - 1 = +3.1%.
   Positive = the bet is mispriced in our favor. That's the whole game.
"""
from __future__ import annotations


def american_to_implied(odds: float) -> float:
    """-110 -> 0.5238, +150 -> 0.40. The break-even win rate."""
    if odds == 0:
        raise ValueError("odds cannot be 0")
    if odds < 0:
        return -odds / (-odds + 100.0)
    return 100.0 / (odds + 100.0)


def american_to_decimal(odds: float) -> float:
    """-110 -> 1.9091, +150 -> 2.5. Total returned per 1 unit staked."""
    if odds == 0:
        raise ValueError("odds cannot be 0")
    if odds < 0:
        return 1.0 + 100.0 / -odds
    return 1.0 + odds / 100.0


def decimal_to_american(decimal: float) -> float:
    """Inverse of american_to_decimal, for display."""
    if decimal <= 1.0:
        raise ValueError("decimal odds must be > 1.0")
    if decimal >= 2.0:
        return 100.0 * (decimal - 1.0)
    return -100.0 / (decimal - 1.0)


def no_vig_two_way(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Strip the book's cut from a two-sided market.

    Returns (fair_a, fair_b) summing to 1.0 — the book's true opinion.
    Example: (-110, -110) -> (0.5, 0.5). The 4.76% overround is gone.
    """
    pa = american_to_implied(odds_a)
    pb = american_to_implied(odds_b)
    total = pa + pb  # > 1.0 — the overround (vig) lives here
    return pa / total, pb / total


def ev_percent(fair_prob: float, decimal_odds: float) -> float:
    """Expected value as a fraction: +0.031 = +3.1% edge.

    fair_prob: OUR model's probability (0..1).
    decimal_odds: what the BOOK pays per unit staked.
    """
    if not 0.0 < fair_prob < 1.0:
        raise ValueError("fair_prob must be strictly between 0 and 1")
    return fair_prob * decimal_odds - 1.0


def kelly_fraction(fair_prob: float, decimal_odds: float) -> float:
    """Fraction of bankroll Kelly says to stake. v1 does NOT bet this —
    it's shown for education only. Flat paper units until the edge is
    proven (Kelly on an unproven edge is how bankrolls die)."""
    b = decimal_odds - 1.0  # net odds
    q = 1.0 - fair_prob
    return max(0.0, (b * fair_prob - q) / b)
