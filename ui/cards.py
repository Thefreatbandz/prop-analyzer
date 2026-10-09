"""Pick-card building blocks for the Scan tab.

Pure helpers (no Streamlit import): hero EV metric, mini last-N bar
visualization, hit-rate shading, pick filtering. The friendly,
organized card layout Tbandz asked for — modeled on how props.cash
and BettingPros present a pick: one big edge number, the bet in
plain words, and a tiny visual of recent form.
"""
from __future__ import annotations

from players import headshots as _headshots

# Stat-category chips -> book market keys. "TDs" groups the three
# touchdown markets because nobody shops "player_rush_tds" alone.
CATEGORY_MARKETS = {
    "Pass Yds": ["player_pass_yds"],
    "Rush Yds": ["player_rush_yds"],
    "Rec Yds": ["player_rec_yds"],
    "Receptions": ["player_receptions"],
    "TDs": ["player_pass_tds", "player_rush_tds", "player_rec_tds"],
    # NBA
    "Points": ["player_points"],
    "Rebounds": ["player_rebounds"],
    "Assists": ["player_assists"],
    "Threes": ["player_threes"],
    "Steals": ["player_steals"],
    "Blocks": ["player_blocks"],
    # MLB
    "Hits": ["player_hits"],
    "Home Runs": ["player_home_runs"],
    "RBIs": ["player_rbis"],
    "Total Bases": ["player_total_bases"],
    "Strikeouts": ["player_so_batter", "player_so_pitcher"],
}

# Plain-English labels for markets (no jargon on the cards).
MARKET_FRIENDLY = {
    "player_pass_yds": "Passing yards",
    "player_pass_tds": "Passing TDs",
    "player_rush_yds": "Rushing yards",
    "player_rush_tds": "Rushing TDs",
    "player_receptions": "Receptions",
    "player_rec_yds": "Receiving yards",
    "player_rec_tds": "Receiving TDs",
}


def market_column(market: str) -> str | None:
    """nflverse stat column behind a book market key.

    Returns None for unknown markets — the card then skips the
    mini-bars instead of crashing. (Single source of truth lives in
    projections.model.STAT_MAP; we only read it here.)
    """
    from projections import model as pmodel

    entry = pmodel.STAT_MAP.get(market)
    return entry[0] if entry else None


def is_hit(value: float, line: float, side: str) -> str:
    """'hit' | 'miss' | 'push' for one past game vs the line.

    Over: beating the line is a hit. Under: staying under it is a hit.
    Landing exactly on the line is a push (the bet is refunded).
    """
    if value == line:
        return "push"
    won = (value > line) if side == "over" else (value < line)
    return "hit" if won else "miss"


def hit_stats(values: list, line: float, side: str) -> tuple[int, int]:
    """(hits, games) for a list of past game values vs a line.

    None values (didn't play / no stat) are skipped, not counted.
    Pushes count as games but not hits — same as the sportsbook grades.
    """
    hits, n = 0, 0
    for v in values:
        if v is None:
            continue
        n += 1
        if is_hit(v, line, side) == "hit":
            hits += 1
    return hits, n


def hit_shade(pct: float | None) -> str:
    """CSS class for a hit-rate number: green / red / neutral.

    60%+ is a real trend (green), 40%- is a fade (red), the middle is
    gold — readable at a glance, which is the whole point.
    """
    if pct is None:
        return "hit-na"
    if pct >= 0.6:
        return "hit-good"
    if pct <= 0.4:
        return "hit-bad"
    return "hit-mid"


