"""Preseason data — an honest inventory.

Verified empirically 2026-10-07 against nflverse (the free backbone):
  - schedules list NO preseason games
    (game_type values: REG, DIV, CON, WC, SB — zero PRE rows).
  - play-by-play is charted for REG+POST only.
  - player_stats has season_type REG/POST only.

So: preseason STATS and preseason GAME FILM do not exist in the free
data, and we refuse to invent them. What DOES exist:
  - full offseason rosters (camp bodies included),
  - weekly depth charts (in-season),
  - draft picks, combine numbers.

The dashboard's Players tab shows this inventory verbatim so nobody
mistakes "no data" for "bad player".
"""


def availability() -> dict:
    """What preseason data exists in the free tier, and what doesn't."""
    return {
        "preseason_games": {
            "available": False,
            "detail": "nflverse schedules list no preseason games "
                      "(game_type is REG/DIV/CON/WC/SB only).",
        },
        "preseason_play_by_play": {
            "available": False,
            "detail": "nflverse charts play-by-play for REG+POST only. "
                      "No free source charts preseason snaps.",
        },
        "preseason_player_stats": {
            "available": False,
            "detail": "Weekly player stats cover REG/POST only "
                      "(season_type check, 2026-10-07).",
        },
        "rosters": {
            "available": True,
            "detail": "Full offseason rosters via nflverse (camp bodies "
                      "included) — who made the team is free data.",
        },
        "depth_charts": {
            "available": True,
            "detail": "Weekly in-season depth charts via nflverse.",
        },
        "draft_combine": {
            "available": True,
            "detail": "Draft picks + combine numbers via nflverse "
                      "(rookies with no NFL snaps yet).",
        },
    }


def summary_lines() -> list[str]:
    """Human-readable lines for the dashboard."""
    out = []
    for key, v in availability().items():
        mark = "YES" if v["available"] else "NO "
        out.append(f"{mark}  {key}: {v['detail']}")
    return out
