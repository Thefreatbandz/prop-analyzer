"""Neon Edge card redesign: hit-rate computation, form dicts, and the
new card layout (PLAYER INSIGHT header, big gold line, hit-rate bar,
season/last-5 avg boxes). Gold-on-charcoal brand, all three sports."""

import pytest

from ui import cards


# ---------------- market_label ----------------

def test_market_label_all_sports():
    assert cards.market_label("player_threes") == "3-pointers made"
    assert cards.market_label("player_pass_yds") == "Passing yards"
    assert cards.market_label("player_hits") == "Hits"
    assert cards.market_label("player_so_pitcher") == "Strikeouts (pitcher)"
    assert cards.market_label("player_pra") == "Pts + Reb + Ast"


def test_market_label_unknown_never_blank():
    assert cards.market_label("player_something_new") == "Something New"
    assert cards.market_label(None) == "Prop"
    assert cards.market_label("") == "Prop"


def test_market_column_sport_aware():
    assert cards.market_column("player_threes", "nba") == "FG3M"
    assert cards.market_column("player_pra", "nba") == "PRA"
    assert cards.market_column("player_hits", "mlb") == "H"
    assert cards.market_column("player_so_pitcher", "mlb") == "SO"
    assert cards.market_column("player_pass_yds", "nfl") == "passing_yards"
    assert cards.market_column("player_pass_yds") == "passing_yards"  # default
    assert cards.market_column("bogus", "nba") is None
    assert cards.mlb_log_kind("player_so_pitcher") == "pitcher"
    assert cards.mlb_log_kind("player_hits") == "batter"
    assert cards.mlb_log_kind("player_points") == ""


# ---------------- hit_stats (shared core) ----------------

def test_hit_stats_pushes_count_not_hits():
    hits, n = cards.hit_stats([10, 10, 5, None], 10, "over")
    assert (hits, n) == (0, 3)  # two pushes + one miss, None skipped


def test_hit_stats_under():
    hits, n = cards.hit_stats([3, 8, 5], 5.5, "under")
    assert (hits, n) == (2, 3)


# ---------------- trading_card_html: Neon Edge layout ----------------

def _pick(**kw):
    d = {"type": "prop", "player": "Anthony Edwards", "team": "MIN",
         "market": "player_threes", "label": "3PT",
         "side": "over", "book": "DraftKings", "line": 2.5,
         "price": -110, "ev_pct": 6.4, "fair_prob": 0.58,
         "sport": "nba"}
    d.update(kw)
    return d


def _form(**kw):
    d = {"hits": 7, "n": 10, "season_avg": 2.8, "last5_avg": 3.2,
         "values": [3, 2, 4, 1, 3, 2, 5, 2, 3, 4], "cold": None}
    d.update(kw)
    return d


def test_neon_card_has_insight_header_and_big_line():
    html = cards.trading_card_html(_pick(), form=_form(), sport="nba")
    assert "PLAYER INSIGHT" in html
    assert "3-pointers made" in html
    assert "neon-line" in html
    assert "2.5" in html
    assert "NBA" in html


def test_neon_card_hit_rate_bar_honest_counts():
    html = cards.trading_card_html(_pick(), form=_form(), sport="nba")
    assert "Last 10 hit rate" in html
    assert "7/10" in html
    assert "neon-track" in html and "neon-fill" in html


def test_neon_card_short_sample_labeled_honestly():
    html = cards.trading_card_html(_pick(), form=_form(hits=3, n=4),
                                   sport="nba")
    assert "Last 4 hit rate" in html  # not "Last 10"
    assert "3/4" in html


def test_neon_card_avg_boxes():
    html = cards.trading_card_html(_pick(), form=_form(), sport="nba")
    assert "Season avg." in html and "2.8" in html
    assert "Last 5 avg." in html and "3.2" in html


def test_neon_card_keeps_edge_and_book():
    html = cards.trading_card_html(_pick(), form=_form(), sport="nba")
    assert "+6.40%" in html and "ev-hero" in html
    assert "DraftKings" in html
    assert "58%" in html  # model prob


def test_neon_card_no_form_renders_clean():
    # Unknown market / no data: card renders, form section skipped.
    html = cards.trading_card_html(_pick(market="player_wat"), sport="nba")
    assert "PLAYER INSIGHT" in html
    assert "neon-hitbox" not in html
    assert "neon-avgs" not in html


def test_neon_card_cold_warning_shows():
    html = cards.trading_card_html(
        _pick(), form=_form(cold="Missed 4 of last 5 vs this line"), sport="nba")
    assert "Missed 4 of last 5 vs this line" in html


def test_neon_card_explore_affordance():
    html = cards.trading_card_html(_pick(), form=_form(), sport="nba")
    assert "Explore player trends" in html


def test_neon_card_fades_variant():
    p = _pick()
    p["ev_pct"] = -5.1
    html = cards.trading_card_html(p, form=_form(), sport="nba",
                                   negative=True)
    assert "ev-hero neg" in html


def test_neon_card_escapes():
    p = _pick(player='Evil <img src=x onerror=alert(1)>')
    html = cards.trading_card_html(p, form=_form(), sport="nba")
    assert "<img src=x" not in html


# ---------------- cross-sport headshots ----------------

def _fake_img(url, timeout):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 160, 90)).save(buf, "JPEG")

    class R:
        content = buf.getvalue()
        headers = {"content-type": "image/jpeg"}
    return R()


def test_nba_headshot_uses_league_cdn(tmp_path):
    from players import headshots as hs
    import players.headshots as hsm
    hsm._NBA_HEADSHOT_DIR = str(tmp_path / "nba")
    got = {}

    def fetch(url, timeout):
        got["url"] = url
        return _fake_img(url, timeout)

    out = hs.nba_headshot_b64("LeBron James", fetch=fetch)
    assert out and out.startswith("data:image/jpeg;base64,")
    assert "cdn.nba.com" in got["url"] and "2544" in got["url"]


def test_mlb_headshot_uses_league_cdn(tmp_path):
    from players import headshots as hs
    import players.headshots as hsm
    hsm._MLB_HEADSHOT_DIR = str(tmp_path / "mlb")
    got = {}

    def fetch(url, timeout):
        got["url"] = url
        return _fake_img(url, timeout)

    out = hs.mlb_headshot_b64("Aaron Judge", fetch=fetch)
    assert out and out.startswith("data:image/jpeg;base64,")
    assert "mlb.com" in got["url"] and "592450" in got["url"]


def test_photo_for_sport_unknown_player_is_none():
    from players import headshots as hs
    assert hs.photo_for_sport("Nobody McNobody", "nba") is None
    assert hs.photo_for_sport("Nobody McNobody", "mlb") is None


def test_photo_for_sport_dispatch():
    from players import headshots as hs
    # Unknown names -> None (initials fallback), never raises.
    assert hs.photo_for_sport("Xyz Qqq", "nfl", rosters_df=None) is None
