"""Aggressive response cache for odds APIs.

API credits cost money (or are limited on free tiers), so we NEVER hit the
network twice for the same thing within the TTL. Every adapter goes through
here: `get(source, key, ttl_seconds, fetcher)`.

- `source`: which API, e.g. "the_odds_api" or "lumify"
- `key`: what we're asking for, e.g. "nfl_h2h_us"
- `fetcher`: a zero-arg function that does the real HTTP call. Only runs
  on a cache miss (or when `force=True`).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

CACHE_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "odds_cache.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(CACHE_DB), exist_ok=True)
    conn = sqlite3.connect(CACHE_DB)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS odds_cache (
               source TEXT,
               cache_key TEXT,
               fetched_at REAL,
               payload TEXT,
               PRIMARY KEY (source, cache_key))"""
    )
    return conn


def get(source: str, key: str, ttl_seconds: int, fetcher, force: bool = False):
    """Return cached payload, or call fetcher() and cache the result.

    `fetcher` must return something JSON-serializable. Raises whatever
    fetcher raises on network failure — callers decide how to degrade.
    """
    now = time.time()
    if not force:
        with _conn() as conn:
            row = conn.execute(
                "SELECT fetched_at, payload FROM odds_cache WHERE source=? AND cache_key=?",
                (source, key),
            ).fetchone()
        if row and now - row[0] < ttl_seconds:
            return json.loads(row[1])

    payload = fetcher()
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO odds_cache (source, cache_key, fetched_at, payload)"
            " VALUES (?, ?, ?, ?)",
            (source, key, now, json.dumps(payload)),
        )
    return payload


def age_seconds(source: str, key: str) -> float | None:
    """How old the cached entry is, or None if nothing cached."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT fetched_at FROM odds_cache WHERE source=? AND cache_key=?",
            (source, key),
        ).fetchone()
    return time.time() - row[0] if row else None
