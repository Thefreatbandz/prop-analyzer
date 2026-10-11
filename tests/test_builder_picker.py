"""Tests for the PrizePicks-style builder picker (builder/picker.py)
and the player tile renderer (ui/cards.player_tile_html).

Pure logic — no Streamlit needed. The picker only surfaces players
from the board (never invents them) and only offers markets the model
can price.
"""
from builder import picker


def _board():
    return [
        {"player": "Josh Allen", "team": "BUF", "market": "player_pass_yds",
         "label": "Passing yards",
         "books": [{"book": "dk", "line": 267.5, "over": -110, "under": -110},
                   {"book": "fd", "line": 268.5, "over": -114, "under": -114}]},
        {"player": "Josh Allen", "team": "BUF", "market": "player_pass_tds",
         "label": "Passing TDs",
         "books": [{"book": "dk", "line": 1.5, "over": -110, "under": -110}]},
        # Same market twice (two books as separate rows) -> one entry.
        {"player": "Josh Allen", "team": "BUF", "market": "player_pass_yds",
         "label": "Passing yards",
         "books": [{"book": "mgm", "line": 267.5, "over": -110, "under": -110}]},
        {"player": "James Cook", "team": "BUF", "market": "player_rush_yds",
         "label": "Rushing yards",
         "books": [{"book": "dk", "line": 64.5, "over": -110, "under": -110}]},
        # No priced books -> dropped entirely.
        {"player": "Ghost Player", "team": "BUF", "market": "player_pass_yds",
         "label": "Passing yards", "books": []},
        {"player": "No Line Guy", "team": "BUF", "market": "player_rush_yds",
         "label": "Rushing yards",
         "books": [{"book": "dk", "line": None, "over": -110, "under": -110}]},
    ]


def test_board_players_groups_and_sorts():
    players = picker.board_players(_board())
    names = [p["player"] for p in players]
    # Sorted, ghost players dropped.
    assert names == ["James Cook", "Josh Allen"]
    allen = next(p for p in players if p["player"] == "Josh Allen")
    # Duplicate market rows collapse to one entry.
    assert [m["market"] for m in allen["markets"]] == [
        "player_pass_yds", "player_pass_tds"]
    assert allen["team"] == "BUF"


def test_board_players_empty_board():
    assert picker.board_players([]) == []
    assert picker.board_players(None) == []


def test_consensus_line_median():
    books = [{"line": 267.5}, {"line": 268.5}, {"line": 267.5}]
    assert picker.consensus_line(books) == 267.5
    assert picker.consensus_line([{"line": 10.0}, {"line": 20.0}]) == 15.0
    assert picker.consensus_line([]) is None
    assert picker.consensus_line([{"line": None}]) is None


def test_priceable_markets_only_model_priced():
    dists = {
        "Josh Allen": {
            "player_pass_yds": {"mean": 270.0, "std": 40.0, "n": 30},
            # pass_tds has NO dist -> not offered
        },
    }
    rows = picker.priceable_markets(_board(), "Josh Allen", dists)
    assert [r["market"] for r in rows] == ["player_pass_yds"]
    assert rows[0]["line"] == 268.0  # median of first row's 267.5, 268.5
    assert rows[0]["n_books"] == 2


def test_priceable_markets_unknown_player():
    assert picker.priceable_markets(_board(), "Nobody", {}) == []


def test_markets_for_sport():
    nfl = picker.markets_for_sport("nfl")
    assert "player_pass_yds" in nfl
    nba = picker.markets_for_sport("nba")
    assert "player_points" in nba and "player_pass_yds" not in nba
    mlb = picker.markets_for_sport("mlb")
    assert "player_hits" in mlb and "player_so_pitcher" in mlb
    # Unknown sport falls back to NFL.
    assert picker.markets_for_sport("xyz") == nfl


def test_market_label():
    assert picker.market_label("player_pass_yds") == "Passing yards"
    assert picker.market_label("player_points") == "Points"
    assert picker.market_label("player_hits") == "Hits"
    # Unknown key passes through (never crashes the UI).
    assert picker.market_label("something_weird") == "something_weird"


