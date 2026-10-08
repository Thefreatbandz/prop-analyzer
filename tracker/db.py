"""Paper tracker — the Stackz rule, enforced in code.

Every +EV flag gets logged BEFORE the game with: timestamp, book, line,
odds, fair prob, EV%. Nothing here touches real money — stakes are flat
1 paper unit, max plays per day, and the README documents the
100-picks-before-real-money rule.

Grading (two report cards):
  1. CLV (closing line value): did the line move OUR way after we logged
     it? Positive CLV = we beat the market = skill signal.
  2. Actuals: did the bet win? Win rate + ROI in paper units.

CLV math for a -110-style bet: convert our logged price and the closing
price to implied probs (no-vig vs the other side when available, raw
otherwise). CLV = implied(closing) - implied(logged), in our favor's
direction. Positive = the market moved toward us.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tracker.db")

# Bankroll guardrails (paper): flat stakes, daily cap. Real-money sizing
# (Kelly etc.) stays OFF until the edge is proven — see README.
UNIT = 1.0
MAX_PLAYS_PER_DAY = 10
MIN_PICKS_BEFORE_REAL_MONEY = 100


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS picks (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               logged_at REAL,
               game_date TEXT,
               type TEXT,            -- 'prop' | 'moneyline'
               label TEXT,           -- 'Josh Allen over 267.5 pass yds'
               book TEXT,
               line REAL,
               price REAL,           -- american odds at log time
               fair_prob REAL,
               ev_pct REAL,
               closing_price REAL,   -- filled near kickoff
               result TEXT,          -- 'win' | 'loss' | 'push' | NULL
               profit_units REAL,    -- graded profit in paper units
               detail TEXT           -- JSON: full pick dict
           )"""
    )
    return conn


def plays_today() -> int:
    """How many paper plays logged in the last 24h (guardrail)."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM picks WHERE logged_at > ?", (time.time() - 86400,)
        ).fetchone()
    return row[0]


def log_pick(pick: dict, game_date: str = "") -> int | None:
    """Log a +EV flag. Returns row id, or None if the daily cap is hit."""
    if plays_today() >= MAX_PLAYS_PER_DAY:
        return None
    label = pick.get("label") or _label_for(pick)
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO picks
               (logged_at, game_date, type, label, book, line, price,
                fair_prob, ev_pct, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                game_date,
                pick.get("type"),
                label,
                pick.get("book"),
                pick.get("line"),
                pick.get("price"),
                pick.get("fair_prob"),
                pick.get("ev_pct"),
                json.dumps(pick),
            ),
        )
        return cur.lastrowid


def _label_for(pick: dict) -> str:
    if pick.get("type") == "prop":
        return f"{pick['player']} {pick['side']} {pick['line']} {pick['label']}"
    return f"{pick['team']} ML"


def set_closing(pick_id: int, closing_price: float) -> None:
    """Record the closing line (call near kickoff) — enables CLV."""
    with _conn() as conn:
        conn.execute("UPDATE picks SET closing_price=? WHERE id=?", (closing_price, pick_id))


def _profit_units(price: float, result: str) -> float:
    # Flat 1-unit paper stakes. Win: profit = decimal - 1. Loss: -1.
    from engine.odds_math import american_to_decimal

    if result == "win":
        return american_to_decimal(price) - 1.0
    if result == "loss":
        return -UNIT
    return 0.0  # push


def grade_result(pick_id: int, result: str) -> None:
    """Grade win/loss/push after the game. result in {'win','loss','push'}."""
    assert result in ("win", "loss", "push")
    with _conn() as conn:
        row = conn.execute("SELECT price FROM picks WHERE id=?", (pick_id,)).fetchone()
        if not row:
            raise KeyError(f"pick {pick_id} not found")
        conn.execute(
            "UPDATE picks SET result=?, profit_units=? WHERE id=?",
            (result, _profit_units(row[0], result), pick_id),
        )


def clv_for(pick_id: int) -> float | None:
    """Closing line value in implied-probability points, signed so that
    positive = the market moved in our favor.

    For an OVER (or moneyline side we took): if the closing price got
    SHORTER (more negative, e.g. -110 -> -130), the market agrees with us
    -> positive CLV.
    """
    from engine.odds_math import american_to_implied

    with _conn() as conn:
        row = conn.execute(
            "SELECT price, closing_price, type, detail FROM picks WHERE id=?",
            (pick_id,),
        ).fetchone()
    if not row or row[1] is None:
        return None
    price, closing, _, detail_json = row
    detail = json.loads(detail_json or "{}")
    side = detail.get("side", "over")
    imp_now, imp_close = american_to_implied(price), american_to_implied(closing)
    # We took over/home: favorable move = closing implies HIGHER prob.
    # We took under/away: favorable = closing implies LOWER prob for our side.
    return (imp_close - imp_now) if side in ("over", "home") else (imp_now - imp_close)


def weekly_summary(days: int | None = 7) -> dict:
    """Report card: picks, win rate, ROI (paper units), avg CLV, avg EV.

    days=None = lifetime (the public track record). Otherwise the last
    `days` days (the Tracker's ops view).
    """
    with _conn() as conn:
        if days is None:
            rows = conn.execute(
                "SELECT id, result, profit_units, ev_pct FROM picks"
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, result, profit_units, ev_pct FROM picks
                   WHERE logged_at > ?""",
                (time.time() - days * 86400,),
            ).fetchall()
    graded = [r for r in rows if r[1] in ("win", "loss", "push")]
    wins = sum(1 for r in graded if r[1] == "win")
    profit = sum(r[2] or 0 for r in graded)
    staked = sum(1 for r in graded if r[1] in ("win", "loss")) * UNIT
    clvs = [c for c in (clv_for(r[0]) for r in rows) if c is not None]
    return {
        "picks_logged": len(rows),
        "picks_graded": len(graded),
        "win_rate": round(wins / len(graded), 3) if graded else None,
        "profit_units": round(profit, 2),
        "roi": round(profit / staked, 3) if staked else None,
        "avg_clv_pts": round(sum(clvs) / len(clvs), 4) if clvs else None,
        "avg_ev_pct": round(sum(r[3] for r in rows if r[3]) / len(rows), 2) if rows else None,
        "picks_until_real_money": max(0, MIN_PICKS_BEFORE_REAL_MONEY - len(graded)),
    }


def track_record() -> dict:
    """The PUBLIC track record: lifetime numbers for the proof page.

    Same math as weekly_summary, but over every pick ever logged — no
    window to cherry-pick. The pick log underneath it shows every row,
    so anyone can audit the totals. Includes the 100-pick gate progress
    (the Stackz rule: no real money talk before 100 graded picks).
    """
    s = weekly_summary(days=None)
    s["gate_target"] = MIN_PICKS_BEFORE_REAL_MONEY
    s["gate_done"] = s["picks_graded"] >= MIN_PICKS_BEFORE_REAL_MONEY
    return s


def all_picks(limit: int = 200) -> list[dict]:
    """Recent picks for the dashboard tracker view."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, logged_at, type, label, book, line, price,
                      fair_prob, ev_pct, closing_price, result, profit_units
               FROM picks ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    cols = ["id", "logged_at", "type", "label", "book", "line", "price",
            "fair_prob", "ev_pct", "closing_price", "result", "profit_units"]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d["logged_at"] = datetime.fromtimestamp(d["logged_at"]).strftime("%m-%d %H:%M")
        d["clv_pts"] = clv_for(d["id"])
        out.append(d)
    return out
