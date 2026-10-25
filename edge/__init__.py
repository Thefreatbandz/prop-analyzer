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
    leg is {id, player, side, line, stat, market, book, price,
    fair_prob, ev_pct, result}. Picks without a parlay key are
    ignored — they are single picks, not Edge parlays.
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
            "market": detail.get("market", ""),
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


# Tracker stat label -> ESPN boxscore market key. Tracker legs store
# the human label (e.g. "passing yards"); newer legs also store the
# market key directly, which takes precedence.
LABEL_TO_MARKET = {
    "passing yards": "player_pass_yds",
    "passing tds": "player_pass_tds",
    "rushing yards": "player_rush_yds",
    "rushing tds": "player_rush_tds",
    "receiving yards": "player_rec_yds",
    "receptions": "player_receptions",
    "receiving tds": "player_rec_tds",
}


MARKET_TO_LABEL = {v: k for k, v in LABEL_TO_MARKET.items()}


def leg_market(leg: dict) -> str:
    """ESPN market key for a leg: stored market first, else label map."""
    market = (leg.get("market") or "").strip()
    if market:
        return market
    return LABEL_TO_MARKET.get((leg.get("stat") or "").strip().lower(), "")


def leg_progress(leg: dict, games: list[dict]) -> dict:
    """Live progress for one leg against games with boxscores.

    games: [{status ('live'|'final'), detail, boxscore}] — boxscore in
    live.espn.get_boxscore shape. Pure function: no network, no
    Streamlit, so tests drive it with fake games.

    Returns {state, current, game_detail}:
      live: player has a stat in a live game.
      final: player has a stat in a final game.
      no_stats: player found in no game's boxscore (game not started,
        or player hasn't recorded a stat yet).
      untrackable: the leg's stat has no ESPN market mapping.
    """
    from live import espn as _le

    market = leg_market(leg)
    if not market:
        return {"state": "untrackable", "current": None, "game_detail": ""}
    for g in games:
        val = _le.player_live_stat(g.get("boxscore") or {},
                                   leg["player"], market)
        if val is not None:
            state = g.get("status")
            if state not in ("live", "final"):
                state = "live"
            return {"state": state, "current": val,
                    "game_detail": g.get("detail", "")}
    return {"state": "no_stats", "current": None, "game_detail": ""}


def progress_text(leg: dict, prog: dict, game_date: str | None,
                  today_str: str) -> str:
    """Human line for a leg's live progress.

    Over legs clinch mid-game (stats only grow); under legs can only
    clinch at final, so a live under shows room to spare instead of
    a premature HIT. A final under/over is reported as final, not
    graded here — grading is the Grade-now button's job.
    """
    state, cur = prog["state"], prog["current"]
    line, stat, side = leg["line"], leg["stat"], leg["side"]
    if state == "untrackable":
        return "live tracking unavailable for this stat"
    if state == "final":
        return f"final: {cur:g} / {line:g} {stat} — ready to grade"
    if state == "live":
        if side == "over":
            if cur > line:
                return f"HIT — {cur:g} / {line:g} {stat} ✓"
            if cur == line:
                return f"at the line — {cur:g} / {line:g} {stat}"
            return f"{cur:g} / {line:g} {stat} — needs {line - cur:g} more"
        if cur >= line:
            return (f"{cur:g} / {line:g} {stat} — line already covered, "
                    f"leg lost")
        return f"{cur:g} / {line:g} {stat} — {line - cur:g} to spare"
    if game_date and game_date > today_str:
        return "not started"
    return "no stats yet"


def validate_draft(draft: list[dict], name: str) -> list[str]:
    """Errors blocking a parlay save. Warnings are separate (see
    low_prob_legs): a sub-55% leg warns but never blocks."""
    errors = []
    if len(draft) < 2:
        errors.append("need at least 2 legs")
    if not (name or "").strip():
        errors.append("parlay name required")
    keys = [((d.get("player") or "").strip().lower(),
             (d.get("stat") or "").strip().lower()) for d in draft]
    if len(set(keys)) != len(keys):
        errors.append("duplicate player+stat on the same parlay")
    for d in draft:
        if d.get("price") in (None, 0):
            errors.append(f"missing odds for {d.get('player', '?')}")
        if d.get("line") is None:
            errors.append(f"missing line for {d.get('player', '?')}")
    return errors


