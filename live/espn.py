"""Live NFL game data from ESPN's free scoreboard API (no key needed).

Two jobs:
  * get_scoreboard() — today's games: scores, clock, who's live.
  * get_boxscore(event_id) — live player stats for one game, so Builder
    legs and test parlays can track progress mid-game
    ("Maye: 85 / 225.5 yds — Q1").

Honesty rules: ESPN is the source for scores/stats; when a game isn't
live or a player has no stats yet, we say so — never interpolate or
project a final from partial data.
"""
from __future__ import annotations

import re
import unicodedata

SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
)
SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
)

# market -> (ESPN boxscore category, stat index within the stats list)
# Verified against live 2026-10-11 summary boxscores:
#   passing:   C/ATT(combined)/YDS/YPA/TD/INT/SACKS/RTG
#   rushing:   CAR/YDS/YPA/TD/LONG
#   receiving: REC/YDS/YPA/TD/LONG/TGTS
LIVE_STAT_MAP = {
    "player_pass_yds": ("passing", 1),
    "player_pass_tds": ("passing", 3),
    "player_rush_yds": ("rushing", 1),
    "player_rush_tds": ("rushing", 3),
    "player_rec_yds": ("receiving", 1),
    "player_receptions": ("receiving", 0),
    "player_rec_tds": ("receiving", 3),
}


def norm_name(name: str) -> str:
    """Punctuation/case-blind name key: \"Ja'Marr Chase\" -> \"jamarrchase\"."""
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", n.lower())


def _get(url: str, params: dict | None = None, timeout: int = 20) -> dict:
    import requests

    r = requests.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _overall_record(competitor: dict) -> str:
    """Overall W-L summary (e.g. '4-2') from a scoreboard competitor."""
    for r in competitor.get("records") or []:
        if r.get("type") == "total":
            return r.get("summary", "")
    recs = competitor.get("records") or []
    return recs[0].get("summary", "") if recs else ""


def get_scoreboard() -> list[dict]:
    """Today's games: [{id, away, home, away_score, home_score,
    away_record, home_record, status ('live'|'pre'|'final'),
    detail ('2:34 - 1st'), live: bool}]."""
    try:
        data = _get(SCOREBOARD_URL)
    except Exception:
        return []
    out = []
    for e in data.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        st = comp.get("status", {}).get("type", {})
        state = st.get("state", "")
        out.append({
            "id": str(e.get("id", "")),
            "away": (away.get("team") or {}).get("abbreviation", ""),
            "home": (home.get("team") or {}).get("abbreviation", ""),
            "away_score": away.get("score", ""),
            "home_score": home.get("score", ""),
            "away_record": _overall_record(away),
            "home_record": _overall_record(home),
            "status": ("live" if state == "in"
                       else "final" if state == "post" else "pre"),
            "detail": st.get("shortDetail", ""),
            "live": state == "in",
        })
    return out


def get_boxscore(event_id: str) -> dict:
    """{team_abbr: {category: {norm_name: {'name': display, 'stats': [...]}}}}.

    Empty dict on any failure — the caller shows 'no live data', never
    a crash.
    """
    try:
        data = _get(SUMMARY_URL, params={"event": event_id})
    except Exception:
        return {}
    out: dict = {}
    for t in data.get("boxscore", {}).get("players", []):
        abbr = (t.get("team") or {}).get("abbreviation", "")
        cats: dict = {}
        for cat in t.get("statistics", []):
            players = {}
            for a in cat.get("athletes", []):
                name = (a.get("athlete") or {}).get("displayName", "")
                if name:
                    players[norm_name(name)] = {
                        "name": name,
                        "stats": a.get("stats", []),
                    }
            if players:
                cats[cat.get("name", "")] = players
        if cats:
            out[abbr] = cats
    return out


def get_play_by_play(event_id: str) -> list[dict]:
    """Plays for one game, most recent first.

    Each play: {type, text, period, clock, away_score, home_score,
    scoring}. The text is ESPN's description, which names who got the
    ball on the play (passer, receiver, or ball carrier) — text only,
    not Next Gen Stats tracking (no routes, speed, or separation).
    Empty list on any failure — the caller shows 'no live data',
    never a crash.
    """
    try:
        data = _get(SUMMARY_URL, params={"event": event_id})
    except Exception:
        return []
    plays = []
    drives = data.get("drives") or {}
    for d in drives.get("previous") or []:
        plays.extend(d.get("plays") or [])
    current = drives.get("current") or {}
    plays.extend(current.get("plays") or [])
    out = []
    for p in plays:
        text = p.get("text", "")
        if not text:
            continue
        out.append({
            "type": (p.get("type") or {}).get("text", ""),
            "text": text,
            "period": (p.get("period") or {}).get("number", ""),
            "clock": (p.get("clock") or {}).get("displayValue", ""),
            "away_score": p.get("awayScore", ""),
            "home_score": p.get("homeScore", ""),
            "scoring": bool(p.get("scoringPlay")),
        })
    out.reverse()
    return out


def player_live_stat(boxscore: dict, player: str,
                     market: str) -> float | None:
    """Current live stat value for one player+market, or None.

    Searches every team in the boxscore (no team mapping needed).
    Returns None when the market isn't live-trackable or the player
    has no stats yet.
    """
    mapping = LIVE_STAT_MAP.get(market)
    if not mapping:
        return None
    category, idx = mapping
    key = norm_name(player)
    for cats in boxscore.values():
        entry = (cats.get(category) or {}).get(key)
        if entry:
            try:
                return float(entry["stats"][idx])
            except (IndexError, ValueError, TypeError):
                return None
    return None


def find_player_game(scoreboard: list[dict], boxscores: dict,
                     player: str) -> dict | None:
    """The live game dict where this player has boxscore stats, or None."""
    key = norm_name(player)
    for g in scoreboard:
        if not g.get("live"):
            continue
        bs = boxscores.get(g["id"], {})
        for cats in bs.values():
            for cat_players in cats.values():
                if key in cat_players:
                    return g
    return None
