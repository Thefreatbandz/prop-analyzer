"""Trading-card pick cards + "what's not working" signals.

Covers players/headshots.py (cached thumbnails, jersey lookup,
fallbacks), ui/cards.py cold_line() + trading_card_html(), and
engine rank_fades(). All on synthetic data — no network, no Streamlit.
"""
import io
import os
import sys

import polars as pl
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import picks as engine
from players import headshots
from ui import cards


def _rosters():
    return pl.DataFrame([
        {"full_name": "Josh Allen", "gsis_id": "00-0034857",
         "jersey_number": 17, "position": "QB",
         "headshot_url": "https://cdn.example.com/allen.jpg"},
        {"full_name": "No Photo Guy", "gsis_id": "00-0099999",
         "jersey_number": 99, "position": "DT", "headshot_url": None},
        {"full_name": "Weird <b>Name</b>", "gsis_id": "00-0077777",
         "jersey_number": None, "position": "WR",
         "headshot_url": "https://cdn.example.com/weird.jpg"},
    ])


def _png_bytes(color=(200, 30, 30), size=(400, 300)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class _Resp:
    def __init__(self, content, ctype="image/png"):
        self.content = content
        self.headers = {"content-type": ctype}


# ---------------- headshots ----------------

def test_jersey_number_lookup(tmp_path):
    df = _rosters()
    assert headshots.jersey_number("Josh Allen", df) == "17"
    assert headshots.jersey_number("Nobody Here", df) is None
    assert headshots.jersey_number("Weird <b>Name</b>", df) is None
    assert headshots.position_abbr("Josh Allen", df) == "QB"


def test_headshot_download_caches_thumbnail(tmp_path):
    df = _rosters()
    calls = []

    def fake_fetch(url, timeout):
        calls.append(url)
        return _Resp(_png_bytes())

    p1 = headshots.headshot_path("Josh Allen", df, fetch=fake_fetch,
                                 cache_dir=str(tmp_path))
    assert p1 and os.path.exists(p1)
    # Thumbnail is a small JPEG, not the 400x300 source.
    from PIL import Image

    img = Image.open(p1)
    assert img.size == (headshots.THUMB_PX, headshots.THUMB_PX)
    assert img.format == "JPEG"
    assert os.path.getsize(p1) < 20000
    # Second call hits the cache — no second download.
    p2 = headshots.headshot_path("Josh Allen", df, fetch=fake_fetch,
                                 cache_dir=str(tmp_path))
    assert p2 == p1 and len(calls) == 1


def test_headshot_missing_url_returns_none_no_fetch(tmp_path):
    df = _rosters()
    calls = []
    out = headshots.headshot_path("No Photo Guy", df,
                                  fetch=lambda u, t: calls.append(u) or _Resp(b""),
                                  cache_dir=str(tmp_path))
    assert out is None and calls == []


def test_headshot_failed_download_marks_miss(tmp_path):
    df = _rosters()
    calls = []

    def bad_fetch(url, timeout):
        calls.append(url)
        raise ConnectionError("down")

    out = headshots.headshot_path("Josh Allen", df, fetch=bad_fetch,
                                  cache_dir=str(tmp_path))
    assert out is None
    # Miss marker: the second call must not re-hit the network.
    out2 = headshots.headshot_path("Josh Allen", df, fetch=bad_fetch,
                                   cache_dir=str(tmp_path))
    assert out2 is None and len(calls) == 1


def test_headshot_rejects_non_image(tmp_path):
    df = _rosters()
    out = headshots.headshot_path(
        "Josh Allen", df,
        fetch=lambda u, t: _Resp(b"<html>nope</html>", "text/html"),
        cache_dir=str(tmp_path))
    assert out is None


def test_headshot_rejects_oversize(tmp_path):
    df = _rosters()
    out = headshots.headshot_path(
        "Josh Allen", df,
        fetch=lambda u, t: _Resp(b"x" * (headshots.MAX_BYTES + 1)),
        cache_dir=str(tmp_path))
    assert out is None


def test_safe_id_cannot_traverse(tmp_path):
    df = pl.DataFrame([
        {"full_name": "../../evil", "gsis_id": None, "jersey_number": 1,
         "position": "QB", "headshot_url": "https://cdn.example.com/e.jpg"},
    ])
    p = headshots.headshot_path("../../evil", df,
                                fetch=lambda u, t: _Resp(_png_bytes()),
                                cache_dir=str(tmp_path))
    assert p is not None
    # The file really lives inside the cache dir — no escape.
    assert os.path.dirname(os.path.abspath(p)) == os.path.abspath(str(tmp_path))
    assert ".." not in os.path.basename(p)


def test_cache_evicts_lru(tmp_path):
    df = _rosters()
    # Shrink the cap for the test via monkeypatch.
    import players.headshots as hs

    old = hs.MAX_CACHED
    hs.MAX_CACHED = 2
    try:
        names = ["Josh Allen", "No Photo Guy", "Weird <b>Name</b>"]
        urls = {n: f"https://cdn.example.com/{i}.jpg" for i, n in enumerate(names)}
        rows = [
            {"full_name": n, "gsis_id": f"00-000000{i}", "jersey_number": i,
             "position": "QB", "headshot_url": urls[n]}
            for i, n in enumerate(names)
        ]
        df2 = pl.DataFrame(rows)
        for n in names:
            hs.headshot_path(n, df2, fetch=lambda u, t: _Resp(_png_bytes()),
                             cache_dir=str(tmp_path))
        jpgs = [f for f in os.listdir(str(tmp_path)) if f.endswith(".jpg")]
        assert len(jpgs) <= 2
    finally:
        hs.MAX_CACHED = old


def test_headshot_b64_embeds_data_uri(tmp_path):
    df = _rosters()
    uri = headshots.headshot_b64(
        "Josh Allen", df, fetch=lambda u, t: _Resp(_png_bytes()),
        cache_dir=str(tmp_path))
    assert uri.startswith("data:image/jpeg;base64,")
    assert headshots.headshot_b64("No Photo Guy", df,
                                  cache_dir=str(tmp_path)) is None


def test_initials_fallback():
    assert headshots.initials("Josh Allen") == "JA"
    assert headshots.initials("Madonna") == "M"
    assert headshots.initials("") == "?"


# ---------------- cold_line ----------------

def test_cold_line_miss_streak():
    # Last three all missed 267.5 over -> streak wins.
    got = cards.cold_line([300, 310, 200, 210, 220], 267.5, "over")
    assert got == "Trending down — missed 3 straight vs this line"


def test_cold_line_cold_rate():
    # 2 of 5 hit (40%) with no 3-streak -> rate line.
    got = cards.cold_line([300, 200, 310, 210, 220], 267.5, "over")
    assert got == "Missed 3 of last 5 vs this line"


def test_cold_line_hot_is_none():
    assert cards.cold_line([300, 310, 320, 290, 300], 267.5, "over") is None


def test_cold_line_needs_min_games():
    assert cards.cold_line([200, 210], 267.5, "over") is None
    assert cards.cold_line([], 267.5, "over") is None


def test_cold_line_under_side():
    # Under 267.5: 300/310/320 are misses -> cold.
    got = cards.cold_line([300, 310, 320, 200, 210], 267.5, "under")
    assert got is not None and "Missed" in got


# ---------------- rank_fades ----------------

def _board():
    return [
        {"player": "Cold QB", "team": "BUF", "market": "player_pass_yds",
         "label": "Pass Yds",
         "books": [{"book": "b1", "line": 250.5, "over": -110, "under": -110}]},
        {"player": "Hot QB", "team": "KC", "market": "player_pass_yds",
         "label": "Pass Yds",
         "books": [{"book": "b1", "line": 250.5, "over": -110, "under": -110}]},
    ]


def _dists():
    # Cold QB projects way OVER the line -> the UNDER is a terrible bet
    # (fair prob ~5%, book pays -110) -> strong fade.
    # Hot QB projects way UNDER the line -> the OVER is the fade.
    return {
        "Cold QB": {"player_pass_yds": {"mean": 300.0, "std": 25.0, "n": 10}},
        "Hot QB": {"player_pass_yds": {"mean": 200.0, "std": 25.0, "n": 10}},
    }


def test_rank_fades_finds_negative_ev_worst_first():
    fades = engine.rank_fades(_board(), _dists(), sims=2000)
    assert len(fades) == 2
    assert all(f["ev_pct"] <= -2.0 for f in fades)
    evs = [f["ev_pct"] for f in fades]
    assert evs == sorted(evs)  # most negative first
    # The +EV sides must NOT appear as fades.
    assert {f["side"] for f in fades} == {"under", "over"}
    by_player = {f["player"]: f["side"] for f in fades}
    assert by_player == {"Cold QB": "under", "Hot QB": "over"}


def test_rank_fades_threshold_and_cap():
    fades = engine.rank_fades(_board(), _dists(), max_ev=-0.99, sims=2000)
    assert fades == []  # nothing is worse than -99%
    fades = engine.rank_fades(_board(), _dists(), top_n=1, sims=2000)
    assert len(fades) == 1


def test_rank_fades_skips_do_not_bet():
    dists = {"Cold QB": {"player_pass_yds": {"mean": 300.0, "std": 25.0,
                                             "n": 10, "do_not_bet": True}},
             "Hot QB": _dists()["Hot QB"]}
    fades = engine.rank_fades(_board(), dists, sims=2000)
    assert [f["player"] for f in fades] == ["Hot QB"]


# ---------------- trading_card_html ----------------

def _pick():
    return {"type": "prop", "player": "Josh Allen", "team": "BUF",
            "market": "player_pass_yds", "label": "Pass Yds",
            "side": "over", "book": "DraftKings", "line": 267.5,
            "price": -110, "ev_pct": 4.2}


def test_trading_card_has_photo_jersey_cold():
    html = cards.trading_card_html(
        _pick(), matchup_html=" · vs KC · wk 6",
        bars="<div class='mini-bars'></div>",
        hit_html="<div class='pc-hit'></div>",
        cold_html="Cold: Missed 4 of last 5 vs this line",
        photo_b64="data:image/jpeg;base64,AAA", jersey="17", position="QB")
    assert "data:image/jpeg;base64,AAA" in html
    assert "jersey-badge" in html and ">17<" in html
    assert "Cold: Missed 4 of last 5 vs this line" in html
    assert "+4.20%" in html and "ev-hero" in html
    assert "tcard-pos" in html and "QB" in html


def test_trading_card_fades_variant_is_red():
    p = _pick()
    p["ev_pct"] = -6.35
    html = cards.trading_card_html(p, negative=True)
    assert "ev-hero neg" in html
    assert "-6.35%" in html


def test_trading_card_initials_fallback_no_photo():
    html = cards.trading_card_html(_pick(), jersey="17")
    assert "tcard-initials" in html
    assert ">JA<" in html  # Josh Allen's monogram


def test_trading_card_escapes_player_supplied_strings():
    p = _pick()
    p["player"] = 'Evil <img src=x onerror=alert(1)>'
    p["book"] = 'Book<script>alert(2)</script>'
    html = cards.trading_card_html(
        p, jersey='<b>99</b>', cold_html='Cold: <i>bad</i>')
    assert "<img src=x" not in html
    assert "<script>" not in html
    assert "&lt;img" in html and "&lt;script&gt;" in html
    assert "&lt;b&gt;99&lt;/b&gt;" in html


# ---------------- team colors + model prob (v5 refinements) ----------------

def test_team_colors_cover_all_32():
    from teams import colors as tc

    assert len(tc.TEAM_COLORS) == 32
    assert len(tc.NAME_TO_ABBR) == 32
    import re

    for abbr, (p1, p2) in tc.TEAM_COLORS.items():
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", p1), abbr
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", p2), abbr
    assert set(tc.NAME_TO_ABBR.values()) == set(tc.TEAM_COLORS)


def test_team_accent_full_name_and_abbr():
    from teams import colors as tc

    assert tc.team_accent("Buffalo Bills") == ("#00338D", "#C60C30")
    assert tc.team_accent("BUF") == ("#00338D", "#C60C30")
    assert tc.team_accent("buf") == ("#00338D", "#C60C30")
    assert tc.team_accent("Springfield Atoms") is None
    assert tc.team_accent(None) is None
    assert tc.team_accent("") is None


def test_team_accent_dark_primary_falls_to_secondary():
    from teams import colors as tc

    # Raiders primary is black — invisible on charcoal, so the accent
    # must be the silver secondary.
    accent, tint = tc.team_accent("LV")
    assert accent == "#A5ACAF"
    assert tint == "#A5ACAF"


def test_badge_text_color_contrast():
    from teams import colors as tc

    assert tc.badge_text_color("#FFB612") == "#141416"  # bright gold -> dark text
    assert tc.badge_text_color("#0B162A") == "#FFFFFF"  # dark navy -> white text


def test_stable_seed_deterministic():
    from projections.montecarlo import stable_seed

    a = stable_seed("Josh Allen", "player_pass_yds", "over", 267.5)
    assert stable_seed("Josh Allen", "player_pass_yds", "over", 267.5) == a
    assert stable_seed("Josh Allen", "player_pass_yds", "over", 268.5) != a
    assert stable_seed("Josh Allen", "player_pass_yds", "under", 267.5) != a


def test_builder_leg_matches_scan_prob():
    # The card's MODEL PROB and the builder's per-leg fair P must be
    # the same number for the same player/market/side/line.
    from builder import legs as blegs

    board = [{"player": "A", "team": "BUF", "market": "player_pass_yds",
              "label": "Pass Yds",
              "books": [{"book": "b1", "line": 250.5,
                         "over": -110, "under": -110}]}]
    dists = {"A": {"player_pass_yds": {"mean": 280.0, "std": 30.0, "n": 10}}}
    picks = engine.rank_props(board, dists, min_ev=0.0, sims=5000)
    over_pick = next(p for p in picks if p["side"] == "over")
    leg = blegs.price_leg("A", "player_pass_yds", "over", 250.5, dists,
                          sims=5000)
    assert leg["fair_p"] == over_pick["fair_prob"]


def _pick_with_prob():
    p = {"type": "prop", "player": "Josh Allen", "team": "Buffalo Bills",
         "market": "player_pass_yds", "label": "Pass Yds",
         "side": "over", "book": "DraftKings", "line": 267.5,
         "price": -110, "ev_pct": 4.2, "fair_prob": 0.68}
    return p


def test_trading_card_shows_model_prob():
    html = cards.trading_card_html(_pick_with_prob())
    assert "MODEL PROB" in html
    assert "68%" in html


def test_trading_card_no_prob_when_missing():
    p = _pick_with_prob()
    del p["fair_prob"]
    assert "MODEL PROB" not in cards.trading_card_html(p)


def test_trading_card_team_accent_styles():
    html = cards.trading_card_html(_pick_with_prob(), jersey="17")
    # Bills royal blue border + glow; red tint wash.
    assert "border-color:#00338D" in html
    assert "box-shadow:0 0 16px #00338D30" in html
    assert "#C60C301A" in html
    # Jersey badge in team accent with readable text.
    assert "background:#00338D" in html


def test_trading_card_unknown_team_falls_back_to_gold():
    p = _pick_with_prob()
    p["team"] = "Springfield Atoms"
    html = cards.trading_card_html(p, jersey="17")
    assert "border-color:" not in html
    assert "jersey-badge" in html  # badge still renders, default CSS


def test_trading_card_edge_line_explains_the_edge():
    html = cards.trading_card_html(_pick_with_prob())
    # Beginner wording: "68 in 100", not "implied probability".
    assert "pc-edge-line" in html
    assert "our model: 68% in 100" in html
    # -110 implies 52.38% -> "52%".
    assert "book\u2019s 52% in 100" in html
    assert "That gap is the edge." in html


def test_trading_card_edge_line_fade_copy():
    p = _pick_with_prob()
    p["ev_pct"] = -27.70
    html = cards.trading_card_html(p, negative=True)
    assert "No edge here \u2014 that\u2019s why it\u2019s a fade." in html


def test_trading_card_edge_line_absent_without_prob():
    p = _pick_with_prob()
    del p["fair_prob"]
    assert "pc-edge-line" not in cards.trading_card_html(p)


def test_trading_card_edge_explainer_beginner_copy():
    html = cards.trading_card_html(_pick_with_prob())
    assert "New to edge? What this means" in html
    assert "times out of 100" in html
    assert "+EV" in html
    # Zero jargon: no "implied probability" anywhere in the explainer.
    assert "implied probability" not in html


def test_trading_card_edge_explainer_fade_copy():
    p = _pick_with_prob()
    p["ev_pct"] = -27.70
    html = cards.trading_card_html(p, negative=True)
    assert "a fade, not a pick" in html


def test_trading_card_edge_explainer_absent_without_prob():
    p = _pick_with_prob()
    del p["fair_prob"]
    assert "edge-why" not in cards.trading_card_html(p)


def test_edge_explainer_sharp_source_mentions_pinnacle():
    p = _pick_with_prob()
    html = cards.edge_explainer_html(p, source="sharp")
    assert "Pinnacle" in html
    assert "Our model" not in html


def test_edge_explainer_never_leaks_markup():
    p = _pick_with_prob()
    p["player"] = "<script>alert(1)</script>"
    html = cards.trading_card_html(p)
    assert "<script>" not in html
    assert "edge-why" in html  # explainer still renders (numbers only)


def test_dev_mode_gates_key_status():
    # The key-status block must only render for devs. The contract:
    # DEV_MODE is driven by ?dev=1 or DEV_MODE=1, and the key NAMES
    # (the markdown loop) only render inside that gate. key_status()
    # itself may run for the public mode label — booleans, not names.
    src = open("app.py").read()
    assert 'st.query_params.get("dev"' in src
    assert 'os.environ.get("DEV_MODE")' in src
    gate_start = src.index("if DEV_MODE:")
    gate = src[gate_start:gate_start + 700]
    assert "for k, v in keys.items():" in gate
    before_gate = src[:gate_start]
    # The key-name render loop appears exactly once: inside the gate.
    assert before_gate.count("for k, v in keys.items():") == 0
    # No key names leak into user-facing feed notes.
    from odds import the_odds_api
    _, note = the_odds_api.get_moneylines_strict()
    assert "ODDS_API_KEY" not in (note or "")