def low_prob_legs(draft: list[dict]) -> list[dict]:
    """Draft legs whose model probability is below 55% — warn, don't block."""
    return [d for d in draft
            if d.get("fair_prob") is not None and d["fair_prob"] < 0.55]


def low_prob_legs(draft: list[dict]) -> list[dict]:
    """Draft legs whose model probability is below 55% — warn, don't block."""
    return [d for d in draft
            if d.get("fair_prob") is not None and d["fair_prob"] < 0.55]


# One-off, documented: the Oct 25 GB-DET paper-hypothetical parlay had
# 3 legs, but the tracker's 10-plays-per-day cap blocked 2 of them, so
# only Goff made it into tracker.db. These two live on The Edge
# artifact card. Grading never writes them to the tracker — the Grade
# button only reports their final stats here so they can be graded
# manually from that card.
HYPOTHETICAL_EXTRA_LEGS = [
    {"player": "Jahmyr Gibbs", "side": "over", "line": 50.5,
     "stat": "rushing yards", "game_date": "2026-10-25",
     "teams": ("GB", "DET")},
    {"player": "Josh Jacobs", "side": "under", "line": 80.5,
     "stat": "rushing yards", "game_date": "2026-10-25",
     "teams": ("GB", "DET")},
]


def _player_in_boxscore(boxscore: dict, player: str) -> bool:
    """True if the player appears in any boxscore category."""
    from live.espn import norm_name

    key = norm_name(player)
    for cats in boxscore.values():
        for players in cats.values():
            if key in players:
                return True
    return False


def _grade_outcome(side: str, stat: float, line: float) -> str:
    """win/loss/push for one leg's final stat vs its line."""
    if side == "over":
        return "win" if stat > line else "loss" if stat < line else "push"
    return "win" if stat < line else "loss" if stat > line else "push"