def test_slip_has():
    legs = [{"player": "Josh Allen", "market": "player_pass_yds"}]
    assert picker.slip_has(legs, "Josh Allen", "player_pass_yds")
    assert not picker.slip_has(legs, "Josh Allen", "player_rush_yds")
    assert not picker.slip_has(legs, "James Cook", "player_pass_yds")
    assert not picker.slip_has([], "Josh Allen", "player_pass_yds")


def test_price_leg_nba_market_key():
    # price_leg is market-key agnostic: an NBA dist prices fine.
    from builder import legs as blegs
    dists = {"Anthony Edwards": {
        "player_threes": {"mean": 2.8, "std": 1.4, "n": 60}}}
    leg = blegs.price_leg("Anthony Edwards", "player_threes", "over",
                          2.5, dists)
    assert leg is not None
    assert 0 < leg["fair_p"] < 1
    assert leg["player"] == "Anthony Edwards"


def test_player_tile_html_escapes():
    from ui import cards
    html = cards.player_tile_html(
        '<script>alert("x")</script>', team="BUF", position="QB",
        n_props=3, selected=True)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "3 props" in html


def test_player_tile_html_initials_fallback():
    from ui import cards
    html = cards.player_tile_html("Josh Allen", team="BUF")
    assert "JA" in html  # initials render when no photo
    assert "Josh Allen" in html


def test_tier_lines_targets():
    # mean 250, std 50: 85% line ~= 250 - 50*1.036 = 198.2 -> 198.0
    tiers = picker.tier_lines(250.0, 50.0)
    assert [t["tier"] for t in tiers] == ["Safe", "Standard", "Plus", "Lottery"]
    assert tiers[0]["line"] == 198.0
    assert tiers[0]["target_p"] == 0.85
    # Lines strictly increasing as probability drops.
    lines = [t["line"] for t in tiers]
    assert lines == sorted(lines)
    # All rounded to 0.5.
    assert all(l * 2 == int(l * 2) for l in lines)


def test_tier_lines_dedupe_tiny_std():
    # Near-zero std collapses tiers to one line — never show dupes.
    tiers = picker.tier_lines(100.0, 0.05)
    assert len(tiers) <= 1


def test_tier_lines_no_std():
    assert picker.tier_lines(100.0, 0.0) == []


def test_tier_legs_priced_honestly():
    # Each tier leg carries the Monte Carlo fair_p (not the target).
    dists = {"Drake Maye": {
        "player_pass_yds": {"mean": 235.3, "std": 64.0, "n": 34}}}
    legs = picker.tier_legs("Drake Maye", "player_pass_yds", dists)
    assert len(legs) == 4
    assert [l["tier"] for l in legs] == ["Safe", "Standard", "Plus", "Lottery"]
    # Fair probs decrease with the line and bracket the targets.
    ps = [l["fair_p"] for l in legs]
    assert ps == sorted(ps, reverse=True)
    assert ps[0] > 0.75  # safe tier is high-probability
    assert ps[-1] < 0.40  # lottery tier is low
    # Legs are valid price_leg output.
    assert all(l["player"] == "Drake Maye" for l in legs)
    assert all(l["side"] == "over" for l in legs)


def test_tier_legs_no_dist():
    assert picker.tier_legs("Nobody", "player_pass_yds", {}) == []
    dists = {"P": {"player_pass_yds": {"mean": 200, "std": 0, "n": 5}}}
    assert picker.tier_legs("P", "player_pass_yds", dists) == []


def test_risk_tiers_constant():
    names = [t for t, _ in picker.RISK_TIERS]
    assert names == ["Safe", "Standard", "Plus", "Lottery"]


def test_safe_tier_leg():
    dists = {"Drake Maye": {
        "player_pass_yds": {"mean": 235.3, "std": 64.0, "n": 34}}}
    leg = picker.safe_tier_leg("Drake Maye", "player_pass_yds", dists)
    assert leg is not None
    assert leg["tier"] == "Safe"
    assert leg["side"] == "over"
    assert leg["fair_p"] > 0.75
    # Matches the first tier_legs entry.
    full = picker.tier_legs("Drake Maye", "player_pass_yds", dists)
    assert leg["line"] == full[0]["line"]


def test_safe_tier_leg_no_dist():
    assert picker.safe_tier_leg("Nobody", "player_pass_yds", {}) is None


