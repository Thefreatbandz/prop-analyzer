"""PrizePicks-style player/prop picker logic (no Streamlit).

Pure functions the Builder tab uses to turn a normalized props board
([{player, team, market, label, books: [{book, line, over, under}]}],
see odds/lumify.normalize) into:
  * a browsable player list (photo tiles, like the homepage)
  * per-player prop rows with a single consensus line + More/Less

Honesty rules: players come only from the board (live or sample —
never invented). Markets shown are only the ones the model can price
(price_leg returns a real probability). Empty board -> empty list and
the caller shows the honest empty state.
"""
from __future__ import annotations


def consensus_line(books: list[dict]) -> float | None:
    """Single line to show per market — the median across books.

    PrizePicks shows one number per prop; the median is the most
    honest single summary when books disagree. None when no book
    posted a line.
    """
    lines = [b.get("line") for b in (books or []) if b.get("line") is not None]
    if not lines:
        return None
    lines = sorted(lines)
    mid = len(lines) // 2
    if len(lines) % 2:
        return float(lines[mid])
    return float((lines[mid - 1] + lines[mid]) / 2)


def board_players(board: list[dict]) -> list[dict]:
    """Group a normalized board by player.

    Returns [{player, team, markets: [{market, label}]} sorted by
    player name. A market is listed only if at least one book posted
    a line. Players with zero priced markets are dropped.
    """
    by_player: dict[str, dict] = {}
    for row in board or []:
        name = (row.get("player") or "").strip()
        if not name:
            continue
        books = [b for b in (row.get("books") or []) if b.get("line") is not None]
        if not books:
            continue
        entry = by_player.setdefault(
            name, {"player": name, "team": row.get("team"),
                   "markets": [], "_seen": set()})
        key = row.get("market")
        if key and key not in entry["_seen"]:
            entry["_seen"].add(key)
            entry["markets"].append({
                "market": key,
                "label": row.get("label") or key,
            })
    out = []
    for entry in by_player.values():
        entry.pop("_seen", None)
        if entry["markets"]:
            out.append(entry)
    out.sort(key=lambda e: e["player"].lower())
    return out


def markets_for_sport(sport: str) -> list[str]:
    """Market keys the builder can price for a sport (model dist keys)."""
    sport = (sport or "nfl").lower()
    if sport == "nba":
        from projections import model
        return list(model.NBA_STAT_MAP.keys())
    if sport == "mlb":
        from projections import model
        return list(model.MLB_BATTER_STAT_MAP.keys()) + list(
            model.MLB_PITCHER_STAT_MAP.keys())
    from builder import legs as blegs
    return list(blegs.BUILDER_MARKETS.keys())


def market_label(market: str, sport: str = "nfl") -> str:
    """Display label for a market key. Never returns the raw key when a
    human label exists (builder markets first, then the card labels)."""
    from builder import legs as blegs
    if market in blegs.BUILDER_MARKETS:
        return blegs.BUILDER_MARKETS[market]
    try:
        from ui import cards as ui_cards
        if market in ui_cards.MARKET_LABELS:
            return ui_cards.MARKET_LABELS[market]
    except Exception:
        pass
    return market


def priceable_markets(board: list[dict], player: str,
                      distributions: dict) -> list[dict]:
    """Prop rows for one player: only markets that are BOTH on the board
    and priced by the model. Each row: {market, label, line, n_books}.

    Rows are in a stable sport-agnostic order: the sport's market list
    order first, then any board-only extras (shouldn't happen, but
    never crash on them).
    """
    dists = (distributions.get(player) or {})
    rows_by_market: dict[str, dict] = {}
    for row in board or []:
        if (row.get("player") or "").strip() != player:
            continue
        market = row.get("market")
        if not market or market in rows_by_market:
            continue
        if market not in dists:
            continue  # model can't price it — don't offer the tap
        line = consensus_line(row.get("books"))
        if line is None:
            continue
        rows_by_market[market] = {
            "market": market,
            "label": row.get("label") or market_label(market),
            "line": line,
            "n_books": len([b for b in (row.get("books") or [])
                            if b.get("line") is not None]),
        }
    # Stable order: canonical sport order first.
    order: list[str] = []
    for row in board or []:
        if (row.get("player") or "").strip() == player:
            order.append(row.get("market"))
    ordered = sorted(rows_by_market.values(),
                     key=lambda r: (order.index(r["market"])
                                    if r["market"] in order else 999,
                                    r["label"]))
    return ordered


