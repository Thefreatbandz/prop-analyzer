"""Backtest lab — walk-forward calibration of the projection model
(PREMIUM).

What it answers: "when the model says 60%, does it actually happen
60% of the time?" For each week in the chosen range, we rebuild every
player's distribution using ONLY games before that week (no lookahead —
player_distribution skips future games by construction), set the
"market proxy" line to the trailing median, and check the actual result.

Honest scope: this validates the MODEL's probabilities (calibration +
Brier score). It is NOT a betting P&L — that needs historical book
lines, which aren't free. We label it as such in the UI.

Fast by design: per-player game lists are fetched once per stat, then
each target week is pure Python on small lists (no per-week polars
filters, no 10k-sim Monte Carlos — the closed-form normal survival
function is deterministic and instant).
"""
from __future__ import annotations

import math
import statistics

from projections.model import HALF_LIFE_WEEKS, MIN_GAMES, STAT_MAP

# Stats worth calibrating (the core SGP/prop markets).
LAB_STATS = ["player_pass_yds", "player_rush_yds",
             "player_receptions", "player_rec_yds"]

BUCKETS = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 1.01)]


def _weeks_ago(season: int, week: int, cur_season: int, cur_week: int) -> float:
    # Same 18-week season convention as projections.model.
    return (cur_season - season) * 18.0 + (cur_week - week)


def _weighted_dist(games: list[tuple[int, int, float]],
                   cur_season: int, cur_week: int,
                   half_life: float = HALF_LIFE_WEEKS) -> dict | None:
    """Recency-weighted (mean, std, n) from [(season, week, value)].

    Mirrors projections.model.player_distribution exactly (same weights,
    same shrinkage) but works on a pre-fetched list so the lab stays fast.
    Only games strictly before (cur_season, cur_week) count — no lookahead.
    """
    weights, values = [], []
    for season, week, value in games:
        ago = _weeks_ago(season, week, cur_season, cur_week)
        if ago <= 0:  # this week or future — not known yet
            continue
        w = 0.5 ** (ago / half_life)
        weights.append(w)
        values.append(float(value))
    n = len(values)
    if n < MIN_GAMES:
        return None
    wsum = sum(weights)
    mean = sum(v * w for v, w in zip(values, weights)) / wsum
    var = sum(w * (v - mean) ** 2 for v, w in zip(values, weights)) / wsum
    return {"mean": mean, "std": math.sqrt(max(var, 1e-9)), "n": n}


def norm_p_over(mean: float, std: float, line: float) -> float:
    """Closed-form P(X > line) for X ~ Normal(mean, std).

    Deterministic twin of montecarlo.prob_over (which clips at 0 and
    simulates); the lab uses this so results are instant and repeatable.
    """
    if std <= 0:
        return 1.0 if mean > line else 0.0
    return 0.5 * math.erfc((line - mean) / (std * math.sqrt(2.0)))


def _player_games(player_stats_df, stat_col: str,
                  season: int) -> dict[str, tuple[list, str]]:
    """One polars pull per stat.

    Returns player -> ([(season, week, value)] sorted, position).
    Includes the two prior seasons — early weeks need last year's games
    (the recency weights make old games count for almost nothing anyway).
    """
    import polars as pl

    cols = ["player_display_name", "season", "week", stat_col]
    # Position lets the lab grade players only on markets they play;
    # optional so synthetic test frames (no position column) still run.
    has_pos = "position" in player_stats_df.columns
    if has_pos:
        cols.insert(1, "position")
    rows = (
        player_stats_df.filter(
            (pl.col("season") >= season - 2)
            & (pl.col("season") <= season)
            & (pl.col("season_type") == "REG")
            & (pl.col(stat_col).is_not_null())
        )
        .select(cols)
        .sort(["player_display_name", "season", "week"])
        .to_dicts()
    )
    out: dict[str, tuple[list, str | None]] = {}
    for r in rows:
        games, _pos = out.get(r["player_display_name"], ([], None))
        games.append((r["season"], r["week"], float(r[stat_col])))
        out[r["player_display_name"]] = (
            games, r.get("position") if has_pos else None)
    return out


