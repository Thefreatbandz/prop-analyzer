"""Known-answer tests for the odds math. If any of these fail, the whole
product's numbers are wrong — that's why they're tested to 4 decimals."""
import math

from engine.odds_math import (
    american_to_decimal,
    american_to_implied,
    decimal_to_american,
    ev_percent,
    kelly_fraction,
    no_vig_two_way,
)


def approx(a, b, tol=1e-4):
    assert abs(a - b) < tol, f"{a} != {b}"


def test_implied_negative():
    # -110: risk 110 to win 100 -> 110/210
    approx(american_to_implied(-110), 110 / 210)


def test_implied_positive():
    # +150: risk 100 to win 150 -> 100/250
    approx(american_to_implied(150), 100 / 250)


def test_implied_even():
    approx(american_to_implied(100), 0.5)
    approx(american_to_implied(-100), 0.5)


def test_implied_big_favorite():
    # -200 -> 200/300
    approx(american_to_implied(-200), 200 / 300)


def test_decimal_negative():
    approx(american_to_decimal(-110), 1 + 100 / 110)


def test_decimal_positive():
    approx(american_to_decimal(150), 2.5)


def test_decimal_roundtrip():
    for o in (-250, -110, -101, 100, 150, 300):
        approx(decimal_to_american(american_to_decimal(o)), o, tol=1e-9)


def test_no_vig_even():
    # -110/-110: the classic coin flip with 4.76% overround -> (0.5, 0.5)
    a, b = no_vig_two_way(-110, -110)
    approx(a, 0.5)
    approx(b, 0.5)
    approx(a + b, 1.0)


def test_no_vig_unbalanced():
    # -120/+100: implied .54545 + .5 = 1.04545 overround
    a, b = no_vig_two_way(-120, 100)
    approx(a, (120 / 220) / (120 / 220 + 0.5))
    approx(b, 0.5 / (120 / 220 + 0.5))
    approx(a + b, 1.0)


def test_ev_positive():
    # Model says 54%, book pays -110 (1.909): 0.54*1.909 - 1 = +3.09%
    approx(ev_percent(0.54, american_to_decimal(-110)), 0.54 * (1 + 100 / 110) - 1)


def test_ev_negative():
    # Coin flip at -110 is -4.55%: the vig, quantified
    approx(ev_percent(0.5, american_to_decimal(-110)), 0.5 * (1 + 100 / 110) - 1)
    assert ev_percent(0.5, american_to_decimal(-110)) < 0


def test_ev_break_even():
    # Fair prob exactly = implied prob -> EV ~ 0
    approx(ev_percent(american_to_implied(-110), american_to_decimal(-110)), 0.0, tol=1e-9)


def test_kelly_positive_edge_only():
    assert kelly_fraction(0.54, american_to_decimal(-110)) > 0
    assert kelly_fraction(0.50, american_to_decimal(-110)) == 0  # no edge, no bet
    # Kelly never suggests more than the edge warrants on a value bet
    k = kelly_fraction(0.6, american_to_decimal(150))
    assert 0 < k < 1
