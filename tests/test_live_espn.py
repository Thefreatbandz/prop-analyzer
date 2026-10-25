"""Live ESPN data tests — parsing and stat extraction on synthetic
payloads. No network: the fetchers are thin wrappers around requests,
so we test everything below the HTTP layer.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live import espn


def test_norm_name():
    assert espn.norm_name("Ja'Marr Chase") == "jamarrchase"
    assert espn.norm_name("Drake Maye") == "drakemaye"
    assert espn.norm_name("A.J. Brown") == "ajbrown"


def _boxscore():
    # Mirrors the real ESPN summary shape: passing combines C/ATT.
    return {
        "NE": {
            "passing": {
                "drakemaye": {"name": "Drake Maye",
                              "stats": ["6/7", "85", "12.1", "1", "0",
                                        "0-0", "156.8"]},
            },
            "rushing": {
                "drakemaye": {"name": "Drake Maye",
                              "stats": ["2", "18", "9.0", "0", "10"]},
            },
        },
        "CIN": {
            "receiving": {
                "jamarrchase": {"name": "Ja'Marr Chase",
                                "stats": ["2", "8", "4.0", "0", "6", "4"]},
            },
        },
    }


def test_player_live_stat():
    bs = _boxscore()
    assert espn.player_live_stat(bs, "Drake Maye", "player_pass_yds") == 85.0
    assert espn.player_live_stat(bs, "Drake Maye", "player_rush_yds") == 18.0
    assert espn.player_live_stat(bs, "Ja'Marr Chase",
                                 "player_rec_yds") == 8.0
    assert espn.player_live_stat(bs, "Ja'Marr Chase",
                                 "player_receptions") == 2.0
    # Unmapped market -> None, never a crash.
    assert espn.player_live_stat(bs, "Drake Maye", "player_first_td") is None
    # Unknown player -> None.
    assert espn.player_live_stat(bs, "Tom Brady", "player_pass_yds") is None
    # Punctuation-blind lookup.
    assert espn.player_live_stat(bs, "Jamarr Chase",
                                 "player_rec_yds") == 8.0


def test_find_player_game():
    sb = [
        {"id": "1", "live": True, "away": "LV", "home": "NE"},
        {"id": "2", "live": True, "away": "CIN", "home": "MIA"},
        {"id": "3", "live": False, "away": "DEN", "home": "LAC"},
    ]
    bss = {"1": _boxscore(), "2": {}, "3": {}}
    g = espn.find_player_game(sb, bss, "Drake Maye")
    assert g is not None and g["id"] == "1"
    assert espn.find_player_game(sb, bss, "Tom Brady") is None


def test_get_scoreboard_parses():
    sample = {
        "events": [{
            "id": "401872986",
            "competitions": [{
                "status": {"type": {"state": "in",
                                    "shortDetail": "2:34 - 1st"}},
                "competitors": [
                    {"homeAway": "away",
                     "score": "7",
                     "team": {"abbreviation": "LV"}},
                    {"homeAway": "home",
                     "score": "7",
                     "team": {"abbreviation": "NE"}},
                ],
            }],
        }],
    }
    real_get = espn._get
    espn._get = lambda url, params=None, timeout=20: sample  # noqa: E731
    try:
        games = espn.get_scoreboard()
    finally:
        espn._get = real_get
    assert len(games) == 1
    g = games[0]
    assert (g["away"], g["home"]) == ("LV", "NE")
    assert (g["away_score"], g["home_score"]) == ("7", "7")
    assert g["live"] is True and g["status"] == "live"
    assert g["detail"] == "2:34 - 1st"


def test_get_scoreboard_failure_is_empty():
    real_get = espn._get

    def boom(url, params=None, timeout=20):
        raise ConnectionError("down")
    espn._get = boom
    try:
        assert espn.get_scoreboard() == []
        assert espn.get_boxscore("123") == {}
        assert espn.get_play_by_play("123") == []
    finally:
        espn._get = real_get


def test_get_scoreboard_records():
    sample = {
        "events": [{
            "id": "401873020",
            "competitions": [{
                "status": {"type": {"state": "in",
                                    "shortDetail": "15:00 - 2nd"}},
                "competitors": [
                    {"homeAway": "away",
                     "score": "7",
                     "records": [{"type": "total", "summary": "4-2"},
                                 {"type": "home", "summary": "2-1"}],
                     "team": {"abbreviation": "GB"}},
                    {"homeAway": "home",
                     "score": "7",
                     "records": [{"type": "total", "summary": "3-2"}],
                     "team": {"abbreviation": "DET"}},
                ],
            }],
        }],
    }
    real_get = espn._get
    espn._get = lambda url, params=None, timeout=20: sample  # noqa: E731
    try:
        games = espn.get_scoreboard()
    finally:
        espn._get = real_get
    assert len(games) == 1
    assert games[0]["away_record"] == "4-2"
    assert games[0]["home_record"] == "3-2"


def test_get_play_by_play_parses():
    sample = {
        "drives": {
            "previous": [{
                "plays": [
                    {"type": {"text": "Pass Reception"},
                     "text": "J.Goff pass short left to A.St. Brown "
                             "for 8 yards (J.Jacobs).",
                     "period": {"number": 1},
                     "clock": {"displayValue": "12:00"},
                     "awayScore": "0", "homeScore": "0",
                     "scoringPlay": False},
                    {"type": {"text": "Rush"},
                     "text": "J.Gibbs right tackle for 12 yards.",
                     "period": {"number": 1},
                     "clock": {"displayValue": "11:20"},
                     "awayScore": "0", "homeScore": "0",
                     "scoringPlay": False},
                ],
            }],
            "current": {
                "plays": [
                    {"type": {"text": "Pass Touchdown"},
                     "text": "J.Goff pass deep to A.St. Brown "
                             "for 30 yards, TOUCHDOWN.",
                     "period": {"number": 1},
                     "clock": {"displayValue": "10:05"},
                     "awayScore": "0", "homeScore": "7",
                     "scoringPlay": True},
                ],
            },
        },
    }
    real_get = espn._get
    espn._get = lambda url, params=None, timeout=20: sample  # noqa: E731
    try:
        plays = espn.get_play_by_play("401873020")
    finally:
        espn._get = real_get
    # Most recent first: current-drive TD, then the two previous plays.
    assert len(plays) == 3
    assert plays[0]["scoring"] is True
    assert "TOUCHDOWN" in plays[0]["text"]
    assert plays[0]["period"] == 1 and plays[0]["clock"] == "10:05"
    assert plays[0]["home_score"] == "7"
    assert plays[1]["type"] == "Rush"
    assert "Gibbs" in plays[1]["text"]
    assert plays[2]["type"] == "Pass Reception"
    assert "Goff" in plays[2]["text"]
