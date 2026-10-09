"""Pick ranking: turn lines + projections into a ranked +EV list.

Player props: for each player-market, take the BEST line/price across
books (line shopping is free edge), run our Monte Carlo fair probability
against it, and rank by EV%.

Moneyline: best price across books for each side, plus a cross-check
against Pinnacle (the sharp book) when it's quoted — if our best price
beats Pinnacle's no-vig price, that's a line-shopping edge even without
a model.

Only flags with EV% >= min_ev make the list. v1 default: 2%.
"""
from __future__ import annotations

from projections.montecarlo import (
    fair_odds_american,
    prob_over,
    stable_seed,
)
from .odds_math import (
    american_to_decimal,
    american_to_implied,
    ev_percent,
    no_vig_two_way,
)

MIN_EV = 0.02  # only flag edges of at least 2%


def _best_side(books: list[dict], side: str) -> dict | None:
    """Best (highest decimal payout) book for over/under on one line.

    For props the line can differ by book too — we compare per book-line
    combo and keep the best EV, since you can only bet what's offered.
    """
    best = None
    for b in books:
        price = b.get(side)
        if price is None:
            continue
        dec = american_to_decimal(price)
        if best is None or dec > best["decimal"]:
            best = {"book": b["book"], "line": b["line"], "price": price, "decimal": dec}
    return best


def _model_prob(dist: dict, side: str, line: float,
                player: str, market: str, sims: int) -> float | None:
    """Model's fair probability for one side, or None when degenerate.

    A Monte Carlo probability of exactly 0.0 or 1.0 means the model's
    distribution is fake-certain — near-zero variance on a tiny sample,
    typically a fringe player with a few identical games (n=3, std~0).
    There is no honest EV to compute there (ev_percent would raise), so
    the caller skips the side and counts it. Noise stays noise; it never
    becomes a pick.
    """
    if dist.get("mean") is None or dist.get("std") is None:
        return None  # no data at all — same as a collapsed probability
    seed = stable_seed(player, market, side, line)
    if side == "over":
        p = prob_over(dist["mean"], dist["std"], line, n=sims, seed=seed)
    else:
        p = 1.0 - prob_over(dist["mean"], dist["std"], line, n=sims, seed=seed)
    if not 0.0 < p < 1.0:
        return None
    return p


def rank_props(prop_board: list[dict], distributions: dict,
               min_ev: float = MIN_EV, sims: int = 10_000,
               stats: dict | None = None) -> list[dict]:
    """Rank player props by EV%. distributions: {player: {market: dist}}.

    Each pick: {type, player, team, market, label, side, book, line,
                price, fair_prob, fair_american, ev_pct, ...}

    `stats` (optional dict) is filled with scan diagnostics, including
    `degenerate_sides`: sides skipped because the model's probability
    collapsed to exactly 0 or 1 (tiny-sample fringe players — noise,
    not signal). Callers surface that count loudly; it is never a pick.
    """
    picks = []
    degenerate = 0
    malformed = 0
    for prop in prop_board:
        try:
            player, market = prop["player"], prop["market"]
            dist = (distributions.get(player) or {}).get(market)
            if not dist or dist.get("do_not_bet"):
                continue  # no projection, or player is OUT — skip loudly elsewhere
            for side in ("over", "under"):
                best = _best_side(prop["books"], side)
                if not best:
                    continue
                fair_p = _model_prob(dist, side, best["line"], player, market, sims)
                if fair_p is None:
                    degenerate += 1
                    continue
                ev = ev_percent(fair_p, best["decimal"])
                if ev >= min_ev:
                    picks.append(
                        {
                            "type": "prop",
                            "player": player,
                            "team": prop.get("team"),
                            "market": market,
                            "label": prop.get("label", market),
                            "side": side,
                            "book": best["book"],
                            "line": best["line"],
                            "price": best["price"],
                            "fair_prob": round(fair_p, 4),
                            "fair_american": round(fair_odds_american(fair_p)),
                            "ev_pct": round(ev * 100, 2),
                            "n_games": dist.get("n"),
                            "injury_flag": dist.get("injury_flag"),
                            # The math, shown in the dashboard (Learn mode):
                            "math": (
                                f"Model: {player} {prop.get('label', market)} "
                                f"~ N({dist['mean']:.1f}, {dist['std']:.1f}) over "
                                f"{dist.get('n', '?')} games → P({side} {best['line']}) = "
                                f"{fair_p:.1%}. Book pays {best['price']} "
                                f"({best['decimal']:.3f}x). "
                                f"EV = {fair_p:.3f} × {best['decimal']:.3f} − 1 = {ev:+.1%}."
                            ),
                        }
                    )
        except Exception:
            # One malformed prop (bad line, bad price, broken dist) never
            # kills the whole scan — skip it, count it, say it out loud.
            malformed += 1
            continue
    picks.sort(key=lambda p: p["ev_pct"], reverse=True)
    if stats is not None:
        stats["degenerate_sides"] = degenerate
        stats["malformed_props"] = malformed
    return picks


MAX_NEG_EV = -0.02  # fades: only flag edges of at least -2% (priced against you)


