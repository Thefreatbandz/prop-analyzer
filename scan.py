"""Run the full EV scan: lines -> projections -> ranked picks (-> paper log).

Usage:
    python scan.py                 # sample data, prints ranked picks
    python scan.py --model live    # live nflverse projections (slower, needs download)
    python scan.py --log           # also write +EV picks to the paper tracker
    python scan.py --min-ev 3      # only flag edges >= 3%

Needs ODDS_API_KEY / LUMIFY_API_KEY in .env for live odds; without keys it
runs on the bundled sample boards and tells you so.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from engine import picks as engine
from odds import lumify, the_odds_api


def key_status() -> dict:
    return {
        "ODDS_API_KEY": bool(os.environ.get("ODDS_API_KEY")),
        "LUMIFY_API_KEY": bool(os.environ.get("LUMIFY_API_KEY")),
    }


def load_distributions(mode: str) -> dict:
    if mode == "live":
        from projections import build

        season, week = build.current_nfl_week()
        print(f"Live model: {season} week {week}, nflverse 2015–present ...")
        return build.build_distributions(build.sample_players(), season, week)
    path = os.path.join("projections", "samples", "player_distributions.json")
    with open(path) as f:
        return json.load(f)["projections"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["sample", "live"], default="sample")
    ap.add_argument("--log", action="store_true", help="write picks to paper tracker")
    ap.add_argument("--min-ev", type=float, default=2.0)
    args = ap.parse_args()

    keys = key_status()
    print("Keys:", {k: ("set" if v else "MISSING — sample mode") for k, v in keys.items()})

    # --- Moneylines (graceful: props-only is fine) ---
    ml_games, ml_note = the_odds_api.get_moneylines_strict()
    if ml_note:
        print(f"({ml_note})")
    ml_picks = engine.rank_moneylines(ml_games, min_ev=args.min_ev / 100)

    # --- Player props (the live source right now) ---
    props_note = None
    try:
        props_board = lumify.get_player_props()
    except Exception as e:  # dead API / bad key -> sample, loudly
        props_board = lumify.load_sample()
        props_note = (f"Live props pull failed ({type(e).__name__}) — "
                      "showing sample props.")
    props = lumify.normalize(props_board)
    if props_note:
        print(f"({props_note})")
    dists = load_distributions(args.model)
    prop_picks = engine.rank_props(props, dists, min_ev=args.min_ev / 100)

    print(f"\n== MONEYLINE EDGES ({len(ml_picks)}) ==")
    for p in ml_picks:
        print(f"  {p['ev_pct']:+.2f}%  {p['team']} {p['price']:+} @ {p['book']}"
              f"  (fair {p['fair_american']:+.0f})  [{p['game']}]")

    print(f"\n== PROP EDGES ({len(prop_picks)}) ==")
    # News cross-check: if the LATEST injury report flags a player the
    # weekly-built model didn't know about, say so loudly. Never silent.
    try:
        from projections import nflverse as nv
        from projections import build as pbuild
        from news import espn as news_mod

        season, week = pbuild.current_nfl_week()
        inj = nv.injuries()
        prop_picks = news_mod.enrich_injury_flags(prop_picks, inj, season, week)
    except Exception as e:  # offline / no data yet — scan still works
        print(f"(injury cross-check skipped: {e})")
    for p in prop_picks:
        flag = f"  !! {p['injury_flag']}" if p.get("injury_flag") else ""
        print(f"  {p['ev_pct']:+.2f}%  {p['player']} {p['side']} {p['line']} "
              f"{p['label']} {p['price']:+} @ {p['book']}"
              f"  (fair {p['fair_american']:+.0f}, P={p['fair_prob']:.1%}){flag}")

    if args.log:
        from tracker import db

        n = 0
        for p in ml_picks + prop_picks:
            if db.log_pick(p):
                n += 1
        print(f"\nLogged {n} paper picks to the tracker.")

    if not ml_picks and not prop_picks:
        print("\nNo +EV flags at the current threshold. The market is sharp today.")


if __name__ == "__main__":
    main()
