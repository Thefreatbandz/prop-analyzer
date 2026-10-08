"""Upcoming-games schedule from the Lumify events feed.

Learn-mode tour:
  - Lumify's /v1/events?status=scheduled returns the upcoming NFL slate
    (the same feed the props scanner already uses — no extra API key,
    no extra credit burn beyond the 1-credit events call).
  - parse_events() turns the raw payload into plain display dicts:
    {away, home, abbrs, starts_at, week, is_today}. Pure function, so
    it's unit-testable with synthetic events (see tests/).

"Today" is judged in US Eastern — that's where Tbandz watches from,
and where the primetime windows are anchored. A game at 8:15 PM ET on
Friday counts as Friday's game even though it's Saturday UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # very old Pythons; the app targets 3.11+
    ZoneInfo = None


def _eastern():
    # Learn-mode: some minimal server images (like Streamlit Cloud's)
    # ship WITHOUT the tz database, so ZoneInfo("America/New_York")
    # raises ZoneInfoNotFoundError at import time — and an import-time
    # crash takes down the whole app ("Oh no. Error running app").
    # Never let a missing tz database break startup: UTC fallback.
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo("America/New_York")
    except Exception:
        return timezone.utc


# Display timezone for kickoff times and the "today" badge.
ET = _eastern()

from teams.colors import NAME_TO_ABBR


def parse_starts_at(raw: str | None):
    """ISO-8601 kickoff -> aware datetime, or None on garbage input.

    Lumify sends "2026-10-09T00:15:00Z". Never raises — a schedule row
    with no time still renders, it just says "TBD".
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def split_matchup(name: str) -> tuple[str, str]:
    """'Tampa Bay Buccaneers at Dallas Cowboys' -> (away, home).

    Falls back to ("", name) when the shape is unexpected — the row
    still renders, it just shows the raw event name.
    """
    if not name or " at " not in name:
        return "", (name or "")
    away, home = name.rsplit(" at ", 1)
    return away.strip(), home.strip()


def name_to_abbr(full_name: str) -> str | None:
    """Full team name -> abbr ("Dallas Cowboys" -> "DAL")."""
    if not full_name:
        return None
    return NAME_TO_ABBR.get(full_name.strip())


def parse_events(events: list[dict], today_et=None) -> list[dict]:
    """Raw Lumify events -> sorted display dicts.

    Each: {away, home, away_abbr, home_abbr, starts_at (aware dt|None),
    week, is_today}. Sorted by kickoff, dateless rows last. today_et is
    a datetime.date in Eastern; games kicking off that date get the
    TODAY badge.
    """
    if today_et is None:
        today_et = datetime.now(ET).date()
    games = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        away, home = split_matchup(e.get("name", ""))
        dt = parse_starts_at(e.get("starts_at") or e.get("scheduled_start_at"))
        games.append(
            {
                "away": away,
                "home": home,
                "away_abbr": name_to_abbr(away),
                "home_abbr": name_to_abbr(home),
                "starts_at": dt,
                "week": e.get("round") or "",
                "is_today": bool(dt) and dt.astimezone(ET).date() == today_et,
            }
        )
    games.sort(key=lambda g: (g["starts_at"] is None, g["starts_at"]))
    return games


def kickoff_label(dt) -> str:
    """'Fri, Oct 9 · 8:15 PM ET' — or 'TBD' when there's no time."""
    if not dt:
        return "TBD"
    local = dt.astimezone(ET)
    return local.strftime("%a, %b %-d · %-I:%M %p ET")