def grade_pending(db_path: str | None = None, scoreboard_fn=None,
                  boxscore_fn=None) -> dict:
    """Grade every PENDING tracker leg whose game is final.

    scoreboard_fn(date_yyyymmdd) -> [{id, away, home, status, ...}];
    boxscore_fn(event_id) -> boxscore dict. Defaults hit live.espn
    (scoreboard takes a dates=YYYYMMDD param, so yesterday's games
    grade fine). Pure except for the DB write and the injected
    fetchers, so tests drive it with fake fetchers.

    Grading rule per leg:
      - player in a final game's boxscore (any category): stat for
        the leg's market, or 0.0 if he has no entry in that category
        (played but recorded nothing there). Compare to the line.
      - player in a live game -> skipped, still live.
      - player in a pre game -> skipped, not started.
      - player in no game that date, and every game that date is
        final -> push (void: did not play / no stats).
      - otherwise skipped (that date's games still pending).

    Returns a report dict: graded / skipped_live / skipped_pre /
    skipped_pending / voided / hypothetical / errors. Writes grades
    via tracker.grade_result().
    """
    from tracker import db as _tdb

    if scoreboard_fn is None:
        from live import espn as _le

        def scoreboard_fn(date_yyyymmdd: str):
            return _le.get_scoreboard(date_yyyymmdd)

    if boxscore_fn is None:
        from live import espn as _le

        def boxscore_fn(event_id: str):
            return _le.get_boxscore(event_id)

    report: dict = {"graded": [], "skipped_live": [], "skipped_pre": [],
                    "skipped_pending": [], "voided": [], "hypothetical": [],
                    "errors": []}
    parlays = load_parlays(db_path)
    pending = [(p, leg) for p in parlays for leg in p["legs"]
               if leg["result"] is None]
    has_hyp = any("HYPOTHETICAL" in p["name"] for p in parlays)

    if pending:
        by_date: dict[str, list] = {}
        for parlay, leg in pending:
            if not parlay["game_date"]:
                report["skipped_pending"].append(
                    (parlay["name"], leg, "no game date"))
                continue
            by_date.setdefault(parlay["game_date"], []).append((parlay, leg))

        for game_date, legs in sorted(by_date.items()):
            yyyymmdd = game_date.replace("-", "")
            try:
                sb = scoreboard_fn(yyyymmdd)
            except Exception:
                sb = []
            if not sb:
                for parlay, leg in legs:
                    report["errors"].append(
                        (parlay["name"], leg, "scoreboard unavailable"))
                continue
            bs_cache: dict = {}

            def _bs(event_id: str) -> dict:
                if event_id not in bs_cache:
                    try:
                        bs_cache[event_id] = boxscore_fn(event_id) or {}
                    except Exception:
                        bs_cache[event_id] = {}
                return bs_cache[event_id]

            all_final = all(g.get("status") == "final" for g in sb)
            for parlay, leg in legs:
                found = None
                for g in sb:
                    if _player_in_boxscore(_bs(g["id"]), leg["player"]):
                        found = g
                        break
                if found is None:
                    if all_final and sb:
                        _tdb.grade_result(leg["id"], "push")
                        report["voided"].append((parlay["name"], leg,
                                                 "did not play / no stats"))
                    else:
                        report["skipped_pending"].append(
                            (parlay["name"], leg, "games still pending"))
                    continue
                if found.get("status") == "live":
                    report["skipped_live"].append((parlay["name"], leg))
                    continue
                if found.get("status") != "final":
                    report["skipped_pre"].append((parlay["name"], leg))
                    continue
                from live import espn as _le

                stat = _le.player_live_stat(_bs(found["id"]), leg["player"],
                                            leg_market(leg))
                if stat is None:
                    stat = 0.0  # played, but nothing in this category
                result = _grade_outcome(leg["side"], stat, leg["line"])
                _tdb.grade_result(leg["id"], result)
                report["graded"].append((parlay["name"], leg, result, stat))

    # Hypothetical extras: report final stats only, never write them.
    # Runs whenever the hypothetical parlay exists in the tracker,
    # even if its logged leg is already graded.
    if not has_hyp:
        return report
    for extra in HYPOTHETICAL_EXTRA_LEGS:
        yyyymmdd = extra["game_date"].replace("-", "")
        try:
            sb = scoreboard_fn(yyyymmdd)
        except Exception:
            sb = []
        game = next((g for g in sb
                     if {g.get("away"), g.get("home")} == set(extra["teams"])),
                    None)
        if game is None or game.get("status") != "final":
            report["hypothetical"].append((extra, None, None))
            continue
        from live import espn as _le

        try:
            bs = boxscore_fn(game["id"]) or {}
        except Exception:
            bs = {}
        stat = _le.player_live_stat(
            bs, extra["player"],
            LABEL_TO_MARKET.get(extra["stat"], ""))
        if stat is None:
            # Played but nothing in this category -> 0.0; absent from
            # the boxscore entirely -> no stats (void), not zero.
            stat = 0.0 if _player_in_boxscore(bs, extra["player"]) else None
        implied = (_grade_outcome(extra["side"], stat, extra["line"])
                   if stat is not None else "push")
        report["hypothetical"].append((extra, stat, implied))
    return report


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


