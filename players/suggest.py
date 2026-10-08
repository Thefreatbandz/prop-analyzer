"""Suggested players — "who should I look at this week?"

Two honest signals, both labeled in the UI so nobody mistakes them for
picks:

  1. EV signal: players behind this week's top +EV prop flags, ranked by
     their best EV%. (A suggestion to *look*, not a bet slip.)
  2. News signal: players mentioned most in this week's headlines
     ("trending"). Counted with the same simple name-match the News tab
     uses — cheap, honest, no NLP theater.

suggestions() merges the two, de-duplicated by player name: EV first
(the money signal), then trending. Each item carries its reason string
so the UI can show exactly why the player is suggested.
"""
from __future__ import annotations


def suggest_from_ev(prop_picks: list[dict], top_n: int = 5) -> list[dict]:
    """Unique players behind the top +EV prop flags, ranked by best EV%."""
    best: dict[str, dict] = {}
    for p in prop_picks:
        name = p.get("player")
        if not name:
            continue
        cur = best.get(name)
        if cur is None or p.get("ev_pct", 0) > cur["ev_pct"]:
            best[name] = {
                "name": name,
                "team": p.get("team"),
                "ev_pct": p.get("ev_pct", 0),
                "reason": (
                    f"Top +EV prop this week: {p.get('label')} "
                    f"{p.get('side')} {p.get('line')} "
                    f"({p.get('ev_pct', 0):+.1f}%)"
                ),
            }
    ranked = sorted(best.values(), key=lambda s: s["ev_pct"], reverse=True)
    return ranked[:top_n]


def suggest_trending(news: list[dict], rosters_df, top_n: int = 5) -> list[dict]:
    """Players mentioned most in this week's headlines.

    Same matching rule as news.news_for_player: full-name or last-name
    (len > 2) substring hit in headline + description.
    """
    counts: dict[str, int] = {}
    texts = [
        f"{a.get('headline', '')} {a.get('description', '')}".lower() for a in news
    ]
    for r in rosters_df.to_dicts():
        full = (r.get("full_name") or "").lower()
        last = (r.get("last_name") or "").lower()
        if not full:
            continue
        hits = sum(
            1
            for t in texts
            if full in t or (len(last) > 2 and last in t)
        )
        if hits:
            counts[r["full_name"]] = (hits, r.get("team"), r.get("position"))
    ranked = sorted(counts.items(), key=lambda kv: kv[1][0], reverse=True)
    return [
        {
            "name": name,
            "team": team,
            "position": pos,
            "mentions": n,
            "reason": f"In the news: {n} headline{'s' if n != 1 else ''} this week",
        }
        for name, (n, team, pos) in ranked[:top_n]
    ]


def suggestions(prop_picks: list[dict], news: list[dict], rosters_df,
                top_n: int = 8) -> list[dict]:
    """Merged suggestion list: EV signal first, then trending, de-duplicated.

    Each item: {name, team, position, reason, source}. Position comes
    from the roster when the EV picks don't carry it.
    """
    roster_pos = {
        (r.get("full_name") or ""): (r.get("team"), r.get("position"))
        for r in rosters_df.to_dicts()
    }
    out: list[dict] = []
    seen: set[str] = set()
    for s in suggest_from_ev(prop_picks):
        team, pos = roster_pos.get(s["name"], (s.get("team"), None))
        out.append({**s, "team": team, "position": pos, "source": "ev"})
        seen.add(s["name"])
    for s in suggest_trending(news, rosters_df):
        if s["name"] in seen:
            continue
        out.append({**s, "source": "news"})
        seen.add(s["name"])
    return out[:top_n]
