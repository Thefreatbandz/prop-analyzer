"""Lumify adapter — player props across books, multi-sport (NFL/NBA/MLB).

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

SPORTS = ("nfl", "nba", "mlb")


def _key() -> str | None:
    return os.environ.get("LUMIFY_API_KEY") or None


def _headers() -> dict:
    return {"Authorization": f"Bearer {_key()}"}


def _check_sport(sport: str) -> str:
    s = (sport or "nfl").lower()
    if s not in SPORTS:
        raise ValueError(f"unsupported sport {sport!r} — pick one of {SPORTS}")
    return s


def load_sample(sport: str = "nfl") -> dict:
    """Sample props board — lets the whole pipeline run with zero keys."""
    sport = _check_sport(sport)
    path = os.path.join(os.path.dirname(__file__), "samples", f"{sport}_player_props.json")
    with open(path) as f:
        return json.load(f)


def list_events(status: str = "scheduled", sport: str = "nfl") -> list[dict]:
    """Events (cheap: 1 credit). Each has an id for props pulls.

    Defaults to status="scheduled" — without it the endpoint returns the most
    recent finals, so an "upcoming games" call would find nothing to scan.
    """
    sport = _check_sport(sport)
    if not _key():
        raise RuntimeError("LUMIFY_API_KEY is not set.")
    params = {"sport": sport}
    if status:
        params["status"] = status
    r = requests.get(f"{BASE}/events", params=params, headers=_headers(), timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("events", data if isinstance(data, list) else [])


def fetch_props(event_id: str, sport: str = "nfl", force: bool = False) -> dict:
    """Player props for one event. Cached HARD — 1 credit per event with lines."""
    sport = _check_sport(sport)
    if not _key():
        raise RuntimeError("LUMIFY_API_KEY is not set — call load_sample() instead.")

    def _fetch():
        r = requests.get(
            f"{BASE}/events/{event_id}/player-props", headers=_headers(), timeout=30
        )
        r.raise_for_status()
        return r.json()

    return cached_get("lumify", f"{sport}_props_{event_id}", TTL_SECONDS, _fetch, force=force)


def get_player_props(event_id: str | None = None, sport: str = "nfl",
                     force: bool = False) -> dict:
    """Props board, live if we have a key, sample data otherwise.

    With a key and no event_id: lists events, then pulls props only for the
    first upcoming event (keeps credit burn tiny on the free tier).
    """
    sport = _check_sport(sport)
    if not _key():
        return load_sample(sport)
    if event_id is None:
        events = list_events(sport=sport)
        # Skip completed games: props only exist for upcoming events.
        # (Events list in chronological order; finals sit at the top
        # early in the week before books post the next slate.)
        upcoming = [e for e in events
                    if (e.get("status") or "").lower() != "final"]
        if not upcoming:
            return {"props": [],
                    "note": f"no upcoming {sport.upper()} games right now"}
        event_id = upcoming[0].get("id")
    return fetch_props(event_id, sport=sport, force=force)


# Live Lumify market keys -> the canonical player_* keys our projection
# model builds distributions for (see projections/model.py STAT_MAP).
# Markets with no mapping (alt/combo lines like pass_rush_yards, anytime-TD
# "touchdowns") keep their raw key and are skipped honestly by the engine —
# never silently mis-mapped.
LIVE_MARKET_MAP = {
    "nfl": {
        "passing_yards": "player_pass_yds",
        "passing_tds": "player_pass_tds",
        "rushing_yards": "player_rush_yds",
        "receiving_yards": "player_rec_yds",
        "receptions": "player_receptions",
        "rushing_tds": "player_rush_tds",
        "receiving_tds": "player_rec_tds",
    },
    "nba": {
        "points": "player_points",
        "rebounds": "player_rebounds",
        "assists": "player_assists",
        "threes": "player_threes",
        "three_pointers": "player_threes",
        "steals": "player_steals",
        "blocks": "player_blocks",
        "points_rebounds_assists": "player_pra",
        "pra": "player_pra",
    },
    "mlb": {
        "hits": "player_hits",
        "home_runs": "player_home_runs",
        "rbis": "player_rbis",
        "runs": "player_runs",
        "total_bases": "player_total_bases",
        "hits_runs_rbis": "player_hits_runs_rbis",
        "stolen_bases": "player_stolen_bases",
        "strikeouts_batter": "player_so_batter",
        "strikeouts_pitcher": "player_so_pitcher",
        "earned_runs": "player_earned_runs",
        "outs_recorded": "player_outs_recorded",
        "hits_allowed": "player_hits_allowed",
    },
}

LIVE_MARKET_LABELS = {
    "nfl": {
        "passing_yards": "Passing Yards",
        "passing_tds": "Passing TDs",
        "passing_attempts": "Pass Attempts",
        "passing_completions": "Completions",
        "rushing_yards": "Rushing Yards",
        "receiving_yards": "Receiving Yards",
        "receptions": "Receptions",
        "rushing_tds": "Rushing TDs",
        "receiving_tds": "Receiving TDs",
        "touchdowns": "Touchdowns",
        "pass_rush_yards": "Pass + Rush Yards",
        "interceptions": "Interceptions",
    },
    "nba": {
        "points": "Points",
        "rebounds": "Rebounds",
        "assists": "Assists",
        "threes": "Three-Pointers",
        "three_pointers": "Three-Pointers",
        "steals": "Steals",
        "blocks": "Blocks",
        "points_rebounds_assists": "Pts+Reb+Ast",
        "pra": "Pts+Reb+Ast",
    },
    "mlb": {
        "hits": "Hits",
        "home_runs": "Home Runs",
        "rbis": "RBIs",
        "runs": "Runs",
        "total_bases": "Total Bases",
        "hits_runs_rbis": "Hits+Runs+RBIs",
        "stolen_bases": "Stolen Bases",
        "strikeouts_batter": "Strikeouts (Batter)",
        "strikeouts_pitcher": "Strikeouts (Pitcher)",
        "earned_runs": "Earned Runs",
        "outs_recorded": "Outs Recorded",
        "hits_allowed": "Hits Allowed",
    },
}

def _market_map(sport: str) -> dict:
    return LIVE_MARKET_MAP.get(_check_sport(sport), {})


def _market_labels(sport: str) -> dict:
    return LIVE_MARKET_LABELS.get(_check_sport(sport), {})


def _norm_books_dict(raw_books: dict, line) -> list[dict]:
    """Live Lumify shape: books is {"draftkings": {"over": -110, ...}}."""
    books = []
    for name, prices in raw_books.items():
        if not isinstance(prices, dict):
            continue
        over = prices.get("over")
        under = prices.get("under")
        if over is None and under is None:
            continue
        books.append({"book": name, "line": line, "over": over, "under": under})
    return books


def _norm_books_list(raw_books: list) -> list[dict]:
    """Sample/legacy shape: books is [{book, line, over, under}, ...]."""
    books = []
    for b in raw_books:
        if not isinstance(b, dict):
            continue
        over = b.get("over") if b.get("over") is not None else b.get("over_price")
        under = b.get("under") if b.get("under") is not None else b.get("under_price")
        books.append(
            {
                "book": b.get("book") or b.get("bookmaker") or b.get("key"),
                "line": b.get("line"),
                "over": over,
                "under": under,
            }
        )
    return books


def normalize(payload: dict, sport: str = "nfl") -> list[dict]:
    """Flatten to one row per player-market.

    Returns: [{player, team, market, label,
               books: [{book, line, over, under}]}]
    Accepts both our sample shape and the live Lumify API shape — the live
    payload nests books as a dict keyed by book name with the line at the
    prop level, and uses short market keys (passing_yards, ...) which are
    mapped to the canonical player_* keys the model understands.
    """
    sport = _check_sport(sport)
    market_map = _market_map(sport)
    market_labels = _market_labels(sport)
    props = payload.get("props") or payload.get("player_props") or []
    out = []
    for p in props:
        raw_books = p.get("books", [])
        if isinstance(raw_books, dict):
            books = _norm_books_dict(raw_books, p.get("line"))
        else:
            books = _norm_books_list(raw_books or p.get("bookmakers", []))
        raw_market = p.get("market") or p.get("market_key")
        market = market_map.get(raw_market, raw_market)
        label = p.get("label") or market_labels.get(raw_market) or raw_market
        out.append(
            {
                "player": p.get("player") or p.get("player_name"),
                "team": p.get("team"),
                "market": market,
                "label": label,
                "books": [b for b in books if b["line"] is not None],
            }
        )
    return [p for p in out if p["books"]]
