"""Spotlight View, full-league roster lookup, and games strip tests.

Covers Tbandz's three asks (2026-10-08):
  a) View on a suggestion with no +EV flags always renders the player
     spotlight — never the generic dead-end empty state.
  b) Roster lookup resolves variant/depth names the old exact-match
     code missed or, worse, resolved to the WRONG player
     ("AJ Brown" -> Trent Brown, HOU OL).
  c) The games strip renders with today's games (TODAY badge), future
     games, and degrades honestly when the feed is empty.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import polars as pl

from players import profiles, headshots
from ui import cards
from games import schedule as gsched

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "nflverse")


def _rosters():
    return pl.read_parquet(os.path.join(DATA, "rosters_2026_2026_2026.parquet"))


def _stats():
    return pl.read_parquet(os.path.join(DATA, "player_stats_2015_2026.parquet"))


# ---------- (b) roster lookup: every name resolves to the RIGHT player ----------

def test_find_player_variant_punctuation_resolves():
    # The old exact-match code returned Trent Brown (HOU, OL) for
    # "AJ Brown" — the last-name fallback took an arbitrary row.
    bio = profiles.find_player(_rosters(), "AJ Brown")
    assert bio is not None
    assert bio["name"] == "A.J. Brown", bio
    assert bio["position"] == "WR", bio


def test_find_player_exact_still_works():
    bio = profiles.find_player(_rosters(), "Erick All")
    assert bio["name"] == "Erick All"
    assert bio["team"] == "CIN" and bio["position"] == "TE"


def test_find_player_last_name_ambiguous_is_none():
    # "Allen" matches several real players — guessing one is how the
    # old code showed Trent Brown for "AJ Brown". An honest None beats
    # a wrong player; the UI shows its "couldn't match" fallback.
    assert profiles.find_player(_rosters(), "Allen", team="BUF") is None
    assert profiles.find_player(_rosters(), "Allen") is None


def test_find_player_last_name_unique_resolves():
    # Exactly one Mahomes / one Kelce in the league -> resolves fine.
    assert profiles.find_player(_rosters(), "Mahomes")["name"] == \
        "Patrick Mahomes"
    assert profiles.find_player(_rosters(), "Kelce")["name"] == "Travis Kelce"


def test_find_player_suffix_prefix_match():
    bio = profiles.find_player(_rosters(), "Chris Godwin")
    assert bio["name"] == "Chris Godwin Jr.", bio


def test_find_player_unknown_is_none():
    # Team defenses / novelty markets are not players — None, not a
    # wrong player.
    assert profiles.find_player(_rosters(), "Dallas Defense") is None
    assert profiles.find_player(_rosters(), "First TD") is None
    assert profiles.find_player(_rosters(), "") is None


def test_headshot_lookup_uses_same_normalization():
    row = headshots._row_for("AJ Brown", _rosters())
    assert row is not None and row["full_name"] == "A.J. Brown"


def test_roster_coverage_is_full_league():
    cov = profiles.roster_coverage(_rosters())
    assert cov["teams"] == 32, cov
    assert cov["players"] > 2500, cov  # full roster table, not just actives
    assert cov["active"] > 1500, cov


def test_rams_abbr_resolves_to_team_colors():
    # nflverse data uses "LA" for the Rams; the app's canonical key is
    # "LAR". The alias keeps Rams team colors on every card either way.
    from teams import colors

    assert colors.team_accent("LA") is not None
    assert colors.team_accent("LAR") is not None
    assert colors.team_accent("Los Angeles Rams") is not None
    assert colors.team_accent("LA") == colors.team_accent("LAR")


def test_player_form_summary_skill_positions():
    form = profiles.player_form_summary(_stats(), "Josh Allen", "QB", 2026)
    assert form and form["label"] == "Passing yards"
    assert form["games"] > 0 and form["season_avg"] > 0
    assert len(form["last5"]) <= 5


def test_player_form_summary_lineman_is_none():
    # No made-up form line for positions without a yardage stat.
    assert profiles.player_form_summary(_stats(), "Trent Brown", "OL",
                                        2026) is None


# ---------- (a) spotlight: View always shows something ----------

def _bio(name="Josh Allen"):
    return profiles.find_player(_rosters(), name)


def test_spotlight_renders_full_card():
    form = profiles.player_form_summary(_stats(), "Josh Allen", "QB", 2026)
    html = cards.player_spotlight_html(
        "Josh Allen", bio=_bio(), form=form, matchup="Next: vs KC · wk 6")
    assert "Josh Allen" in html and "tcard-name" in html
    assert "BUF" in html and "QB" in html
    assert "Passing yards/game this season" in html
    assert "Last 5 vs own average" in html
    assert "Next: vs KC" in html
    assert "jersey-badge" in html


def test_spotlight_unknown_player_is_honest():
    html = cards.player_spotlight_html("Dallas Defense", bio=None)
    assert "Dallas Defense" in html
    assert "Not on a current roster" in html
    assert "tcard-initials" in html  # initials fallback, no photo


def test_spotlight_no_form_line_for_linemen():
    html = cards.player_spotlight_html("Trent Brown",
                                       bio=profiles.find_player(
                                           _rosters(), "Trent Brown"),
                                       form=None)
    assert "Trent Brown" in html
    assert "game this season" not in html


def test_spotlight_escapes_markup():
    html = cards.player_spotlight_html('<script>alert("x")</script>',
                                       bio={"team": "<b>", "position": None,
                                            "jersey": None})
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ---------- (c) games strip ----------

def _syn_events():
    now = datetime.now(gsched.ET)
    return [
        {"name": "Buffalo Bills at Miami Dolphins",
         "starts_at": now.isoformat(), "round": "Week 6"},
        {"name": "Dallas Cowboys at New York Giants",
         "starts_at": (now + timedelta(days=3)).isoformat(),
         "round": "Week 6"},
        {"name": "Weird Event", "starts_at": None, "round": ""},
    ]


def test_parse_events_marks_today_and_sorts():
    games = gsched.parse_events(_syn_events())
    assert len(games) == 3
    assert games[0]["is_today"] is True
    assert games[0]["away_abbr"] == "BUF" and games[0]["home_abbr"] == "MIA"
    assert games[1]["is_today"] is False
    # Dateless/malformed rows sort last and never crash.
    assert games[2]["starts_at"] is None
    assert games[2]["away_abbr"] is None


def test_kickoff_label():
    assert gsched.kickoff_label(None) == "TBD"
    now = datetime.now(gsched.ET)
    assert "ET" in gsched.kickoff_label(now)


def test_game_row_today_badge_and_escape():
    games = gsched.parse_events(_syn_events())
    today = {**games[0], "kickoff": gsched.kickoff_label(games[0]["starts_at"])}
    future = {**games[1], "kickoff": gsched.kickoff_label(games[1]["starts_at"])}
    assert "TODAY" in cards.game_row_html(today)
    assert "TODAY" not in cards.game_row_html(future)
    evil = {**future, "away_abbr": "<img src=x>"}
    assert "<img src=x>" not in cards.game_row_html(evil)


def test_parse_events_empty_is_empty():
    assert gsched.parse_events([]) == []
    assert gsched.parse_events(None) == []


# ---------- (a) end-to-end: the View flow in the running app ----------

def test_view_flow_renders_spotlight_without_picks(monkeypatch):
    """AppTest: scan_player set, no +EV flags -> spotlight + honest note.

    This is the exact flow Tbandz hit: View on a news-trending name
    with no mispriced props. It must render the player card, never the
    generic dead-end.
    """
    monkeypatch.setenv("ODDS_API_KEY", "")
    monkeypatch.setenv("LUMIFY_API_KEY", "")
    from streamlit.testing.v1 import AppTest

    app_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
    at = AppTest.from_file(app_path, default_timeout=180)
    at.session_state["nav"] = "Scan"
    at.session_state["scan_player"] = "Erick All"
    at.session_state["scan_player_team"] = "CIN"
    at.run()
    assert not at.exception, f"dashboard raised: {at.exception}"
    md = " ".join(str(getattr(m, "value", "")) for m in at.markdown)
    assert "Erick All" in md, "spotlight card did not render for View"
    # The honest no-flags note renders via st.info (branded banner).
    info = " ".join(str(getattr(i, "value", "")) for i in at.info)
    assert "priced right" in info, "honest no-flags note missing"


def test_schedule_import_without_tzdata():
    # Learn-mode: Streamlit Cloud's image once shipped without the tz
    # database, so ZoneInfo("America/New_York") raised at import time
    # and the whole app died on startup ("Oh no. Error running app").
    # Importing games.schedule must NEVER raise, with or without tzdata.
    import zoneinfo

    class _NoTzdata:
        def __init__(self, *a, **k):
            raise zoneinfo.ZoneInfoNotFoundError("no tzdata here")

    import sys

    for m in [m for m in sys.modules if m == "games.schedule" or m.startswith("games.schedule.")]:
        del sys.modules[m]
    real = zoneinfo.ZoneInfo
    zoneinfo.ZoneInfo = _NoTzdata
    try:
        import games.schedule as g2

        assert g2.ET is not None
        evs = g2.parse_events([{"name": "Tampa Bay Buccaneers at Dallas Cowboys",
                                "starts_at": "2026-10-09T00:15:00Z"}])
        assert evs and evs[0]["away"] == "Tampa Bay Buccaneers"
        assert evs[0]["home"] == "Dallas Cowboys"
    finally:
        zoneinfo.ZoneInfo = real
        for m in [m for m in sys.modules if m == "games.schedule" or m.startswith("games.schedule.")]:
            del sys.modules[m]