def render(scan_picks: list[dict] | None = None) -> None:
    """Streamlit section: The Edge parlay cards + learning loop.

    scan_picks: this week's ranked scan edges (player, side, line,
    label, market, book, price, fair_prob, ev_pct) used to prefill
    the builder. None means no prefill — manual entry still works.
    """
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

    # --- Live leg tracking (Feature 1) ---
    pending = [p for p in parlays if parlay_status(p) == "PENDING"]
    pending_legs = [leg for p in pending for leg in p["legs"]
                    if leg["result"] is None]
    if pending_legs:
        st.markdown("## Live leg tracking")
        st.caption(
            "Refreshes every minute while games are live. Stats come "
            "from ESPN's free public box scores — text stats only, "
            "not Next Gen Stats tracking (no routes, speed, or "
            "separation). Over legs clinch mid-game; under legs can "
            "only clinch at final."
        )

        @st.fragment(run_every=60)
        def _edge_live():
            import datetime as _dt

            from live import espn as _le
            try:
                sb = _le.get_scoreboard()
            except Exception:
                sb = []
            if not sb:
                st.caption("Live data unavailable right now — ESPN's "
                           "feed didn't respond. Tracking returns "
                           "automatically.")
                return
            games = []
            for g in sb:
                if g.get("status") not in ("live", "final"):
                    continue
                try:
                    bs = _le.get_boxscore(g["id"])
                except Exception:
                    bs = {}
                games.append({"status": g["status"],
                              "detail": g.get("detail", ""),
                              "boxscore": bs})
            today = _dt.date.today().isoformat()
            for parlay in pending:
                legs = [l for l in parlay["legs"]
                        if l["result"] is None]
                if not legs:
                    continue
                st.markdown(f"**{parlay['name']}**")
                for leg in legs:
                    prog = leg_progress(leg, games)
                    txt = progress_text(leg, prog, parlay["game_date"],
                                        today)
                    st.markdown(
                        f"- **{leg['player']}** {leg['side']} "
                        f"{leg['line']} {leg['stat']}: {txt}"
                    )
        _edge_live()

    # --- Build a parlay (Feature 2) ---
    st.markdown("## Build a parlay")
    st.caption(
        "Pick legs from this week's scan edges or enter them by hand. "
        "Combined probability and parlay odds update as you add legs. "
        "Saving logs the legs to the paper tracker — paper-only, "
        "flat 1-unit paper stakes. Builder tracks NFL player markets."
    )
    if "edge_save_msg" in st.session_state:
        st.success(st.session_state.pop("edge_save_msg"))
    if "edge_draft" not in st.session_state:
        st.session_state["edge_draft"] = []
    draft = st.session_state["edge_draft"]

    if scan_picks:
        _prefill = {}
        for _p in scan_picks:
            _prefill[f"{_p['player']} {_p['side']} {_p['line']:g} "
                     f"{_p.get('label', _p['market'])} · {_p['book']} "
                     f"{_fmt_odds(_p['price'])}"] = _p
        _choice = st.selectbox("Prefill from this week's scan edges",
                               ["— pick an edge —"] + list(_prefill.keys()),
                               key="edge_prefill_pick")
        if st.button("Use this edge", key="edge_prefill_use"):
            if _choice in _prefill:
                _p = _prefill[_choice]
                _stat = MARKET_TO_LABEL.get(_p.get("market", ""),
                                            _p.get("label", ""))
                if _stat not in LABEL_TO_MARKET:
                    _stat = "passing yards"
                st.session_state["edge_f_player"] = _p["player"]
                st.session_state["edge_f_side"] = _p["side"]
                st.session_state["edge_f_line"] = float(_p["line"])
                st.session_state["edge_f_stat"] = _stat
                st.session_state["edge_f_book"] = _p["book"]
                st.session_state["edge_f_odds"] = float(_p["price"])
                st.session_state["edge_f_prob"] = float(_p["fair_prob"])
                st.session_state["edge_f_market"] = _p.get("market", "")
                st.session_state["edge_f_ev"] = _p.get("ev_pct")
                st.rerun()

    _c1, _c2 = st.columns(2)
    with _c1:
        st.text_input("Player", key="edge_f_player")
        st.selectbox("Side", ["over", "under"], key="edge_f_side")
        st.number_input("Line", value=None, key="edge_f_line")
        st.selectbox("Stat", list(LABEL_TO_MARKET.keys()),
                     key="edge_f_stat")
    with _c2:
        st.text_input("Book", key="edge_f_book")
        st.number_input("Odds (American)", value=None, key="edge_f_odds")
        st.number_input("Model probability (0–1, optional)", value=None,
                        min_value=0.0, max_value=1.0, key="edge_f_prob")
        st.caption("Leave model probability blank if unknown — combined "
                   "probability shows as — until every leg has one.")
    if st.button("Add leg", key="edge_add_leg"):
        _player = (st.session_state.get("edge_f_player") or "").strip()
        _line = st.session_state.get("edge_f_line")
        _odds = st.session_state.get("edge_f_odds")
        _stat = st.session_state.get("edge_f_stat")
        _add_errors = []
        if not _player:
            _add_errors.append("player required")
        if _line is None or _line <= 0:
            _add_errors.append("line must be above 0")
        if _odds is None or _odds == 0:
            _add_errors.append("odds required (non-zero)")
        if any((d["player"].lower() == _player.lower()
                and d["stat"] == _stat) for d in draft):
            _add_errors.append("duplicate player+stat already on the draft")
        if _add_errors:
            st.error(" · ".join(_add_errors))
        else:
            draft.append({
                "player": _player,
                "side": st.session_state.get("edge_f_side", "over"),
                "line": float(_line),
                "stat": _stat,
                "market": st.session_state.get("edge_f_market") or
                          LABEL_TO_MARKET.get(_stat, ""),
                "book": (st.session_state.get("edge_f_book") or "").strip(),
                "price": float(_odds),
                "fair_prob": st.session_state.get("edge_f_prob"),
                "ev_pct": st.session_state.get("edge_f_ev"),
            })
            st.session_state["edge_f_market"] = ""
            st.session_state["edge_f_ev"] = None
            st.rerun()

    if draft:
        st.markdown("**Your draft**")
        for _i, _d in enumerate(draft):
            _dc1, _dc2 = st.columns([4, 1])
            _dc1.markdown(
                f"- **{_d['player']}** {_d['side']} {_d['line']:g} "
                f"{_d['stat']} · {_d['book']} {_fmt_odds(_d['price'])}"
                f" · model {_fmt_pct(_d['fair_prob'])}"
            )
            if _dc2.button("Remove", key=f"edge_draft_rm_{_i}"):
                draft.pop(_i)
                st.rerun()
        _dprob = combined_prob(draft)
        _dodds = parlay_odds(draft)
        st.markdown(f"Combined model probability: {_fmt_pct(_dprob)} · "
                    f"Parlay odds: {_fmt_odds(_dodds)} · "
                    f"{len(draft)} legs")
        _low = low_prob_legs(draft)
        if _low:
            st.warning("Heads up — these legs are below 55% model "
                       "probability: " + ", ".join(
                           f"{d['player']} {_fmt_pct(d['fair_prob'])}"
                           for d in _low) + ". Saving still allowed.")
    else:
        st.info("No legs yet — pick an edge above or enter one by hand.")

    import datetime as _dt
    _pname = st.text_input("Parlay name", key="edge_save_name",
                           placeholder="e.g. SNF 2026-10-25 3-legger")
    _gdate = st.date_input("Game date", value=_dt.date.today(),
                           key="edge_save_date")
    if st.button("Save parlay to tracker", key="edge_save"):
        _errors = validate_draft(draft, _pname)
        if _errors:
            st.error(" · ".join(_errors))
        else:
            from tracker import db as _tdb
            if _tdb.plays_today() + len(draft) > _tdb.MAX_PLAYS_PER_DAY:
                st.error(
                    f"Daily paper cap reached: {_tdb.plays_today()} plays "
                    f"logged in the last 24h, this parlay needs "
                    f"{len(draft)} more (cap {_tdb.MAX_PLAYS_PER_DAY}). "
                    f"Try again after older plays age out.")
            else:
                _saved = []
                for _d in draft:
                    _pick = {
                        "player": _d["player"], "side": _d["side"],
                        "line": _d["line"], "label": _d["stat"],
                        "market": _d["market"], "book": _d["book"],
                        "price": _d["price"], "fair_prob": _d["fair_prob"],
                        "ev_pct": _d["ev_pct"], "type": "prop",
                        "parlay": _pname.strip(),
                    }
                    _saved.append(_tdb.log_pick(
                        _pick, game_date=_gdate.isoformat()))
                if any(s is None for s in _saved):
                    st.error("Some legs did not save (daily cap hit "
                             "mid-save). Check the tracker list above "
                             "before retrying.")
                else:
                    st.session_state["edge_save_msg"] = (
                        f"Saved '{_pname.strip()}' — {len(_saved)} legs. "
                        f"It appears in the tracker list above.")
                    st.session_state["edge_draft"] = []
                    st.rerun()

    # --- Grade now (Feature 3) ---
    st.markdown("## Grade finished parlays")
    st.caption(
        "Tap Grade now after games go final. It pulls final box scores "
        "from ESPN and grades every pending leg: win, loss, or void "
        "(void = player did not play or recorded no stats). There is "
        "no background scheduler — Streamlit Cloud can't run one "
        "reliably — so this button is the honest design: you tap it "
        "when games are done."
    )
    if "edge_grade_report" in st.session_state:
        _rep = st.session_state["edge_grade_report"]
        _n_graded = len(_rep.get("graded", []))
        _n_void = len(_rep.get("voided", []))
        if (not _n_graded and not _n_void
                and not _rep.get("hypothetical")
                and not _rep.get("errors")):
            st.info("No pending legs to grade.")
        for _name, _leg, _res, _stat in _rep.get("graded", []):
            st.markdown(f"- ✅ {_leg['player']} {_leg['side']} "
                        f"{_leg['line']:g} {_leg['stat']}: "
                        f"final {_stat:g} → **{_res}** ({_name})")
        for _name, _leg, _reason in _rep.get("voided", []):
            st.markdown(f"- ⏭️ {_leg['player']} {_leg['side']} "
                        f"{_leg['line']:g} {_leg['stat']}: "
                        f"void — {_reason} ({_name})")
        for _name, _leg in _rep.get("skipped_live", []):
            st.markdown(f"- ⏳ {_leg['player']}: game still live, "
                        f"not graded ({_name})")
        for _name, _leg in _rep.get("skipped_pre", []):
            st.markdown(f"- ⏳ {_leg['player']}: game not started, "
                        f"not graded ({_name})")
        for _name, _leg, _reason in _rep.get("skipped_pending", []):
            st.markdown(f"- ⏳ {_leg['player']}: {_reason} ({_name})")
        for _name, _leg, _reason in _rep.get("errors", []):
            st.warning(f"⚠️ {_leg['player']}: {_reason} ({_name})")
        for _extra, _stat, _implied in _rep.get("hypothetical", []):
            if _stat is None:
                st.markdown(
                    f"- 📋 {_extra['player']} {_extra['side']} "
                    f"{_extra['line']:g} {_extra['stat']}: no final "
                    f"stats yet — grade manually from The Edge card.")
            else:
                st.markdown(
                    f"- 📋 {_extra['player']} {_extra['side']} "
                    f"{_extra['line']:g} {_extra['stat']}: final "
                    f"{_stat:g} → would be **{_implied}** (manual "
                    f"only — this leg is not in the tracker, so it "
                    f"was not graded here).")
        if st.button("Dismiss", key="edge_grade_dismiss"):
            del st.session_state["edge_grade_report"]
            st.rerun()
    if st.button("Grade now", key="edge_grade_now"):
        try:
            _rep = grade_pending()
        except Exception as _e:
            _rep = {"graded": [], "skipped_live": [], "skipped_pre": [],
                    "skipped_pending": [], "voided": [], "hypothetical": [],
                    "errors": [("", {"player": "grading run"},
                                f"grading failed: {_e}")]}
        st.session_state["edge_grade_report"] = _rep
        st.rerun()

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
