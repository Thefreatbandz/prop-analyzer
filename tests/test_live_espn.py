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
    finally:
        espn._get = real_get
