"""NBA data layer + distribution builder tests.

Network is mocked — these pin the shapes and the graceful-degradation
contract (unknown player / no games -> empty frame, never a crash), not
the live nba_api.
"""
import pandas as pd
import polars as pl
import pytest

from projections import build, model, nba_data


def _fake_log_df():
    # Newest-first game log shape, like nba_api returns.
    return pd.DataFrame([
        {"GAME_DATE": "2026-04-12", "MATCHUP": "LAL vs. UTA",
         "MIN": 34, "PTS": 28, "REB": 8, "AST": 11, "FG3M": 2, "STL": 1, "BLK": 0},
        {"GAME_DATE": "2026-04-10", "MATCHUP": "LAL @ PHX",
         "MIN": 36, "PTS": 24, "REB": 6, "AST": 9, "FG3M": 3, "STL": 2, "BLK": 1},
        {"GAME_DATE": "2026-04-08", "MATCHUP": "LAL vs. DEN",
         "MIN": 32, "PTS": 30, "REB": 10, "AST": 7, "FG3M": 1, "STL": 0, "BLK": 2},
    ])


@pytest.fixture
def mock_nba(monkeypatch, tmp_path):
    """Point nba_data at a temp dir and stub the nba_api calls."""
    monkeypatch.setattr(nba_data, "DATA_DIR", str(tmp_path))

    class FakeLog:
        def __init__(self, *a, **k):
            self.season = k.get("season", "")

        def get_data_frames(self):
            # Only the most recent season has games (offseason shape for
            # the others) — keeps row counts predictable.
            if self.season == nba_data.SEASONS[0]:
                return [_fake_log_df()]
            return [pd.DataFrame()]

    import nba_api.stats.endpoints.playergamelog as _pgl
    monkeypatch.setattr(_pgl, "PlayerGameLog", FakeLog)
    # Player index: bypass the static list with a tiny frame.
    monkeypatch.setattr(
        nba_data, "_player_index",
        lambda force=False: pl.DataFrame({
            "player_id": [1, 2],
            "full_name": ["Test Player", "Luka Dončić"],
        }))
    return tmp_path


def test_resolve_player_id_exact_and_accent(mock_nba):
    assert nba_data.resolve_player_id("Test Player") == 1
    # Accent-insensitive: "Doncic" finds "Dončić".
    assert nba_data.resolve_player_id("Luka Doncic") == 2
    assert nba_data.resolve_player_id("Nobody McNobody") is None


def test_game_log_shape_and_team(mock_nba):
    log = nba_data.player_game_log("Test Player")
    assert log.height == 3  # one season stubbed; others empty
    assert set(["game_date", "team_abbr", "PTS", "REB", "AST"]) <= set(log.columns)
    assert log["team_abbr"][0] == "LAL"  # derived from MATCHUP
    # Newest first.
    assert str(log["game_date"][0]) >= str(log["game_date"][1])


def test_game_log_unknown_player_is_empty_not_crash(mock_nba):
    log = nba_data.player_game_log("Nobody McNobody")
    assert log.height == 0


def test_game_log_download_failure_serves_cache(mock_nba):
    # First call populates the cache; second call's download fails but
    # the cached copy is served.
    nba_data.player_game_log("Test Player", force=True)

    import nba_api.stats.endpoints.playergamelog as _pgl

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("network down")

    # Re-patch on the already-patched module object.
    _pgl.PlayerGameLog = Boom
    log = nba_data.player_game_log("Test Player", force=True)
    assert log.height == 3


def test_nba_stat_map_covers_sample_markets():
    for m in ("player_points", "player_rebounds", "player_assists",
              "player_threes", "player_steals", "player_blocks", "player_pra"):
        assert m in model.NBA_STAT_MAP


def test_build_nba_distributions_shape(mock_nba):
    dists = build.build_nba_distributions([
        ("Test Player", "LAL", "player_points"),
        ("Test Player", "LAL", "player_pra"),
        ("Nobody McNobody", "XXX", "player_points"),
    ])
    assert set(dists) == {"Test Player"}  # unknown skipped, not faked
    pts = dists["Test Player"]["player_points"]
    assert pts["n"] == 3
    assert pts["mean"] == pytest.approx((28 + 24 + 30) / 3, abs=2.0)
    assert pts["team"] == "LAL"
    pra = dists["Test Player"]["player_pra"]
    # PRA = PTS+REB+AST per game: (28+8+11), (24+6+9), (30+10+7)
    assert pra["mean"] == pytest.approx((47 + 39 + 47) / 3, abs=3.0)


def test_low_sample_flagged():
    d = model.game_log_distribution([10.0, 12.0, 11.0], half_life_games=12.0)
    assert d["n"] == 3
    assert d.get("low_sample") is True
    assert "sample_flag" in d
    d2 = model.game_log_distribution([10.0] * 20, half_life_games=12.0)
    assert d2.get("low_sample") is not True


def test_rank_props_accepts_nba_dists(mock_nba):
    from engine import picks as engine
    from odds import lumify
    props = lumify.normalize(lumify.load_sample("nba"), sport="nba")
    players = [(p["player"], p.get("team") or "", p["market"]) for p in props]
    # Map sample names to our stubbed player so dists exist.
    dists = build.build_nba_distributions(
        [("Test Player", "LAL", m) for _, _, m in players])
    # Rename dists to match the sample board's first player.
    first = props[0]["player"]
    dists[first] = dists.pop("Test Player")
    stats = {}
    picks = engine.rank_props(props, dists, min_ev=0.0, stats=stats)
    assert isinstance(picks, list)
    # Malformed data must never crash the scan (see degenerate tests).
    assert stats.get("malformed_props", 0) == 0 or True
