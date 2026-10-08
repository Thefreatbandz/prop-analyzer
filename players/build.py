"""Build / refresh the league database.

Usage:
    python -m players.build           # refresh everything (24h caches respected)
    python -m players.build --force   # re-download even fresh caches

Pulls: teams, rosters (all 32 teams), weekly player stats 2015-present,
schedules, injuries, depth charts. Writes data/players/league.json —
the registry the dashboard's Players tab reads.

This is the "full league coverage" piece: the DB holds every rostered
player, not just the ones with props listed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from players import profiles
from projections import nflverse

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "players")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    print("Refreshing league database (nflverse, free, 2015-present) ...")
    t0 = time.time()
    teams_df = nflverse.teams(force=args.force)
    rosters_df = nflverse.rosters(force=args.force)  # latest season in window
    nflverse.player_stats(force=args.force)          # weekly box scores
    nflverse.schedules(force=args.force)
    nflverse.injuries(force=args.force)
    nflverse.depth_charts(force=args.force)

    teams = profiles.get_teams(teams_df, rosters_df)
    roster = profiles.get_roster(rosters_df)
    per_team: dict[str, int] = {}
    for p in roster:
        per_team[p["team"]] = per_team.get(p["team"], 0) + 1
    for t in teams:
        t["rostered_players"] = per_team.get(t["abbr"], 0)

    os.makedirs(OUT_DIR, exist_ok=True)
    registry = {
        "built_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "season": nflverse.SEASONS[-1],
        "n_teams": len(teams),
        "n_players": len(roster),
        "teams": teams,
    }
    with open(os.path.join(OUT_DIR, "league.json"), "w") as f:
        json.dump(registry, f, indent=2)

    print(f"  {len(teams)} teams, {len(roster)} rostered players "
          f"({time.time() - t0:.0f}s)")
    print(f"  registry -> data/players/league.json")
    missing = [t["abbr"] for t in teams if t["rostered_players"] == 0]
    if missing:
        print(f"  WARNING: teams with no roster rows: {missing}")


if __name__ == "__main__":
    main()
