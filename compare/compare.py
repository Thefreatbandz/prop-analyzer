"""Side-by-side player comparison (PREMIUM-gated).

Compares two players across: bio, season averages, last-5 game logs,
projection distributions, and each player's live prop EVs.

The gate: config.PREMIUM_ENABLED. When False, compare_players() returns
{"locked": True, ...} and the dashboard renders the upsell instead of
the table. The comparison logic itself is fully implemented and
unit-tested in both states (see tests/test_v2.py).
"""
from __future__ import annotations

import config
from players import profiles
from tendencies import player as pstyle


def is_unlocked() -> bool:
    return bool(config.PREMIUM_ENABLED)


def _evs_for(prop_picks: list[dict], player_name: str) -> list[dict]:
    return [
        {"label": p["label"], "side": p["side"], "line": p["line"],
         "price": p["price"], "book": p["book"], "ev_pct": p["ev_pct"],
         "fair_prob": p["fair_prob"]}
        for p in prop_picks
        if (p.get("player") or "").lower() == player_name.lower()
    ]


def compare_players(name_a: str, name_b: str, ctx: dict) -> dict:
    """Compare two players. ctx keys: rosters_df, player_stats_df,
    distributions, prop_picks, season, week.

    Returns {"locked": True, "teaser": [...]} when the premium flag is
    off, else the full side-by-side payload.
    """
    if not is_unlocked():
        return {"locked": True, "teaser": config.PREMIUM_TEASER}

    rosters_df = ctx["rosters_df"]
    ps_df = ctx["player_stats_df"]
    season = ctx["season"]

    def one(name: str) -> dict:
        bio = profiles.find_player(rosters_df, name) or {"name": name}
        return {
            "bio": bio,
            "season_averages": profiles.season_averages(ps_df, name, season),
            "last_5": profiles.game_log(ps_df, name, last_n=5),
            "style": pstyle.style_from_weekly(ps_df, name, season),
            "distributions": (ctx.get("distributions") or {}).get(name, {}),
            "prop_evs": _evs_for(ctx.get("prop_picks") or [], name),
        }

    a, b = one(name_a), one(name_b)
    return {
        "locked": False,
        "players": [a, b],
        "stat_rows": _stat_rows(a["season_averages"], b["season_averages"]),
    }


def _stat_rows(avg_a: dict, avg_b: dict) -> list[dict]:
    """Align the two average dicts into comparable rows."""
    keys = [k for k in avg_a if k != "games"]
    rows = []
    for k in keys:
        rows.append(
            {"stat": k.replace("_", " "), "a": avg_a.get(k), "b": avg_b.get(k)}
        )
    return rows
