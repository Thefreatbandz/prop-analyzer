"""Player search — type a name, get matching players across all 32 teams.

Learn-mode tour:
  - search_players() takes the nflverse rosters DataFrame (3,027 rows —
    a polars substring filter over this is instant, no index needed)
    and a free-text query.
  - Matching is case-insensitive and accent-blind-ish (we just lower()).
    "allen" matches Josh Allen; "mahomes" matches Patrick Mahomes.
  - Ranking: exact full-name match first, then starts-with on the full
    name, then starts-with on the last name, then plain contains.
    That puts "Allen Lazard" above "Josh Allen" for "allen"
    (starts-with beats contains) — standard substring ranking.
  - Each hit: {name, team, position, jersey} — enough for the UI to
    render a result row and open the full profile.

No fuzzy/typo tolerance on purpose: honest substring search, and the UI
shows "no matches — check spelling" instead of guessing.
"""
from __future__ import annotations


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def search_players(rosters_df, query: str, limit: int = 10) -> list[dict]:
    """Search all rostered players by name. Returns ranked hits."""
    import polars as pl

    q = _norm(query)
    if not q:
        return []
    df = rosters_df.filter(
        pl.col("full_name").is_not_null()
        & (
            pl.col("full_name").str.to_lowercase().str.contains(q, literal=True)
            | pl.col("first_name").str.to_lowercase().str.contains(q, literal=True)
            | pl.col("last_name").str.to_lowercase().str.contains(q, literal=True)
        )
    )
    hits = []
    for r in df.to_dicts():
        name = _norm(r.get("full_name"))
        first, last = _norm(r.get("first_name")), _norm(r.get("last_name"))
        # Rank: exact > starts-with full > starts-with last > contains.
        if name == q:
            rank = 0
        elif name.startswith(q):
            rank = 1
        elif last.startswith(q):
            rank = 2
        elif first.startswith(q):
            rank = 3
        else:
            rank = 4
        hits.append(
            (
                rank,
                {
                    "name": r.get("full_name"),
                    "team": r.get("team"),
                    "position": r.get("position"),
                    "jersey": r.get("jersey_number"),
                },
            )
        )
    hits.sort(key=lambda h: (h[0], h[1]["name"] or ""))
    return [h[1] for h in hits[:limit]]
