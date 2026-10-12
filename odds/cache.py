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
    conn.execute(
        """CREATE TABLE IF NOT EXISTS usage_log (
               ts REAL,
               source TEXT,
               cache_key TEXT,
               credits INTEGER)"""
    )
    return conn


def get(source: str, key: str, ttl_seconds: int, fetcher, force: bool = False,
        cost_fn=None):
    """Return cached payload, or call fetcher() and cache the result.

    `fetcher` must return something JSON-serializable. Raises whatever
    fetcher raises on network failure — callers decide how to degrade.

    `cost_fn`: optional payload -> int credits spent. Called only when the
    fetcher actually runs (cache miss). Defaults to 1 credit per call.
    Every real network call is logged to usage_log for budget tracking.
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
    credits = cost_fn(payload) if cost_fn else 1
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO odds_cache (source, cache_key, fetched_at, payload)"
            " VALUES (?, ?, ?, ?)",
            (source, key, now, json.dumps(payload)),
        )
        # Bound growth: a full NFL season is ~270 events; prune anything
        # older than 30 days so the cache never grows without limit.
        conn.execute(
            "DELETE FROM odds_cache WHERE fetched_at < ?",
            (now - 30 * 24 * 3600,),
        )
        conn.execute(
            "INSERT INTO usage_log (ts, source, cache_key, credits)"
            " VALUES (?, ?, ?, ?)",
            (now, source, key, credits),
        )
    return payload


def usage_total(days: int = 7, source: str | None = None) -> int:
    """Total credits spent in the last `days` days (all sources unless given)."""
    cutoff = time.time() - days * 24 * 3600
    q = "SELECT COALESCE(SUM(credits), 0) FROM usage_log WHERE ts >= ?"
    args: list = [cutoff]
    if source:
        q += " AND source = ?"
        args.append(source)
    with _conn() as conn:
        return int(conn.execute(q, args).fetchone()[0])


def usage_by_day(days: int = 30) -> list:
    """Per-day credit totals, newest last: [(date_str, credits), ...]."""
    cutoff = time.time() - days * 24 * 3600
    with _conn() as conn:
        rows = conn.execute(
            "SELECT date(ts, 'unixepoch'), SUM(credits) FROM usage_log"
            " WHERE ts >= ? GROUP BY 1 ORDER BY 1",
            (cutoff,),
        ).fetchall()
    return [(r[0], int(r[1])) for r in rows]


def age_seconds(source: str, key: str) -> float | None:
    """How old the cached entry is, or None if nothing cached."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT fetched_at FROM odds_cache WHERE source=? AND cache_key=?",
            (source, key),
        ).fetchone()
    return time.time() - row[0] if row else None