def rank_fades(prop_board: list[dict], distributions: dict,
               max_ev: float = MAX_NEG_EV, top_n: int = 12,
               sims: int = 10_000, stats: dict | None = None) -> list[dict]:
    """The spots to AVOID: props priced against you, most negative first.

    Same math as rank_props, mirrored: keep sides with ev <= max_ev
    (default -2%), sort ascending (worst first), cap at top_n. The
    returned dicts are the same shape as picks (ev_pct negative) so
    cards render unchanged — only the hero metric turns red.

    These are NOT picks. The UI labels them "spots to stay away from".

    `stats` (optional dict) reports `degenerate_sides`, same as rank_props.
    """
    fades = []
    degenerate = 0
    for prop in prop_board:
        player, market = prop["player"], prop["market"]
        dist = (distributions.get(player) or {}).get(market)
        if not dist or dist.get("do_not_bet"):
            continue
        for side in ("over", "under"):
            best = _best_side(prop["books"], side)
            if not best:
                continue
            fair_p = _model_prob(dist, side, best["line"], player, market, sims)
            if fair_p is None:
                degenerate += 1
                continue
            ev = ev_percent(fair_p, best["decimal"])
            if ev <= max_ev:
                fades.append(
                    {
                        "type": "prop",
                        "player": player,
                        "team": prop.get("team"),
                        "market": market,
                        "label": prop.get("label", market),
                        "side": side,
                        "book": best["book"],
                        "line": best["line"],
                        "price": best["price"],
                        "fair_prob": round(fair_p, 4),
                        "fair_american": round(fair_odds_american(fair_p)),
                        "ev_pct": round(ev * 100, 2),
                        "n_games": dist.get("n"),
                        "injury_flag": dist.get("injury_flag"),
                        "math": (
                            f"Model: {player} {prop.get('label', market)} "
                            f"~ N({dist['mean']:.1f}, {dist['std']:.1f}) over "
                            f"{dist.get('n', '?')} games → P({side} {best['line']}) = "
                            f"{fair_p:.1%}. Book pays {best['price']} "
                            f"({best['decimal']:.3f}x). "
                            f"EV = {fair_p:.3f} × {best['decimal']:.3f} − 1 = {ev:+.1%}."
                        ),
                    }
                )
    fades.sort(key=lambda p: p["ev_pct"])  # most negative first
    if stats is not None:
        stats["degenerate_sides"] = degenerate
    return fades[:top_n]


def rank_moneylines(games: list[dict], min_ev: float = MIN_EV,
                    sharp_book: str = "pinnacle") -> list[dict]:
    """Rank moneyline edges.

    Two signals, both shown:
    1. Line shopping: best price across books vs the WORST price — the gap
       is money left on the table (always take the best number).
    2. Sharp cross-check: best price vs Pinnacle's no-vig fair price.
       Beating Pinnacle = the sharpest book thinks you're getting value.
    """
    picks = []
    for g in games:
        books = g["books"]
        if len(books) < 2:
            continue
        for side, team in (("home", g["home"]), ("away", g["away"])):
            prices = [(b, v[side]) for b, v in books.items()]
            best_book, best_price = max(prices, key=lambda x: american_to_decimal(x[1]))
            worst_price = min(p[1] for p in prices)
            best_dec = american_to_decimal(best_price)

            # Signal 2: vs Pinnacle no-vig fair.
            sharp_ev = None
            sharp_note = None
            if sharp_book in books:
                s = books[sharp_book]
                fair_home, fair_away = no_vig_two_way(s["home"], s["away"])
                fair_p = fair_home if side == "home" else fair_away
                sharp_ev = ev_percent(fair_p, best_dec)
                sharp_note = (
                    f"Pinnacle no-vig says {team} wins {fair_p:.1%} "
                    f"(fair {fair_odds_american(fair_p):+.0f})."
                )

            # Signal 1: line-shopping gap, expressed as payout uplift.
            worst_dec = american_to_decimal(worst_price)
            shop_uplift = (best_dec - worst_dec) / worst_dec

            # A moneyline "pick" needs the sharp cross-check to clear the
            # bar — shopping alone isn't an edge, it's just the best price.
            if sharp_ev is not None and sharp_ev >= min_ev:
                picks.append(
                    {
                        "type": "moneyline",
                        "team": team,
                        "side": side,
                        "game": f"{g['away']} @ {g['home']}",
                        "event_id": g["event_id"],
                        "commence_time": g.get("commence_time"),
                        "book": best_book,
                        "price": best_price,
                        "fair_prob": round(fair_p, 4),
                        "fair_american": round(fair_odds_american(fair_p)),
                        "ev_pct": round(sharp_ev * 100, 2),
                        "shop_uplift_pct": round(shop_uplift * 100, 2),
                        "worst_price": worst_price,
                        "math": (
                            f"{sharp_note} Best price {best_price} at "
                            f"{best_book} ({best_dec:.3f}x) vs worst {worst_price} "
                            f"({worst_dec:.3f}x) — shopping saves "
                            f"{shop_uplift:.1%}. EV = {fair_p:.3f} × "
                            f"{best_dec:.3f} − 1 = {sharp_ev:+.1%}."
                        ),
                    }
                )
    picks.sort(key=lambda p: p["ev_pct"], reverse=True)
    return picks
