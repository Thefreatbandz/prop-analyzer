"""v2 feature tests — all on SYNTHETIC data (zero downloads, zero keys).

Covers: game-log windowing (5/10/15), season averages, team tendency
math, play-type categorization, the premium gate (on and off),
preseason availability inventory, ESPN payload parsing, and the injury
cross-check that wires news into the scan.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import polars as pl
import pytest

from compare import compare as cmp_mod
from news import espn as news_mod
from players import preseason as preseason_mod
from players import profiles
from tendencies import plays as tplays
from tendencies import team as tteam


# ---------- synthetic fixtures ----------
def _player_stats():
    # 20 REG games for "Test Player" across 2024-2025, one per week.
    rows = []
    for i in range(20):
        season, week = (2024, i + 1) if i < 10 else (2025, i - 9)
        rows.append(
            {
                "player_display_name": "Test Player",
                "season": season,
                "week": week,
                "season_type": "REG",
                "team": "BUF",
                "opponent_team": "MIA",
                "passing_yards": 250 + i * 5,
                "passing_tds": 2,
                "passing_interceptions": 1,
                "rushing_yards": 20,
                "receptions": 0,
                "targets": 0,
                "receiving_yards": 0,
            }
        )
    return pl.DataFrame(rows)


def _pbp():
    # 1st down: 3 runs, 1 pass. 2nd down: 1 run, 3 passes. 3rd: all pass.
    rows = []
    rid = 0
    plan = [(1, ["run"] * 3 + ["pass"]), (2, ["run"] + ["pass"] * 3),
            (3, ["pass"] * 4)]
    for down, types in plan:
        for pt in types:
            rid += 1
            rows.append(
                {
                    "game_id": "g1",
                    "posteam": "BUF",
                    "season": 2025,
                    "week": 5,
                    "down": down,
                    "ydstogo": 10,
                    "yardline_100": 50,
                    "play_type": pt,
                    "shotgun": 1 if pt == "pass" else 0,
                    "no_huddle": 0,
                    "run_location": "MIDDLE" if pt == "run" else None,
                    "run_gap": None,
                    "air_yards": 12 if pt == "pass" else None,
                    "yards_after_catch": 4 if pt == "pass" else None,
                    "receiver_player_name": "Test Player" if pt == "pass" else None,
                    "rusher_player_name": "Test Player" if pt == "run" else None,
                    "passer_player_name": "Test Player" if pt == "pass" else None,
                    "qb_scramble": 0,
                    "sack": 0,
                    "game_seconds_remaining": 3600 - rid * 35,
                }
            )
    return pl.DataFrame(rows)


# ---------- 1. game logs ----------
def test_game_log_windows():
    df = _player_stats()
    for n in (5, 10, 15):
        log = profiles.game_log(df, "Test Player", last_n=n)
        assert len(log) == n, f"expected {n} rows, got {len(log)}"
    # most recent first
    log = profiles.game_log(df, "Test Player", last_n=5)
    assert (log[0]["season"], log[0]["week"]) == (2025, 10)
    assert (log[-1]["season"], log[-1]["week"]) == (2025, 6)
    # stat columns present
    assert log[0]["passing_yards"] == 250 + 19 * 5


def test_game_log_bad_window():
    with pytest.raises(ValueError):
        profiles.game_log(_player_stats(), "Test Player", last_n=7)


def test_season_averages():
    avgs = profiles.season_averages(_player_stats(), "Test Player", 2025)
    assert avgs["games"] == 10
    # 2025 weeks: i=10..19 -> yards 300..345, mean 322.5
    assert avgs["passing_yards"] == 322.5
    assert avgs["passing_tds"] == 2.0
    assert profiles.season_averages(_player_stats(), "Nobody", 2025)["games"] == 0


# ---------- 2. team tendencies ----------
def test_run_pass_by_down():
    pbp = _pbp()
    splits = tteam.run_pass_splits(pbp, "BUF")
    assert splits["snaps"] == 12
    assert splits["by_down"]["1st"]["run_rate"] == pytest.approx(0.75, abs=0.002)
    assert splits["by_down"]["2nd"]["pass_rate"] == pytest.approx(0.75, abs=0.002)
    assert splits["by_down"]["3rd"]["pass_rate"] == pytest.approx(1.0, abs=0.002)
    assert splits["run_rate"] == pytest.approx(4 / 12, abs=0.002)


def test_formation_proxies_honest():
    pbp = _pbp()
    fp = tteam.formation_proxies(pbp, "BUF")
    assert fp["shotgun_rate"] == pytest.approx(8 / 12, abs=0.002)  # all passes shotgun
    assert fp["personnel_groupings"] is None  # not in free data
    assert "personnel" in fp["personnel_note"].lower()


def test_pace_math():
    pbp = _pbp()
    p = tteam.pace(pbp, "BUF")
    assert p["games"] == 1
    assert p["snaps_per_game"] == 12.0
    assert p["median_seconds_per_snap"] == pytest.approx(35.0)


# ---------- 3. most-used play types ----------
def test_play_type_categories():
    assert tplays._categorize({"play_type": "run", "run_location": "LEFT"}) == "Run — left"
    assert tplays._categorize({"play_type": "pass", "air_yards": 25}) == "Pass — deep (20+ yds)"
    assert tplays._categorize({"play_type": "pass", "air_yards": -2}) == "Pass — behind line (screen)"
    assert tplays._categorize({"play_type": "pass", "qb_scramble": 1}) == "QB scramble"


def test_most_used_ranking():
    pbp = _pbp()
    ranked = tplays.most_used_play_types(pbp, team="BUF", top_n=3)
    assert ranked[0]["play_type"] == "Pass — intermediate (10-19 yds)"
    assert ranked[0]["share"] == pytest.approx(8 / 12, abs=0.002)
    # The label is honest about what the free data can't do:
    assert "not charted in the free data" in tplays.HONEST_LABEL


# ---------- 4. premium gate ----------
def test_compare_locked_by_default(monkeypatch):
    import config
    monkeypatch.setattr(config, "PREMIUM_ENABLED", False)
    res = cmp_mod.compare_players("A", "B", {})
    assert res["locked"] is True
    assert isinstance(res["teaser"], list) and len(res["teaser"]) > 0


def test_compare_unlocked(monkeypatch):
    import config
    monkeypatch.setattr(config, "PREMIUM_ENABLED", True)
    ps = _player_stats()
    rosters = pl.DataFrame([{
        "full_name": "Test Player", "first_name": "Test", "last_name": "Player",
        "team": "BUF", "position": "QB", "depth_chart_position": "QB",
        "jersey_number": 17, "status": "Active", "status_description_abbr": None,
    }])
    ctx = {"rosters_df": rosters, "player_stats_df": ps,
           "distributions": {}, "prop_picks": [], "season": 2025, "week": 5}
    res = cmp_mod.compare_players("Test Player", "Test Player", ctx)
    assert res["locked"] is False
    assert len(res["players"]) == 2
    assert any(r["stat"] == "passing yards" for r in res["stat_rows"])


# ---------- 5. preseason inventory ----------
def test_preseason_inventory_honest():
    inv = preseason_mod.availability()
    assert inv["preseason_play_by_play"]["available"] is False
    assert inv["preseason_player_stats"]["available"] is False
    assert inv["rosters"]["available"] is True
    assert len(preseason_mod.summary_lines()) == len(inv)


# ---------- 6. news ----------
def test_espn_parse():
    payload = {"articles": [
        {"headline": "Bills win big", "description": "Josh Allen throws 4 TDs",
         "links": {"web": {"href": "https://espn.com/1"}}, "published": "2026-10-07"},
        {"headline": "Weather report", "description": "Rain in Buffalo",
         "links": {"web": {"href": "https://espn.com/2"}}, "published": "2026-10-07"},
    ]}
    arts = news_mod._parse_articles(payload)
    assert len(arts) == 2
    assert arts[0]["link"] == "https://espn.com/1"
    hits = news_mod.news_for_player(arts, "Josh Allen")
    assert len(hits) == 1 and hits[0]["headline"] == "Bills win big"


def test_injury_report_and_enrich():
    inj = pl.DataFrame([
        {"full_name": "Test Player", "team": "BUF", "position": "QB",
         "season": 2025, "week": 5, "report_status": "Out",
         "report_details": "ankle", "injury": None,
         "last_name": "Player"},
        {"full_name": "Healthy Guy", "team": "BUF", "position": "WR",
         "season": 2025, "week": 5, "report_status": "Questionable",
         "report_details": "", "injury": None, "last_name": "Guy"},
    ])
    rep = news_mod.get_injury_report(inj, 2025, 5)
    assert rep[0]["status"] == "Out"  # Out sorts first
    picks = [{"player": "Test Player", "team": "BUF", "label": "x"}]
    out = news_mod.enrich_injury_flags(picks, inj, 2025, 5)
    assert "Out" in out[0]["injury_flag"]
    # already-flagged picks are left alone
    picks2 = [{"player": "Test Player", "injury_flag": "model knew"}]
    assert news_mod.enrich_injury_flags(picks2, inj, 2025, 5)[0]["injury_flag"] == "model knew"


# ---------- 8. real-data format guards ----------
def test_pbp_name_forms():
    # PBP writes "J.Allen"; box scores write "Josh Allen". usage_splits
    # must match both (regression: silently returned 0 rushes).
    from tendencies import player as tplayer
    assert tplayer._name_forms("Josh Allen") == ["Josh Allen", "J.Allen"]
    assert tplayer._name_forms("Ja'Marr Chase") == ["Ja'Marr Chase", "J.Chase"]


def test_usage_splits_pbp_names():
    import polars as pl
    from tendencies import player as tplayer
    pbp = pl.DataFrame([
        {"season": 2025, "posteam": "BUF", "play_type": "run",
         "rusher_player_name": "J.Allen", "receiver_player_name": None,
         "run_location": "left", "air_yards": None},
        {"season": 2025, "posteam": "BUF", "play_type": "run",
         "rusher_player_name": "J.Allen", "receiver_player_name": None,
         "run_location": "right", "air_yards": None},
        {"season": 2025, "posteam": "BUF", "play_type": "pass",
         "rusher_player_name": None, "receiver_player_name": "J.Allen",
         "run_location": None, "air_yards": 25},
    ])
    us = tplayer.usage_splits(pbp, pl.DataFrame(), "Josh Allen", "BUF", 2025)
    assert us["rushes"] == 2
    assert us["rush_left_share"] == 0.5 and us["rush_right_share"] == 0.5
    assert us["target_share"] == 1.0
    assert us["deep_target_rate"] == 1.0
def test_get_teams_filters_historical():
    teams = pl.DataFrame([
        {"team_abbr": "BUF", "team_name": "Buffalo Bills", "team_nick": "Bills",
         "team_conf": "AFC", "team_division": "East"},
        {"team_abbr": "OAK", "team_name": "Oakland Raiders", "team_nick": "Raiders",
         "team_conf": "AFC", "team_division": "West"},
    ])
    rosters = pl.DataFrame([{"team": "BUF", "full_name": "A", "first_name": "A",
                             "last_name": "A", "position": "QB",
                             "depth_chart_position": "QB", "jersey_number": 1,
                             "status": "Active"}])
    got = profiles.get_teams(teams, rosters)
    assert [t["abbr"] for t in got] == ["BUF"]


def test_upcoming_matchup():
    sched = pl.DataFrame([
        {"season": 2025, "week": 6, "home_team": "BUF", "away_team": "MIA",
         "gameday": "2025-10-12"},
        {"season": 2025, "week": 4, "home_team": "NE", "away_team": "BUF",
         "gameday": "2025-09-28"},
    ])
    mu = profiles.upcoming_matchup(sched, "BUF", 2025, 5)
    assert mu["opponent"] == "MIA" and mu["home_away"] == "vs"
    assert profiles.upcoming_matchup(sched, "BUF", 2025, 7) is None
