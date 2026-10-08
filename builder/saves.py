"""Saved prop builds — named SGP slips (PREMIUM feature).

The builder itself is free. SAVING a build (naming it, keeping it,
sharing the slip later) is premium — that's the product decision in
config.py. The storage is plain SQLite, same pattern as tracker/db.py.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data",
                  "builder_saves.db")


def _conn(path: str | None = None) -> sqlite3.Connection:
    # path override exists so tests don't touch the real DB.
    db_path = path or DB
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS builds (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT UNIQUE,
               legs_json TEXT,
               combined_p REAL,
               book_american REAL,
               ev_pct REAL,
               created_at REAL
           )"""
    )
    return conn


def save_build(name: str, legs: list[dict], combined_p: float | None = None,
               book_american: float | None = None,
               ev_pct: float | None = None,
               path: str | None = None) -> int:
    """Save a named build. Returns row id (replaces same-name builds)."""
    if not name.strip():
        raise ValueError("Build needs a name.")
    if not legs:
        raise ValueError("Can't save an empty build.")
    with _conn(path) as conn:
        conn.execute("DELETE FROM builds WHERE name = ?", (name.strip(),))
        cur = conn.execute(
            """INSERT INTO builds
               (name, legs_json, combined_p, book_american, ev_pct, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name.strip(), json.dumps(legs), combined_p, book_american,
             ev_pct, time.time()),
        )
        return cur.lastrowid


def list_builds(path: str | None = None) -> list[dict]:
    """All saved builds, newest first."""
    with _conn(path) as conn:
        rows = conn.execute(
            "SELECT id, name, legs_json, combined_p, book_american, "
            "ev_pct, created_at FROM builds ORDER BY id DESC"
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "name": r[1], "legs": json.loads(r[2]),
            "combined_p": r[3], "book_american": r[4], "ev_pct": r[5],
            "created_at": r[6],
        })
    return out


def delete_build(build_id: int, path: str | None = None) -> None:
    with _conn(path) as conn:
        conn.execute("DELETE FROM builds WHERE id = ?", (build_id,))
