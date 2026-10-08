"""ESPN public API — NFL news headlines, no key required.

Endpoint (verified working 2026-10-07):
    https://site.api.espn.com/apis/site/v2/sports/football/nfl/news

What we deliberately do NOT do: chase ESPN's per-player injury $refs
(their core API returns reference links that need one request per
injury — expensive and fragile). Structured injury data comes from
nflverse's weekly reports instead (see get_injury_report below), which
is also what the projection model already reads. One source of truth.
"""
from __future__ import annotations

import json
import os
import time

NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "news")
TTL_SECONDS = 30 * 60  # headlines refresh fast; don't hammer the endpoint


def _cache_path() -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, "nfl_headlines.json")


def _parse_articles(payload: dict) -> list[dict]:
    """ESPN news payload -> [{headline, description, link, published}]."""
    out = []
    for a in payload.get("articles", []):
        links = a.get("links", {}).get("web", {})
        out.append(
            {
                "headline": a.get("headline"),
                "description": a.get("description"),
                "link": links.get("href"),
                "published": a.get("published"),
            }
        )
    return out


def get_nfl_news(limit: int = 20, force: bool = False) -> list[dict]:
    """Latest NFL headlines: [{headline, description, link, published}]."""
    import requests

    path = _cache_path()
    if not force and os.path.exists(path):
        if time.time() - os.path.getmtime(path) < TTL_SECONDS:
            with open(path) as f:
                return json.load(f)[:limit]

    r = requests.get(NEWS_URL, params={"limit": limit}, timeout=20)
    r.raise_for_status()
    out = _parse_articles(r.json())
    with open(path, "w") as f:
        json.dump(out, f)
    return out[:limit]


def get_injury_report(injuries_df, season: int, week: int) -> list[dict]:
    """Current injury report from nflverse (the structured free source).

    Returns [{player, team, position, status, details}] for the latest
    report week <= the given week. Sorted: Out first, then Doubtful,
    then Questionable.
    """
    import polars as pl

    rep = injuries_df.filter(
        (pl.col("season") == season) & (pl.col("week") <= week)
    )
    if rep.height == 0:
        return []
    latest_week = rep["week"].max()
    rep = rep.filter(pl.col("week") == latest_week)
    order = {"Out": 0, "Doubtful": 1, "Questionable": 2}
    rows = []
    for r in rep.to_dicts():
        status = r.get("report_status") or ""
        rows.append(
            {
                "player": r.get("full_name"),
                "team": r.get("team"),
                "position": r.get("position"),
                "status": status,
                "details": r.get("report_details") or r.get("injury") or "",
                "week": latest_week,
            }
        )
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["player"] or ""))
    return rows


def news_for_player(news: list[dict], player_name: str) -> list[dict]:
    """Headlines mentioning a player (simple name match on headline +
    description — cheap, honest, no NLP theater)."""
    name = player_name.lower()
    parts = name.split()
    last = parts[-1] if parts else ""
    hits = []
    for a in news:
        text = f"{a.get('headline', '')} {a.get('description', '')}".lower()
        if name in text or (len(last) > 2 and last in text):
            hits.append(a)
    return hits


def enrich_injury_flags(picks: list[dict], injuries_df, season: int, week: int) -> list[dict]:
    """Cross-check paper picks against the LATEST injury report.

    Why this exists: projections are built once a week, but injury news
    moves daily. If a flagged player shows up as Out/Doubtful/Questionable
    in the newest report and the pick doesn't already carry an injury
    flag, we append one — the model and the news can never silently
    disagree.
    """
    import polars as pl

    report = {(r["player"] or "").lower(): r for r in get_injury_report(injuries_df, season, week)}
    for p in picks:
        if p.get("injury_flag"):
            continue  # the model already knows
        player = (p.get("player") or "").lower()
        hit = report.get(player)
        if not hit:
            # last-name fallback, team-aware when we know the team
            last = player.split()[-1] if player else ""
            cands = [r for k, r in report.items() if k.endswith(last)]
            if p.get("team"):
                cands = [r for r in cands if (r.get("team") or "") == p["team"]]
            hit = cands[0] if cands else None
        if hit and hit["status"] in ("Out", "Doubtful", "Questionable"):
            p["injury_flag"] = (
                f"Injury report (wk {hit['week']}): {hit['status']} — "
                f"projection was built before this landed"
            )
    return picks
