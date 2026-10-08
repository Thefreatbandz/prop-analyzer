"""Lumify adapter — NFL player props across books.

Docs: https://lumify.ai/docs  (see also their nfl-api.md on GitHub)
Free tier: 1,000 credits that never expire — enough to bootstrap v1.
Credit notes from their docs:
  - GET /v1/events/{id}/player-props costs 1 credit WHEN lines exist;
    `available: false` responses are FREE. We exploit that: check the events
    list first, only pull props for games that actually have them.
Set LUMIFY_API_KEY in .env. Without a key, use load_sample().
"""
from __future__ import annotations

import json
import os

import requests

from .cache import get as cached_get

BASE = "https://lumify.ai/v1"
# Props lines move slower than game lines and credits are precious:
# 6h TTL, refreshed on demand on game days.
TTL_SECONDS = 6 * 60 * 60


def _key() -> str | None:
    return os.environ.get("LUMIFY_API_KEY") or None


def _headers() -> dict:
    return {"Authorization": f"Bearer {_key()}"}


def load_sample() -> dict:
    """Sample props board — lets the whole pipeline run with zero keys."""
    path = os.path.join(os.path.dirname(__file__), "samples", "nfl_player_props.json")
    with open(path) as f:
        return json.load(f)


def list_events() -> list[dict]:
    """Upcoming NFL events (cheap: 1 credit). Each has an id for props pulls."""
    if not _key():
        raise RuntimeError("LUMIFY_API_KEY is not set.")
    r = requests.get(f"{BASE}/events", params={"sport": "nfl"}, headers=_headers(), timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("events", data if isinstance(data, list) else [])


def fetch_props(event_id: str, force: bool = False) -> dict:
    """Player props for one event. Cached HARD — 1 credit per event with lines."""
    if not _key():
        raise RuntimeError("LUMIFY_API_KEY is not set — call load_sample() instead.")

    def _fetch():
        r = requests.get(
            f"{BASE}/events/{event_id}/player-props", headers=_headers(), timeout=30
        )
        r.raise_for_status()
        return r.json()

    return cached_get("lumify", f"nfl_props_{event_id}", TTL_SECONDS, _fetch, force=force)


def get_player_props(event_id: str | None = None, force: bool = False) -> dict:
    """Props board, live if we have a key, sample data otherwise.

    With a key and no event_id: lists events, then pulls props only for the
    first upcoming event (keeps credit burn tiny on the free tier).
    """
    if not _key():
        return load_sample()
    if event_id is None:
        events = list_events()
        # Skip completed games: props only exist for upcoming events.
        # (Events list in chronological order; finals sit at the top
        # early in the week before books post the next slate.)
        upcoming = [e for e in events
                    if (e.get("status") or "").lower() != "final"]
        if not upcoming:
            return {"props": [],
                    "note": "no upcoming NFL games right now"}
        event_id = upcoming[0].get("id")
    return fetch_props(event_id, force=force)


def normalize(payload: dict) -> list[dict]:
    """Flatten to one row per player-market.

    Returns: [{player, team, market, label,
               books: [{book, line, over, under}]}]
    Accepts both our sample shape and the Lumify API shape (best effort —
    field names get mapped defensively since providers change schemas).
    """
    props = payload.get("props") or payload.get("player_props") or []
    out = []
    for p in props:
        books = []
        for b in p.get("books", []) or p.get("bookmakers", []):
            books.append(
                {
                    "book": b.get("book") or b.get("bookmaker") or b.get("key"),
                    "line": b.get("line"),
                    "over": b.get("over") or b.get("over_price"),
                    "under": b.get("under") or b.get("under_price"),
                }
            )
        out.append(
            {
                "player": p.get("player") or p.get("player_name"),
                "team": p.get("team"),
                "market": p.get("market") or p.get("market_key"),
                "label": p.get("label") or p.get("market"),
                "books": [b for b in books if b["line"] is not None],
            }
        )
    return [p for p in out if p["books"]]
