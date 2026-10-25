"""The Edge: paper parlay builder + tracker for BANDZ EDGE.

A parlay is a group of logged paper picks whose tracker `detail` JSON
carries the same `parlay` key (e.g. 'SNF 2026-10-25 3-legger'). Legs
are paper-only: flat 1-unit paper stakes, no real money, no payouts
to cash. This module reads the paper tracker SQLite DB and renders
each parlay with its legs, combined model probability, parlay odds,
and status — plus the learning loop that feeds graded results back
into future parlay construction.

NOTE on data source: Streamlit Cloud SQLite is ephemeral, so the
deployed app reads whatever its own instance DB holds. The local
dev DB (data/tracker.db) is the source of truth for now; parlays
logged locally appear in the deployed section only after they are
logged on that instance. Never silently merge or invent rows.
"""

from __future__ import annotations

import json
import os
import sqlite3

from engine.odds_math import american_to_decimal, decimal_to_american

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                   "data", "tracker.db")


def _conn(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or DB
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def load_parlays(db_path: str | None = None) -> list[dict]:
    """Group tracker picks by their `detail['parlay']` key.

    Returns parlays ordered by first-logged leg, each with:
    name, game_date (earliest leg), legs (in logged order), where a
    leg is {id, player, side, line, stat, book, price, fair_prob,
    ev_pct, result}. Picks without a parlay key are ignored — they
    are single picks, not Edge parlays.
    """
    try:
        conn = _conn(db_path)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            "SELECT id, game_date, book, line, price, fair_prob, ev_pct,"
            " result, detail FROM picks ORDER BY id"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    grouped: dict[str, dict] = {}
    for r in rows:
        try:
            detail = json.loads(r["detail"] or "{}")
        except (ValueError, TypeError):
            continue
        name = detail.get("parlay")
        if not name:
            continue
        leg = {
            "id": r["id"],
            "player": detail.get("player", ""),
            "side": detail.get("side", ""),
            "line": r["line"],
            "stat": detail.get("label", ""),
            "book": r["book"],
            "price": r["price"],
            "fair_prob": r["fair_prob"],
            "ev_pct": r["ev_pct"],
            "result": r["result"],
        }
        if name not in grouped:
            grouped[name] = {"name": name, "game_date": r["game_date"],
                             "legs": []}
        grouped[name]["legs"].append(leg)
        # Earliest leg's game_date wins; legs are id-ordered so the
        # first one set stands.
    return list(grouped.values())


def combined_prob(legs: list[dict]) -> float | None:
    """Product of leg model probabilities. None if any leg lacks one."""
    probs = [leg["fair_prob"] for leg in legs]
    if not legs or any(p is None for p in probs):
        return None
    out = 1.0
    for p in probs:
        out *= p
    return out


def parlay_odds(legs: list[dict]) -> float | None:
    """Parlay American odds from leg prices. None if any leg lacks one."""
    prices = [leg["price"] for leg in legs]
    if not legs or any(p is None for p in prices):
        return None
    dec = 1.0
    for p in prices:
        dec *= american_to_decimal(p)
    return round(decimal_to_american(dec))


def parlay_status(parlay: dict) -> str:
    """PENDING until every leg is graded; then WON / LOST / MIXED.

    A 'push' leg is a void (player did not play): it reduces the
    parlay rather than losing it, so a parlay with only wins and
    voids counts as WON.
    """
    results = [leg["result"] for leg in parlay["legs"]]
    if any(r is None for r in results):
        return "PENDING"
    if any(r == "loss" for r in results):
        return "LOST"
    if any(r == "win" for r in results):
        return "WON"
    return "VOID"


def learning_summary(db_path: str | None = None) -> dict:
    """Graded-result feedback for the learning loop.

    Buckets graded Edge legs by side (over/under) and by book, so
    tomorrow's analysis can see which leg types hit and which books'
    lines held value. Empty when nothing is graded yet — the section
    renders a structured placeholder in that case.
    """
    parlays = load_parlays(db_path)
    by_side: dict[str, dict] = {}
    by_book: dict[str, dict] = {}
    graded = 0
    for parlay in parlays:
        for leg in parlay["legs"]:
            if leg["result"] not in ("win", "loss"):
                continue
            graded += 1
            for bucket, key in ((by_side, leg["side"]), (by_book, leg["book"])):
                entry = bucket.setdefault(key, {"wins": 0, "losses": 0})
                if leg["result"] == "win":
                    entry["wins"] += 1
                else:
                    entry["losses"] += 1
    return {"graded_legs": graded, "by_side": by_side, "by_book": by_book}


def _fmt_odds(price: float | None) -> str:
    if price is None:
        return "—"
    price = round(price)
    return f"+{price}" if price > 0 else f"{price}"


def _fmt_pct(prob: float | None) -> str:
    if prob is None:
        return "—"
    return f"{prob * 100:.1f}%"


def render() -> None:
    """Streamlit section: The Edge parlay cards + learning loop."""
    import streamlit as st

    st.markdown("## The Edge")
    st.caption(
        "Paper parlay builder and tracker. All legs are paper-only — "
        "flat 1-unit paper stakes, no real money, no cash payouts. "
        "Parlays are built from the Scan board with the deeper pass: "
        "confirmed starters, injury checks, model-blind-spot fades, "
        "and backup-trap filtering."
    )
    st.caption(
        "Data source: this deployed instance's paper tracker. "
        "Streamlit Cloud storage is ephemeral, so the local dev "
        "tracker is the source of truth for now."
    )

    parlays = load_parlays()
    if not parlays:
        st.info(
            "No Edge parlays logged on this instance yet. Parlays "
            "logged to the paper tracker appear here automatically."
        )
    for parlay in parlays:
        legs = parlay["legs"]
        prob = combined_prob(legs)
        odds = parlay_odds(legs)
        status = parlay_status(parlay)
        header = f"### {parlay['name']}"
        if parlay["game_date"]:
            header += f" · {parlay['game_date']}"
        st.markdown(header)
        st.markdown(
            f"**Status: {status}** · Combined model probability: "
            f"{_fmt_pct(prob)} · Parlay odds: {_fmt_odds(odds)} · "
            f"{len(legs)} legs"
        )
        for leg in legs:
            result = leg["result"] or "pending"
            st.markdown(
                f"- **{leg['player']}** {leg['side']} {leg['line']} "
                f"{leg['stat']} · {leg['book']} {_fmt_odds(leg['price'])} "
                f"· model {_fmt_pct(leg['fair_prob'])}"
                + (f" · EV {leg['ev_pct']:+.1f}%" if leg["ev_pct"] is not None else "")
                + f" · {result}"
            )

    st.markdown("## How The Edge Gets Better")
    st.caption(
        "After each game, every leg is graded win / loss / void. "
        "Graded results feed back into the next build: which leg "
        "types hit, which books' lines held value, and where the "
        "deeper pass caught or missed something."
    )
    summary = learning_summary()
    if summary["graded_legs"] == 0:
        st.markdown(
            "- **Leg types that hit:** pending — no graded legs yet.\n"
            "- **Books/lines that held value:** pending — no graded legs yet.\n"
            "- **Deeper-pass catches/misses:** pending — grading starts "
            "after the first Edge games finalize."
        )
    else:
        st.markdown(f"**Graded legs: {summary['graded_legs']}**")
        for side, counts in sorted(summary["by_side"].items()):
            total = counts["wins"] + counts["losses"]
            st.markdown(f"- {side or '—'} legs: {counts['wins']}-{counts['losses']} "
                        f"({total} graded)")
        for book, counts in sorted(summary["by_book"].items()):
            total = counts["wins"] + counts["losses"]
            st.markdown(f"- {book or '—'}: {counts['wins']}-{counts['losses']} "
                        f"({total} graded)")
