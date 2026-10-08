"""Line-movement alerts — watchlist + movement detection (PREMIUM).

The idea: you watch a few players. Between scans, books move their
lines (injury news, sharp money, weather). A line that moves 1.5+ points
or odds that move 10+ cents is the market telling you something — this
flags it.

How it works:
  1. Add players (+ markets) to your watchlist.
  2. "Snapshot lines" stores the current board for watched players.
  3. Later, "Check movements" pulls the board again and diffs it.
  4. Push scheduling (cron/Streamlit) is the future step — see README.

Thresholds: LINE_TOL = 1.5 points, ODDS_TOL = 10 (American-odds cents).
"""
from __future__ import annotations

import os
import sqlite3
import time

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data",
                  "alerts.db")

LINE_TOL = 1.5   # points of line movement worth flagging
ODDS_TOL = 10    # cents of odds movement worth flagging


def _conn(path: str | None = None) -> sqlite3.Connection:
    # path override exists so tests don't touch the real DB.
    db_path = path or DB
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS watchlist (
               player TEXT,
               market TEXT,
               added_at REAL,
               PRIMARY KEY (player, market)
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS snapshots (
               player TEXT,
               market TEXT,
               book TEXT,
               line REAL,
               over_price REAL,
               under_price REAL,
               ts REAL,
               PRIMARY KEY (player, market, book)
           )"""
    )
    return conn


# ---------- watchlist ----------

def add_watch(player: str, market: str, path: str | None = None) -> None:
    if not player.strip():
        raise ValueError("Player name required.")
    with _conn(path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (player, market, added_at)"
            " VALUES (?, ?, ?)",
            (player.strip(), market, time.time()),
        )


def remove_watch(player: str, market: str, path: str | None = None) -> None:
    with _conn(path) as conn:
        conn.execute(
            "DELETE FROM watchlist WHERE player = ? AND market = ?",
            (player, market),
        )


def list_watch(path: str | None = None) -> list[dict]:
    with _conn(path) as conn:
        rows = conn.execute(
            "SELECT player, market, added_at FROM watchlist ORDER BY added_at"
        ).fetchall()
    return [{"player": r[0], "market": r[1], "added_at": r[2]} for r in rows]


# ---------- snapshots + detection ----------

def snapshot_board(board: list[dict], path: str | None = None) -> int:
    """Store the current board (normalized prop rows). Returns rows saved.

    board rows: {player, market, books: [{book, line, over, under}]}.
    Only watched (player, market) pairs are snapshotted — credits and
    disk stay proportional to what you actually watch.
    """
    watched = {(w["player"], w["market"]) for w in list_watch(path)}
    n = 0
    with _conn(path) as conn:
        for prop in board:
            if (prop.get("player"), prop.get("market")) not in watched:
                continue
            for b in prop.get("books", []):
                conn.execute(
                    """INSERT OR REPLACE INTO snapshots
                       (player, market, book, line, over_price, under_price, ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (prop["player"], prop["market"], b.get("book"),
                     b.get("line"), b.get("over"), b.get("under"),
                     time.time()),
                )
                n += 1
    return n


def detect_movements(board: list[dict], path: str | None = None,
                     line_tol: float = LINE_TOL,
                     odds_tol: float = ODDS_TOL) -> list[dict]:
    """Diff the current board against the last snapshot.

    Flags: line moved >= line_tol points, or either side's odds moved
    >= odds_tol cents, per book. Returns alert dicts, biggest move first.
    No snapshot yet -> [] (nothing to compare against).
    """
    alerts = []
    with _conn(path) as conn:
        old = {
            (r[0], r[1], r[2]): {"line": r[3], "over": r[4], "under": r[5]}
            for r in conn.execute(
                "SELECT player, market, book, line, over_price, under_price"
                " FROM snapshots"
            ).fetchall()
        }
    for prop in board:
        for b in prop.get("books", []):
            key = (prop.get("player"), prop.get("market"), b.get("book"))
            prev = old.get(key)
            if not prev or prev["line"] is None or b.get("line") is None:
                continue
            line_move = b["line"] - prev["line"]
            over_move = ((b.get("over") or 0) - (prev["over"] or 0)
                         if b.get("over") is not None
                         and prev["over"] is not None else 0)
            under_move = ((b.get("under") or 0) - (prev["under"] or 0)
                          if b.get("under") is not None
                          and prev["under"] is not None else 0)
            reasons = []
            if abs(line_move) >= line_tol:
                reasons.append(f"line {prev['line']:g} → {b['line']:g} "
                               f"({line_move:+.1f})")
            if abs(over_move) >= odds_tol:
                reasons.append(f"over {prev['over']:+.0f} → {b['over']:+.0f}")
            if abs(under_move) >= odds_tol:
                reasons.append(f"under {prev['under']:+.0f} → "
                               f"{b['under']:+.0f}")
            if reasons:
                alerts.append({
                    "player": prop.get("player"),
                    "market": prop.get("market"),
                    "book": b.get("book"),
                    "reasons": reasons,
                    "magnitude": max(abs(line_move),
                                     abs(over_move) / 10,
                                     abs(under_move) / 10),
                })
    alerts.sort(key=lambda a: a["magnitude"], reverse=True)
    return alerts