def board_dist_gaps(board: list[dict],
                    distributions: dict) -> list[tuple]:
    """(player, team, market) triples on the board with no model dist.

    The bundled dist files only cover demo players — the caller builds
    these gaps on demand so the live board is fully priced. Pure logic,
    no model calls.
    """
    gaps = {
        (r.get("player"), r.get("team"), r.get("market"))
        for r in (board or [])
        if r.get("player") and r.get("market")
        and r["market"] not in (distributions.get(r["player"]) or {})
    }
    return sorted(gaps)


def safe_tier_leg(player: str, market: str,
                  distributions: dict, sims: int = 2_000) -> dict | None:
    """Just the Safe tier leg (highest-probability line) for a card.

    One Monte Carlo pricing instead of four — the cards show only the
    Safe row. None when the model can't price the market.

    sims defaults to 2,000 (not 10,000): the cards render this on every
    page load, uncached, once per card — 10k sims would add ~0.3s per
    card. 2k sims is ±1% accurate and ~5x faster. The builder's own
    tier_legs (user-initiated, one player at a time) keeps 10k.
    """
    from builder import legs as blegs

    dist = (distributions.get(player) or {}).get(market)
    if not dist or dist.get("do_not_bet"):
        return None
    mean, std = dist.get("mean"), dist.get("std")
    if mean is None or not std or std <= 0:
        return None
    tiers = tier_lines(mean, std)
    if not tiers:
        return None
    leg = blegs.price_leg(player, market, "over", tiers[0]["line"],
                          distributions, sims=sims)
    if leg:
        leg["tier"] = tiers[0]["tier"]
    return leg


def slip_has(legs: list[dict], player: str, market: str) -> bool:
    """True when this exact player+market is already on the slip."""
    return any(l.get("player") == player and l.get("market") == market
               for l in (legs or []))


# Risk tiers for the builder: multiple lines per stat, each with its
# fair hit probability, so users pick their risk level. Tbandz's rule:
# test parlays default LOW-risk ("we don't want to have more risk
# than profit"). Targets are P(over) — the natural framing is
# "over 150.5 hits 91%".
RISK_TIERS = [
    ("Safe", 0.85),
    ("Standard", 0.65),
    ("Plus", 0.45),
    ("Lottery", 0.30),
]


def tier_lines(mean: float, std: float,
               tiers: list[tuple[str, float]] | None = None) -> list[dict]:
    """Lines targeting each tier's P(over), via the normal quantile.

    Returns [{tier, target_p, line}] with lines rounded to 0.5
    (PrizePicks-style). Tiers that collapse to the same line
    (tiny-std distributions) are deduped — never show two identical
    rows. Pure math, no model calls; callers verify with price_leg.
    """
    from statistics import NormalDist

    tiers = tiers or RISK_TIERS
    if not std or std <= 0:
        return []
    nd = NormalDist(mean, std)
    out: list[dict] = []
    seen: set[float] = set()
    for name, target in tiers:
        try:
            line = round(nd.inv_cdf(1 - target) * 2) / 2
        except Exception:
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append({"tier": name, "target_p": target, "line": line})
    return out


def tier_legs(player: str, market: str, distributions: dict,
              side: str = "over") -> list[dict]:
    """Priced legs for each risk tier of one player-market.

    Each leg is priced with builder.legs.price_leg (Monte Carlo), so
    the displayed fair_p is the honest model number, not the tier
    target. Legs carry a "tier" field ("Safe"/"Standard"/...).

    For side="under" the tiers are mirrored: "Safe" targets P(under)
    ~= 85% (i.e. P(over) ~= 15%), so a Less tap on the Safe row adds a
    genuinely low-risk under leg — never a ~9% trap at the over line.
    Empty when the model can't price the market.
    """
    from builder import legs as blegs

    dist = (distributions.get(player) or {}).get(market)
    if not dist or dist.get("do_not_bet"):
        return []
    mean, std = dist.get("mean"), dist.get("std")
    if mean is None or not std or std <= 0:
        return []
    tiers = RISK_TIERS
    if side == "under":
        tiers = [(name, 1.0 - target) for name, target in RISK_TIERS]
    out = []
    for t in tier_lines(mean, std, tiers=tiers):
        leg = blegs.price_leg(player, market, side, t["line"], distributions)
        if leg:
            leg["tier"] = t["tier"]
            leg["target_p"] = t["target_p"]
            out.append(leg)
    return out
