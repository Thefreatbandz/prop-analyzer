"""Monte Carlo engine: turn a (mean, std) projection into a fair probability.

The idea: we don't know exactly what a player will do Sunday — but if his
recent form says "about 270 yards, give or take 45", we can SIMULATE the
game 10,000 times by drawing from that bell curve and just COUNT how often
he goes over the book's line. That fraction IS our fair probability.

  P(over 267.5) = (# sims above 267.5) / 10,000

For counting stats like TDs the normal curve is an approximation (v1
simplicity — noted, not hidden); yardage/receptions fit it well.
"""
from __future__ import annotations

import hashlib

import numpy as np


def stable_seed(player: str, market: str, side: str, line: float) -> int:
    """Deterministic Monte Carlo seed for one player/market/side/line.

    The Scan card's MODEL PROB and the Builder's per-leg fair P must be
    the SAME number for the same inputs — an unseeded sim would jitter
    by ~±0.5% between the two views. Same inputs -> same draws ->
    same probability, everywhere.
    """
    key = f"{player}|{market}|{side}|{line}".encode()
    return int(hashlib.sha256(key).hexdigest(), 16) % (2 ** 31)


def prob_over(mean: float, std: float, line: float, n: int = 10_000,
              seed: int | None = None) -> float:
    """Fair P(stat > line). Values can't go negative, so clip at 0."""
    rng = np.random.default_rng(seed)
    sims = rng.normal(loc=mean, scale=max(std, 1e-9), size=n)
    sims = np.clip(sims, 0, None)
    return float((sims > line).mean())


def prob_under(mean: float, std: float, line: float, n: int = 10_000,
               seed: int | None = None) -> float:
    """Fair P(stat < line). Pushes (exactly on the line) are rare in the
    NFL with .5 lines — books set them to avoid ties. We ignore pushes."""
    return 1.0 - prob_over(mean, std, line, n=n, seed=seed)


def fair_odds_american(fair_prob: float) -> float:
    """Convert a fair probability back to American odds for display.
    e.g. 0.54 -> about -117."""
    if fair_prob <= 0 or fair_prob >= 1:
        raise ValueError("fair_prob must be strictly between 0 and 1")
    if fair_prob >= 0.5:
        return -100.0 * fair_prob / (1.0 - fair_prob)
    return 100.0 * (1.0 - fair_prob) / fair_prob
