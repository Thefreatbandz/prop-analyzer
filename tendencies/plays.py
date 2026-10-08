"""Most-used plays — the HONEST version.

What Tbandz asked for ("most used plays") meets what the free data has:
nflverse does not chart play CONCEPTS (Mesh, Duo, Power-O, Smash...),
so we do not pretend it does. What we CAN rank from charted
play-by-play is most-used play TYPES:

  - Runs by direction: left / middle / right (run_location)
  - Passes by depth: behind line / short (0-9) / intermediate (10-19) /
    deep (20+) from air_yards
  - QB scrambles, sacks taken

The dashboard labels this exactly that way. If a paid charting feed
ever arrives, this module is where concept tags would plug in.
"""
from __future__ import annotations


def _categorize(play: dict) -> str:
    pt = play.get("play_type")
    if pt == "run":
        loc = (play.get("run_location") or "MIDDLE").upper()
        return {"LEFT": "Run — left", "MIDDLE": "Run — middle",
                "RIGHT": "Run — right"}.get(loc, "Run — middle")
    if pt == "pass":
        if play.get("qb_scramble"):
            return "QB scramble"
        if play.get("sack"):
            return "Sack taken"
        ay = play.get("air_yards")
        if ay is None:
            return "Pass — unknown depth"
        if ay < 0:
            return "Pass — behind line (screen)"
        if ay <= 9:
            return "Pass — short (0-9 yds)"
        if ay <= 19:
            return "Pass — intermediate (10-19 yds)"
        return "Pass — deep (20+ yds)"
    return "Other"


def most_used_play_types(pbp_df, team: str | None = None,
                         seasons: list[int] | None = None,
                         top_n: int = 10) -> list[dict]:
    """Rank play types by usage share. team=None = whole league."""
    import polars as pl

    df = pbp_df.filter(pl.col("play_type").is_in(("run", "pass")))
    if team:
        df = df.filter(pl.col("posteam") == team)
    if seasons:
        df = df.filter(pl.col("season").is_in(seasons))
    n = df.height
    if n == 0:
        return []
    counts: dict[str, int] = {}
    for p in df.to_dicts():
        cat = _categorize(p)
        counts[cat] = counts.get(cat, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [
        {"play_type": cat, "count": c, "share": round(c / n, 3)}
        for cat, c in ranked
    ]


HONEST_LABEL = (
    "Play-TYPE tendencies from charted play-by-play "
    "(run direction, pass depth). Concept-level tags like Mesh, Duo or "
    "Power-O are not charted in the free data — nobody sells them to us "
    "for $0, so we show what the data actually supports."
)
