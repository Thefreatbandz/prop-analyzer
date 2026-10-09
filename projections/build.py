"""Build live per-player distributions from nflverse (2015–present).

Usage:
    python -m projections.build                     # current week, all sample players
    python -m projections.build --week 2026 5       # explicit season/week

Downloads are cached as parquet in data/nflverse/ (first run takes a few
minutes for 12 seasons; after that it's incremental-ish via 24h cache).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from projections import model, nflverse


def current_nfl_week() -> tuple[int, int]:
    """(season, week) containing today, from nflverse schedules."""
    import polars as pl

    sched = nflverse.schedules()
    today = date.today().isoformat()
    upcoming = (
        sched.filter((pl.col("game_type") == "REG") & (pl.col("gameday") >= today))
        .sort(["season", "week"])
    )
    if upcoming.height:
        r = upcoming.to_dicts()[0]
        return int(r["season"]), int(r["week"])
    return 2026, 18


def sample_players() -> list[tuple[str, str, str]]:
    """(player, team, market) tuples from the bundled sample props board."""
    alt = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "odds", "samples", "nfl_player_props.json")
    with open(alt) as f:
        board = json.load(f)
    return [(p["player"], p["team"], p["market"]) for p in board["props"]]


def build_distributions(players: list[tuple[str, str, str]],
                        season: int, week: int) -> dict:
    """{player: {market: dist-dict}} with injury adjustment applied."""
    stats_df = nflverse.player_stats()
    inj_df = nflverse.injuries()
    out: dict = {}
    for name, team, market in players:
        col, _positions = model.STAT_MAP.get(market, (None, None))
        if not col:
            continue
        dist = model.player_distribution(stats_df, name, col, season, week)
        if not dist:
            continue
        status = model.injury_status(inj_df, name, team, season, week)
        dist = model.apply_injury_adjustment(dist, status)
        out.setdefault(name, {})[market] = dist
    return out


def build_nba_distributions(players: list[tuple[str, str, str]]) -> dict:
    """{player: {market: dist-dict}} for NBA props.

    players: (name, team, market) with market in model.NBA_STAT_MAP keys.
    Uses nba_api game logs (last 3 seasons, recency-weighted). Players with
    no games (offseason, unknown names) are skipped — never faked.
    """
    from projections import nba_data

    out: dict = {}
    for name, team, market in players:
        col = model.NBA_STAT_MAP.get(market)
        if not col:
            continue
        try:
            log = nba_data.player_game_log(name)
        except Exception:
            continue
        if log.height == 0:
            continue
        rows = log.to_dicts()  # newest first
        if col == "PRA":
            values = [r["PTS"] + r["REB"] + r["AST"] for r in rows]
        else:
            values = [r[col] for r in rows]
        # game_log_distribution wants oldest -> newest.
        dist = model.game_log_distribution(list(reversed(values)),
                                           half_life_games=12.0)
        if not dist:
            continue
        try:
            dist["team"] = log["team_abbr"][0]
        except Exception:
            pass
        out.setdefault(name, {})[market] = dist
    return out


def build_mlb_distributions(players: list[tuple[str, str, str]]) -> dict:
    """{player: {market: dist-dict}} for MLB props.

    players: (name, team, market) with market in the MLB_*_STAT_MAP keys.
    Batter markets use statcast-derived game logs; pitcher markets use the
    pitching log. Markets with no honest data source (runs, earned_runs)
    are absent from the maps and skipped here.
    """
    from projections import mlb_data

    out: dict = {}
    for name, team, market in players:
        col = model.MLB_BATTER_STAT_MAP.get(market)
        log_fn = mlb_data.batter_game_log
        if col is None:
            col = model.MLB_PITCHER_STAT_MAP.get(market)
            log_fn = mlb_data.pitcher_game_log
        if col is None:
            continue
        try:
            log = log_fn(name)
        except Exception:
            continue
        if log.height == 0:
            continue
        rows = log.to_dicts()  # newest first
        values = [r[col] for r in rows]
        dist = model.game_log_distribution(list(reversed(values)),
                                           half_life_games=20.0)
        if not dist:
            continue
        out.setdefault(name, {})[market] = dist
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", nargs=2, type=int, metavar=("SEASON", "WEEK"))
    args = ap.parse_args()
    season, week = args.week or current_nfl_week()
    print(f"Building distributions for {season} week {week} (nflverse 2015–present)...")
    dists = build_distributions(sample_players(), season, week)
    for player, markets in dists.items():
        for mkt, d in markets.items():
            flag = f"  [{d['injury_flag']}]" if d.get("injury_flag") else ""
            print(f"  {player:20s} {mkt:18s} mean={d['mean']:7.1f} "
                  f"std={d['std']:5.1f} n={d['n']:3d}{flag}")
    out = os.path.join(os.path.dirname(__file__), "live_distributions.json")
    with open(out, "w") as f:
        json.dump(dists, f, indent=1)
    print(f"Saved -> {out} (gitignored scratch; dashboard can load it)")


if __name__ == "__main__":
    main()