def mini_bars_html(values: list, line: float, side: str) -> str:
    """Tiny last-N bar chart: green bar = beat the line, red = missed.

    This is the friendliest data-viz in the space (props.cash does it):
    five little bars tell you the player's recent form vs THIS line
    faster than any table. Empty input -> empty string (no bars).
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return ""
    vmax = max([abs(v) for v in vals] + [abs(line), 1e-9])
    bars = []
    for v in vals:
        # Floor the height so a 0-yard game still renders a stub.
        h = max(8.0, abs(v) / vmax * 100.0)
        cls = is_hit(v, line, side)
        bars.append(
            f'<div class="mbar {cls}" style="height:{h:.0f}%" '
            f'title="{v:g}"></div>'
        )
    return '<div class="mini-bars">' + "".join(bars) + "</div>"


def cold_line(values: list, line: float, side: str) -> str | None:
    """Plain-English "what's not working" line, or None when form is fine.

    Same per-game hit logic as the mini bars. Only speaks when the
    player is genuinely cold: a miss streak of 3+ straight, or a hit
    rate at/below 40% over at least 3 games. Never a pick — this is the
    warning label on the card.
    """
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return None
    results = [is_hit(v, line, side) for v in vals]
    streak = 0
    for r in reversed(results):  # most recent last
        if r == "miss":
            streak += 1
        else:
            break
    hits = sum(1 for r in results if r == "hit")
    n = len(vals)
    if streak >= 3:
        return f"Trending down — missed {streak} straight vs this line"
    if hits / n <= 0.4:
        return f"Missed {n - hits} of last {n} vs this line"
    return None


def _escape(text: str) -> str:
    """HTML-escape a player-supplied string for card HTML.

    Player names come from our own data feeds, but a name is still
    untrusted text going into unsafe_allow_html markup — escape it.
    """
    import html

    return html.escape(str(text), quote=True)


def trading_card_html(p: dict, *, matchup_html: str = "", bars: str = "",
                      hit_html: str = "", cold_html: str = "",
                      photo_b64: str | None = None, jersey: str | None = None,
                      position: str | None = None, team: str | None = None,
                      sport: str = "nfl", negative: bool = False) -> str:
    """Full trading-card HTML for a prop pick.

    Photo (or initials fallback) + jersey-number badge up top, then the
    existing card anatomy: side + line + odds, hero EDGE% with the MODEL
    PROB right beside it, best book, cold line, mini form bars, shaded
    hit rate. negative=True renders the Fades variant: red hero metric,
    same shape.

    Team colors: the card border/glow and jersey badge take the team's
    primary (or secondary when the primary is unreadably dark), plus a
    faint secondary tint wash. Unknown team -> default gold-on-charcoal.
    Colors are accents only — body text never changes, so every card
    stays readable. sport ("nfl"/"nba"/"mlb") picks the color table —
    abbreviations collide across leagues (MIA).
    """
    from teams import colors as _tcolors

    ev_cls = "ev-hero neg" if negative else "ev-hero"
    ev_txt = f"{p['ev_pct']:+.2f}%"
    prob = p.get("fair_prob")
    prob_html = ""
    if prob is not None:
        prob_html = (
            f'<div class="prob-line"><span class="prob-num">{prob:.0%}</span>'
            f'<span class="prob-cap">MODEL PROB</span></div>'
        )
    pos_html = (f'<span class="tcard-pos">{_escape(position)}</span>'
                if position else "")
    if photo_b64:
        photo_html = (
            f'<img src="{photo_b64}" alt="" loading="lazy">'
        )
    else:
        photo_html = (f'<div class="tcard-initials">'
                      f'{_escape(_headshots.initials(p.get("player", "")))}</div>')
    # Team accent: border + glow + badge. Falls back to the default
    # gold-on-charcoal card when the team is unknown.
    card_style = ""
    badge_style = ""
    accent = _tcolors.team_accent(team or p.get("team"), sport=sport)
    if accent:
        accent_color, tint = accent
        parts = [f"border-color:{accent_color}",
                 f"box-shadow:0 0 16px {accent_color}30"]
        if tint:
            parts.append(
                f"background:linear-gradient(135deg, {tint}1A, transparent 60%)")
        card_style = f' style="{";".join(parts)}"'
        badge_style = (
            f' style="background:{accent_color};'
            f'color:{_tcolors.badge_text_color(accent_color)}"'
        )
    jersey_html = (f'<span class="jersey-badge"{badge_style}>'
                   f'{_escape(jersey)}</span>'
                   if jersey else "")
    cold_block = (f'<div class="pc-cold">{_escape(cold_html)}</div>'
                  if cold_html else "")
    _edge_line = edge_line_html(p, negative=negative)
    _edge_why = edge_explainer_html(p, negative=negative)
    return (
        f'<div class="pick-card tcard"{card_style}>'
        '<div class="tcard-top">'
        f'<div class="tcard-photo">{photo_html}{jersey_html}</div>'
        '<div class="tcard-id">'
        f'<div class="tcard-name">{_escape(p.get("player", ""))}{pos_html}</div>'
        f'<div class="pc-team">{matchup_html}</div>'
        f'<div class="pc-bet">{_escape(str(p.get("side", "")).title())} '
        f'{p["line"]:g} <span class="pc-odds">{p["price"]:+}</span></div>'
        f'<div class="pc-book">Best: <b>{_escape(p.get("book", ""))}</b></div>'
        "</div>"
        f'<div class="pc-hero"><div class="{ev_cls}">{ev_txt}</div>'
        f'<div class="ev-cap">EDGE</div>{prob_html}</div>'
        "</div>"
        f"{_edge_line}{_edge_why}{cold_block}{bars}{hit_html}"
        "</div>"
    )
def _edge_numbers(p: dict):
    """fair P(hit) and the book's implied P(hit), or (None, None).

    Shared by the one-line edge readout and the beginner explainer so
    both always agree. Numbers only — nothing user-controlled.
    """
    fair_p = p.get("fair_prob")
    if fair_p is None:
        return None, None
    try:
        from engine import odds_math as _om
        implied = _om.american_to_implied(float(p["price"]))
    except (ValueError, KeyError, TypeError):
        return None, None
    return fair_p, implied


def edge_line_html(p: dict, *, source: str = "model",
                   negative: bool = False) -> str:
    """One-line beginner edge readout for a card.

    Written for people new to props: "68 in 100" instead of "implied
    probability". source="sharp" is for moneyline cards, where the fair
    number comes from the Pinnacle no-vig market, not our sim.
    """
    fair_p, implied = _edge_numbers(p)
    if fair_p is None:
        return ""
    who = "our model" if source == "model" else "the sharp market"
    tail = ("That gap is the edge." if not negative
            else "No edge here \u2014 that\u2019s why it\u2019s a fade.")
    return (
        f'<div class="pc-edge-line">EDGE {p["ev_pct"]:+.2f}% — {who}: '
        f'{fair_p:.0%} in 100 vs the book\u2019s {implied:.0%} in 100. '
        f'{tail}</div>'
    )


def edge_explainer_html(p: dict, *, source: str = "model",
                        negative: bool = False) -> str:
    """Tappable beginner explainer: "New to edge? What this means".

    Three short sentences, zero jargon. A native <details> element keeps
    it light — no per-card Streamlit widgets. Numbers only, always safe.
    """
    fair_p, implied = _edge_numbers(p)
    if fair_p is None:
        return ""
    fpct = int(round(fair_p * 100))
    ipct = int(round(implied * 100))
    try:
        price_txt = f"{float(p['price']):+.0f}"
    except (ValueError, KeyError, TypeError):
        return ""
    if source == "model":
        who_line = (f"Our model studied every NFL game since 2015 and says "
                    f"it really wins about {fpct} times out of 100.")
    else:
        who_line = (f"Pinnacle \u2014 the book the sharps trust \u2014 says "
                    f"the true chance is about {fpct} times out of 100.")
    if negative:
        close = ("The gap runs the wrong way \u2014 you\u2019re paying for "
                 "more chance than the numbers see. That\u2019s why it\u2019s "
                 "a fade, not a pick.")
    else:
        close = ("That gap is the EDGE. A bet like this is +EV: make enough "
                 "of them and the math favors you. Any single one can still "
                 "lose \u2014 the edge shows up over time, not in one game.")
    return (
        f'<details class="edge-why"><summary>New to edge? What this means'
        f'</summary><div class="edge-why-body">'
        f'The book\u2019s {price_txt} odds pay you like this wins {ipct} '
        f'times out of 100.<br>{who_line}<br>{close}'
        f'</div></details>'
    )


def suggestion_card_html(s: dict, *, photo_b64: str | None = None,
                         position: str | None = None,
                         team: str | None = None) -> str:
    """Mini trading card for the Suggested strip.

    Photo (or gold initials fallback) + team-color accent edge, name with
    position, team line, and the reason string styled like a stat line —
    not a gray box. The tappable View button stays a Streamlit widget
    rendered below this HTML by the caller. All interpolated text escaped.
    """
    from teams import colors as _tcolors

    team_name = team or s.get("team", "")
    style = ""
    accent = _tcolors.team_accent(team_name)
    if accent:
        accent_color, _tint = accent
        style = (f' style="border-color:{accent_color};'
                 f'box-shadow:0 0 14px {accent_color}30"')
    if photo_b64:
        photo_html = f'<img src="{photo_b64}" alt="" loading="lazy">'
    else:
        photo_html = (f'<div class="sug-mini-initials">'
                      f'{_escape(_headshots.initials(s.get("name", "")))}</div>')
    pos_html = (f'<span class="tcard-pos">{_escape(position)}</span>'
                if position else "")
    team_html = (f'<div class="sug-mini-team">{_escape(team_name)}</div>'
                 if team_name else "")
    return (
        f'<div class="sug-mini"{style}>'
        f'<div class="sug-mini-photo">{photo_html}</div>'
        '<div class="sug-mini-id">'
        f'<div class="sug-mini-name">{_escape(s.get("name", ""))}{pos_html}</div>'
        f'{team_html}'
        f'<div class="sug-mini-reason">{_escape(s.get("reason", ""))}</div>'
        "</div></div>"
    )


def suggestion_card_safe(s: dict, rosters_df) -> str | None:
    """Render one suggestion card; never raises — None on any failure.

    The Scan strip calls this per card (headshot lookups included) so one
    bad suggestion can never take down the whole tab the way a raw
    exception in the render loop would. A skipped card is a missing card,
    not a broken page.
    """
    try:
        if not isinstance(s, dict) or not s.get("name"):
            return None
        return suggestion_card_html(
            s,
            photo_b64=_headshots.headshot_b64(s["name"], rosters_df),
            position=_headshots.position_abbr(s["name"], rosters_df),
            team=s.get("team"),
        )
    except Exception:
        return None


def _accent_style(team: str | None) -> tuple[str, str]:
    """(card_style, badge_style) for team-color accents on a card.

    Same recipe as trading_card_html: team-color border + glow, faint
    tint wash, readable jersey badge. Unknown team -> gold-on-charcoal
    defaults (empty styles).
    """
    from teams import colors as _tcolors

    card_style = ""
    badge_style = ""
    accent = _tcolors.team_accent(team)
    if accent:
        accent_color, tint = accent
        parts = [f"border-color:{accent_color}",
                 f"box-shadow:0 0 16px {accent_color}30"]
        if tint:
            parts.append(
                f"background:linear-gradient(135deg, {tint}1A, transparent 60%)")
        card_style = f' style="{";".join(parts)}"'
        badge_style = (
            f' style="background:{accent_color};'
            f'color:{_tcolors.badge_text_color(accent_color)}"'
        )
    return card_style, badge_style


def player_spotlight_html(name: str, *, bio: dict | None = None,
                          photo_b64: str | None = None,
                          form: dict | None = None,
                          matchup: str = "",
                          status_line: str = "") -> str:
    """Player spotlight card for the View flow — always renders something.

    Tapping View on a suggestion used to land on a flat "no +EV flags"
    note that felt broken. Now the player always gets their card first:
    photo (or initials), team · position, jersey badge, season form
    (last-5 bars vs their own season average — green = above it), next
    matchup, and any roster/injury status. The +EV props (or the honest
    "market has this one priced right" note) render below it.

    bio: find_player() row or None (unknown name still gets a card with
    an honest "not on a current roster" line). form: player_form_summary()
    dict or None (no form line for positions without a yardage stat).
    All interpolated text is escaped.
    """
    team = (bio or {}).get("team")
    position = (bio or {}).get("position")
    jersey = (bio or {}).get("jersey")
    card_style, badge_style = _accent_style(team)

    if photo_b64:
        photo_html = f'<img src="{photo_b64}" alt="" loading="lazy">'
    else:
        photo_html = (f'<div class="tcard-initials">'
                      f'{_escape(_headshots.initials(name))}</div>')
    try:
        jersey_txt = str(int(jersey)) if jersey is not None else ""
    except (TypeError, ValueError):
        jersey_txt = ""
    jersey_html = (f'<span class="jersey-badge"{badge_style}>'
                   f'{_escape(jersey_txt)}</span>' if jersey_txt else "")
    pos_html = (f'<span class="tcard-pos">{_escape(position)}</span>'
                if position else "")
    team_html = (f'<div class="pc-team">{_escape(team)}</div>' if team
                 else '<div class="pc-team">Not on a current roster</div>')

    form_html = ""
    if form:
        # Bars vs the player's own season average: green = above it.
        # This is form, not a pick — no edge claim attached.
        bars = mini_bars_html(form["last5"], form["season_avg"], "over")
        form_html = (
            f'<div class="pc-edge-line">{form["season_avg"]:g} '
            f'{_escape(form["label"])}/game this season '
            f'({_escape(str(form["games"]))} games)</div>'
            f'<div class="pc-team" style="margin-top:6px">Last 5 vs own average</div>'
            f'{bars}'
        )
    matchup_html = (f'<div class="pc-team">{_escape(matchup)}</div>'
                    if matchup else "")
    status_html = (f'<div class="pc-cold">{_escape(status_line)}</div>'
                   if status_line else "")
    return (
        f'<div class="pick-card tcard"{card_style}>'
        '<div class="tcard-top">'
        f'<div class="tcard-photo">{photo_html}{jersey_html}</div>'
        '<div class="tcard-id">'
        f'<div class="tcard-name">{_escape(name)}{pos_html}</div>'
        f'{team_html}'
        f'{form_html}'
        f'{matchup_html}'
        f'{status_html}'
        "</div></div></div>"
    )


def game_row_html(g: dict) -> str:
    """One slim schedule row: team dots + abbrs, kickoff, TODAY pill.

    g comes from games.schedule.parse_events: {away, home, away_abbr,
    home_abbr, starts_at, week, is_today, kickoff}. Team dots use the
    club colors (gold fallback); everything user-visible is escaped.
    """
    from teams import colors as _tcolors

    def _dot(abbr):
        accent = _tcolors.team_accent(abbr)
        color = accent[0] if accent else "#C9A227"
        return f'<span class="tdot" style="background:{color}"></span>'

    away = _escape(g.get("away_abbr") or g.get("away") or "?")
    home = _escape(g.get("home_abbr") or g.get("home") or "?")
    kickoff = _escape(g.get("kickoff") or "TBD")
    week = _escape(g.get("week") or "")
    meta = f"{kickoff}" + (f" · {week}" if week else "")
    pill = ' <span class="today-pill">TODAY</span>' if g.get("is_today") else ""
    return (
        f'<div class="game-row">{_dot(g.get("away_abbr"))}'
        f'<span class="game-teams">{away}</span>'
        f'<span class="pc-team"> @ </span>'
        f'{_dot(g.get("home_abbr"))}'
        f'<span class="game-teams">{home}</span>{pill}'
        f'<span class="game-meta">{meta}</span></div>'
    )


def filter_picks(picks: list[dict], category: str, side: str) -> list[dict]:
    """Apply the stat-category chips + Over/Under pills to the pick list.

    Moneyline picks have no stat market, so they only appear under the
    "All" chip — filtering to "Pass Yds" shouldn't hide the concept of
    moneylines, it just narrows the prop list (moneylines get their own
    treatment while the Odds API key is missing anyway).
    """
    out = []
    for p in picks:
        if p.get("type") == "moneyline":
            # No stat market and no over/under — only the unfiltered view.
            if category == "All" and side == "All":
                out.append(p)
            continue
        if category != "All":
            allowed = CATEGORY_MARKETS.get(category, [])
            if p.get("market") not in allowed:
                continue
        if side != "All" and p.get("side") != side.lower():
            continue
        out.append(p)
    return out


def premium_lock_html(title: str, teaser_lines: list[str]) -> str:
    """The tasteful locked screen for premium features.

    Same card everywhere (Compare, saved builds, alerts, lab) so the
    freemium model reads as one product, not four paywalls.
    """
    items = "".join(f"<div class='sug-reason'>· {t}</div>"
                    for t in teaser_lines)
    return (
        '<div class="pick-card" style="border-color:#C9A227">'
        '<span class="ev-big" style="color:#C9A227">Premium</span><br>'
        f"<b>{title}</b>"
        f"{items}"
        "<div class='sug-reason' style='margin-top:8px'>Free tier covers "
        "the EV scan, player profiles, tendencies and news. Flip "
        "<span style='font-family:monospace'>PREMIUM_ENABLED</span> in "
        "config.py to unlock (no payments built yet).</div>"
        "</div>"
    )