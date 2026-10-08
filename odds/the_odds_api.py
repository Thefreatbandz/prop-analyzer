"""The Odds API adapter — NFL moneylines (h2h) across US books.

Docs: https://the-odds-api.com/liveapi/guides/v4/
Free tier friendly: moneyline (h2h) is a cheap single-market pull.
Set ODDS_API_KEY in .env. Without a key, use load_sample().
"""
from __future__ import annotations

import json
import os

import requests

from .cache import get as cached_get

SPORT = "americanfootball_nfl"
BASE = "https://api.the-odds-api.com/v4"
# 15 minutes: lines move, but credits cost money. Never re-fetch faster.
TTL_SECONDS = 15 * 60


def _key() -> str | None:
    return os.environ.get("ODDS_API_KEY") or None


def load_sample() -> dict:
    """Sample moneyline board — lets the whole pipeline run with zero keys."""
    path = os.path.join(os.path.dirname(__file__), "samples", "nfl_moneylines.json")
    with open(path) as f:
        return json.load(f)


def fetch_live(regions: str = "us", bookmakers: str | None = None, force: bool = False) -> dict:
    """Pull the live NFL moneyline board. Cached for TTL_SECONDS.

    regions="us" keeps it free-tier friendly. Add ",eu" to include Pinnacle
    (the sharp book we cross-check moneylines against) — costs more credits.
    """
    api_key = _key()
    if not api_key:
        raise RuntimeError("ODDS_API_KEY is not set — call load_sample() instead.")

    def _fetch():
        params = {
            "apiKey": api_key,
            "regions": regions,
            "markets": "h2h",  # h2h = moneyline (head-to-head)
            "oddsFormat": "american",
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
        r = requests.get(f"{BASE}/sports/{SPORT}/odds/", params=params, timeout=30)
        # SECURITY: requests' HTTPError message embeds the request URL,
        # which carries our apiKey as a query param. Never let that
        # exception (or its URL) reach logs, the UI, or a traceback the
        # user can copy — raise a sanitized error instead.
        try:
            r.raise_for_status()
        except requests.HTTPError:
            raise RuntimeError(
                f"The Odds API request failed (HTTP {r.status_code}). "
                "Check the key and the service status."
            )
        remaining = r.headers.get("x-requests-remaining")
        events = r.json()
        return {"events": events, "requests_remaining": remaining}

    return cached_get("the_odds_api", f"nfl_h2h_{regions}", TTL_SECONDS, _fetch, force=force)


def get_moneylines(force: bool = False) -> dict:
    """Moneyline board, live if we have a key, sample data otherwise."""
    if _key():
        return fetch_live(force=force)
    return load_sample()


def get_moneylines_strict() -> tuple[list[dict], str | None]:
    """Moneyline board WITHOUT the sample fallback.

    Returns (games, note): games is the normalized board (possibly empty),
    note is None when live, otherwise a human-readable explanation of why
    moneylines are unavailable. Never raises on network failure — a dead
    API is a UI state, not a crash.

    Tbandz's call (2026-10-07): props-only is fine for now. The adapter
    stays intact so moneylines light back up the moment a key arrives.
    """
    if not _key():
        # User-safe copy: no key names for the public. Dev detail lives
        # in the dev-mode sidebar (key_status), not in this note.
        return [], ("Moneylines aren't available right now — "
                    "showing player props only.")
    try:
        board = fetch_live()
    except Exception:  # API down, bad key, timeout — all the same UI state
        return [], ("Moneyline data didn't come through — "
                    "showing player props only.")
    return normalize(board), None


def normalize(events_payload: dict) -> list[dict]:
    """Flatten the API shape into one row per game.

    Returns: [{event_id, home, away, commence_time,
               books: {book_key: {"home": price, "away": price}}}]
    """
    out = []
    for ev in events_payload.get("events", []):
        books: dict[str, dict] = {}
        for bm in ev.get("bookmakers", []):
            for m in bm.get("markets", []):
                if m.get("key") != "h2h":
                    continue
                prices = {}
                for o in m.get("outcomes", []):
                    if o["name"] == ev["home_team"]:
                        prices["home"] = o["price"]
                    elif o["name"] == ev["away_team"]:
                        prices["away"] = o["price"]
                if len(prices) == 2:
                    books[bm["key"]] = prices
        out.append(
            {
                "event_id": ev.get("id"),
                "home": ev["home_team"],
                "away": ev["away_team"],
                "commence_time": ev.get("commence_time"),
                "books": books,
            }
        )
    return out