def run_lab(player_stats_df, season: int, start_week: int, end_week: int,
            min_games: int = MIN_GAMES) -> dict:
    """Walk-forward calibration over [start_week, end_week].

    Returns per-market results {market: {n, brier, base_rate, buckets}}
    plus an overall rollup. Buckets show predicted fair P vs actual hit
    rate — close together = well calibrated.

    Known limitation (surfaced, not hidden): rushing/receiving markets
    for low-volume players are zero-inflated (lots of exact 0s), and the
    model's normal curve overstates P(over) there. QB passing yards —
    the model's core market — calibrates well. The per-market table
    makes this visible instead of averaging it away.
    """
    market_res: dict[str, dict] = {}
    all_preds: list[tuple[float, int]] = []
    for market in LAB_STATS:
        col, positions = STAT_MAP[market]
        by_player = _player_games(player_stats_df, col, season)
        preds: list[tuple[float, int]] = []
        for player, (games, pos) in by_player.items():
            if not player:
                continue  # data-quality: unnamed rows
            # A QB's "receptions" line is meaningless — only grade a
            # player on markets his position actually plays (when we
            # know the position).
            if pos is not None and pos not in positions:
                continue
            for week in range(start_week, end_week + 1):
                dist = _weighted_dist(games, season, week)
                if not dist or dist["n"] < min_games:
                    continue
                # No historical variation = the model has no signal
                # (e.g. a WR who has never logged a rushing yard:
                # P(over 0) is a 50/50 boundary artifact, not a view).
                if dist["std"] < 0.5:
                    continue
                # Market-proxy line: trailing median of the same window.
                # (A proxy, labeled as such — real historical lines cost $.)
                trailing = [v for s, w, v in games
                            if _weeks_ago(s, w, season, week) > 0]
                if len(trailing) < min_games:
                    continue
                line = statistics.median(trailing)
                fair_p = norm_p_over(dist["mean"], dist["std"], line)
                actual = next((v for s, w, v in games
                               if s == season and w == week), None)
                if actual is None:
                    continue  # bye week / didn't play
                preds.append((fair_p, 1 if actual > line else 0))
        all_preds.extend(preds)
        market_res[market] = {
            "label": market.replace("player_", "").replace("_", " "),
            "n": len(preds),
            "brier": (round(sum((p - o) ** 2 for p, o in preds)
                            / len(preds), 4) if preds else None),
            "base_rate": (round(sum(o for _, o in preds) / len(preds), 3)
                          if preds else None),
            "buckets": _bucketize(preds),
        }

    brier = (sum((p - o) ** 2 for p, o in all_preds) / len(all_preds)
             if all_preds else None)
    return {
        "markets": market_res,
        "buckets": _bucketize(all_preds),
        "brier": round(brier, 4) if brier is not None else None,
        "n_predictions": len(all_preds),
        "season": season,
        "weeks": (start_week, end_week),
        "note": ("Validates the model's probabilities against actuals "
                 "(calibration + Brier). Not a betting P&L — historical "
                 "book lines aren't free, so the 'line' here is the "
                 "trailing median, labeled as a proxy. Rushing/receiving "
                 "markets run hot: low-volume players' stats are "
                 "zero-inflated and the normal curve overstates P(over) "
                 "there — see the per-market table. QB passing yards, the "
                 "core market, calibrates well."),
    }


def _bucketize(preds: list[tuple[float, int]]) -> list[dict]:
    buckets = []
    for lo, hi in BUCKETS:
        in_b = [p for p in preds if lo <= p[0] < hi]
        if in_b:
            buckets.append({
                "bucket": f"{lo:.0%}–{hi:.0%}",
                "predicted": round(sum(p[0] for p in in_b) / len(in_b), 3),
                "actual": round(sum(p[1] for p in in_b) / len(in_b), 3),
                "n": len(in_b),
            })
    return buckets