def test_safe_tier_leg_fast_sims():
    """The card path uses fewer sims (page loads render once per card,
    uncached); the line is identical, only the MC noise differs."""
    dists = {"Drake Maye": {
        "player_pass_yds": {"mean": 235.3, "std": 64.0, "n": 34}}}
    fast = picker.safe_tier_leg("Drake Maye", "player_pass_yds", dists)
    full = picker.safe_tier_leg("Drake Maye", "player_pass_yds", dists,
                                sims=10_000)
    assert fast["line"] == full["line"]
    assert abs(fast["fair_p"] - full["fair_p"]) < 0.03


def test_tier_legs_under_mirrored():
    """Less taps get their own mirrored lines: the Safe under targets
    P(under) ~= 85% — never the over line (a ~9% trap)."""
    dists = {"Drake Maye": {
        "player_pass_yds": {"mean": 235.3, "std": 64.0, "n": 34}}}
    overs = picker.tier_legs("Drake Maye", "player_pass_yds", dists,
                             side="over")
    unders = picker.tier_legs("Drake Maye", "player_pass_yds", dists,
                              side="under")
    assert [t["tier"] for t in overs] == [t["tier"] for t in unders]
    o_safe = next(t for t in overs if t["tier"] == "Safe")
    u_safe = next(t for t in unders if t["tier"] == "Safe")
    assert u_safe["side"] == "under"
    assert u_safe["fair_p"] > 0.75
    # The under line is well above the over line (mirrored), and each
    # side's line differs from the other's.
    assert u_safe["line"] > o_safe["line"]
    assert abs(u_safe["fair_p"] - 0.85) < 0.05


def test_card_safe_tier_row():
    from ui import cards
    p = {"player": "Drake Maye", "market": "player_pass_yds", "line": 225.5,
         "side": "over", "ev_pct": 7.48, "fair_prob": 0.571}
    html = cards.trading_card_html(
        p, sport="nfl",
        safe_tier={"line": 150.5, "fair_p": 0.91, "tier": "Safe"})
    assert "SAFE" in html
    assert "150.5" in html
    assert "91%" in html
    # Existing signaling untouched.
    assert "7.48%" in html


def test_card_news_indicator():
    from ui import cards
    p = {"player": "Drake Maye", "market": "player_pass_yds", "line": 225.5,
         "side": "over", "ev_pct": 7.48}
    html = cards.player_tile_html("x")  # unrelated sanity
    html = cards.trading_card_html(p, sport="nfl", news_count=3)
    assert "3 headlines" in html
    html0 = cards.trading_card_html(p, sport="nfl", news_count=0)
    assert "headlines" not in html0


def test_card_safe_tier_escapes():
    # safe_tier values are numeric; junk input never breaks the card.
    from ui import cards
    p = {"player": "P", "market": "m", "line": 1.0, "side": "over",
         "ev_pct": 1.0}
    html = cards.trading_card_html(p, safe_tier={"line": "xx", "fair_p": {}})
    assert "SAFE" not in html  # malformed tier -> row hidden, card fine


def test_board_dist_gaps():
    board = [
        {"player": "Josh Allen", "team": "BUF", "market": "player_pass_yds"},
        {"player": "Josh Allen", "team": "BUF", "market": "player_rush_yds"},
        {"player": "Dallen Bentley", "team": "NE", "market": "player_rec_yds"},
        {"player": "", "team": "NE", "market": "player_rec_yds"},
    ]
    dists = {"Josh Allen": {"player_pass_yds": {"mean": 1, "std": 1}}}
    gaps = picker.board_dist_gaps(board, dists)
    assert gaps == [
        ("Dallen Bentley", "NE", "player_rec_yds"),
        ("Josh Allen", "BUF", "player_rush_yds"),
    ]
    # No gaps when everything is covered.
    full = {"Josh Allen": {"player_pass_yds": {}, "player_rush_yds": {}},
            "Dallen Bentley": {"player_rec_yds": {}}}
    assert picker.board_dist_gaps(board, full) == []


def test_tier_lines_floor_at_half():
    """Low-mean markets (e.g. receptions) must not produce 'Over -0.5'
    safe rows — lines floor at 0.5, the lowest real book line."""
    tiers = picker.tier_lines(0.4, 0.3)
    assert tiers, "expected tiers"
    assert all(t["line"] >= 0.5 for t in tiers)
    assert tiers[0]["line"] == 0.5
