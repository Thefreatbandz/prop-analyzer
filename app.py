"""Prop Analyzer dashboard — Streamlit.

Three views: Scan (ranked +EV picks), Pick detail (the full math),
Tracker (paper record: CLV, win rate, ROI).

Runs with zero API keys: everything falls back to bundled sample data
and says so up front. Add keys to .env for live odds.
"""
from __future__ import annotations

import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from engine import picks as engine
from odds import lumify, the_odds_api
from tracker import db

st.set_page_config(page_title="Prop Analyzer", page_icon=None, layout="wide")

GOLD = "#C9A227"

# ---------- Dev mode ----------
# Internal/ops details (API key status, feed diagnostics) are dev-only:
# only Tbandz and I see them, via ?dev=1 in the URL or DEV_MODE=1 in .env.
# Public visitors get friendly user-facing copy, never key names or
# exception types.
DEV_MODE = (str(st.query_params.get("dev", "")) == "1"
            or os.environ.get("DEV_MODE") == "1")

# ---------- Cached data helpers (v2 tabs) ----------
# functools.lru_cache (not st.cache_data): polars DataFrames aren't
# hashable by Streamlit, but lru_cache handles them fine.
from functools import lru_cache

LEAGUE_ABBRS = ["ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
                "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
                "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
                "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS"]


@lru_cache(maxsize=2)
def _rosters_df():
    from projections import nflverse as nv
    return nv.rosters()


@lru_cache(maxsize=2)
def _teams_list():
    from projections import nflverse as nv
    from players import profiles
    try:
        return profiles.get_teams(nv.teams(), _rosters_df())
    except Exception:
        return [{"abbr": a, "name": a, "nick": "", "conf": "", "division": ""}
                for a in LEAGUE_ABBRS]


@lru_cache(maxsize=2)
def _player_stats_df():
    from projections import nflverse as nv
    return nv.player_stats()


@lru_cache(maxsize=2)
def _schedules_df():
    from projections import nflverse as nv
    return nv.schedules()


@lru_cache(maxsize=2)
def _injuries_df():
    from projections import nflverse as nv
    return nv.injuries()


@lru_cache(maxsize=4)
def _pbp_df(seasons_key: str):
    from projections import nflverse as nv
    seasons = [int(s) for s in seasons_key.split(",")]
    return nv.pbp(seasons=seasons)


@lru_cache(maxsize=2)
def _espn_news():
    from news import espn as news_mod
    return news_mod.get_nfl_news(limit=20)


def _cur_week():
    from projections import build as pbuild
    try:
        return pbuild.current_nfl_week()
    except Exception:
        return 2026, 5

st.markdown(
    """<style>
    /* ---- Prop Analyzer theme: gold ink on charcoal ---- */
    :root { --gold: #C9A227; --gold-dim: #8a6f1c; --ink: #EDEDED;
            --ink-dim: #9a9aa0; --panel: #141416; --line: #2a2a2e; }
    html, body, [data-testid="stAppViewContainer"] {
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
                     "Segoe UI", Inter, Roboto, sans-serif;
        letter-spacing: 0.01em;
    }
    h1, h2, h3 { letter-spacing: 0.02em; font-weight: 700; }
    [data-testid="stCaptionContainer"] { color: var(--ink-dim); }

    .pick-card { border: 1px solid #33333a; border-radius: 12px;
                 padding: 14px 16px; margin-bottom: 12px;
                 background: linear-gradient(180deg, #18181c, var(--panel));
                 box-shadow: 0 6px 26px rgba(0,0,0,.5),
                             inset 0 1px 0 rgba(255,255,255,.05); }
    .pick-card b { color: var(--ink); }

    /* Section headers: gold gradient underline bar */
    h2::after, h3::after { content: ""; display: block; height: 2px;
        width: 60px; margin-top: 8px; border-radius: 2px;
        background: linear-gradient(90deg, var(--gold), transparent); }
    .ev-big { color: var(--gold); font-size: 1.45em; font-weight: 800;
              font-variant-numeric: tabular-nums; }
    .ev-neg { color: #C46A6A; }
    .flag-warn { color: #E0A030; }
    .key-ok { color: #7BC47F; } .key-miss { color: #C46A6A; }
    .gold-label { color: var(--gold); font-weight: 600; }

    /* ---- Floating tab nav: sticky pill bar on desktop, bottom bar on phone ---- */
    [data-testid="stTabs"] [role="tablist"] {
        position: sticky; top: 3.4rem; z-index: 90;
        background: rgba(18,18,22,.93); backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid var(--line); border-radius: 999px;
        padding: 6px 8px; gap: 2px;
        box-shadow: 0 6px 24px rgba(0,0,0,.5);
        overflow-x: auto; scrollbar-width: none;
    }
    [data-testid="stTabs"] [role="tablist"]::-webkit-scrollbar { display: none; }
    div[data-testid="stTab"] { border-radius: 999px !important;
        padding: 8px 15px !important; flex: 0 0 auto; }
    div[data-testid="stTab"] p { color: var(--ink-dim); font-weight: 600;
        font-size: 0.92em; margin: 0; }
    div[data-testid="stTab"]:hover p { color: var(--ink); }
    div[data-testid="stTab"][aria-selected="true"] {
        background: linear-gradient(135deg, #E8C84A, var(--gold)) !important;
        box-shadow: 0 0 16px rgba(201,162,39,.4); }
    div[data-testid="stTab"][aria-selected="true"] p {
        color: #111 !important; font-weight: 800; }
    div[data-testid="stTab"] .react-aria-SelectionIndicator { display: none; }

    /* ---- Brand every banner: no default Streamlit blue anywhere ---- */
    div[data-testid="stAlert"] { background: transparent; }
    div[data-testid="stAlertContainer"] {
        background: transparent !important; }
    div[data-testid^="stAlertContent"] {
        background: #17171a !important;
        border: 1px solid var(--line) !important;
        border-radius: 12px !important;
        box-shadow: 0 2px 12px rgba(0,0,0,.35); }
    div[data-testid^="stAlertContent"] p { color: var(--ink); }
    div[data-testid^="stAlertContent"] a { color: var(--gold); }
    div[data-testid="stAlertContentInfo"] {
        border-left: 3px solid var(--gold) !important; }
    div[data-testid="stAlertContentInfo"] svg { fill: var(--gold) !important; }
    div[data-testid="stAlertContentWarning"] {
        border-left: 3px solid #E0A030 !important; }
    div[data-testid="stAlertContentWarning"] svg { fill: #E0A030 !important; }
    div[data-testid="stAlertContentSuccess"] {
        border-left: 3px solid #7BC47F !important; }
    div[data-testid="stAlertContentSuccess"] svg { fill: #7BC47F !important; }
    div[data-testid="stAlertContentError"] {
        border-left: 3px solid #C46A6A !important; }
    div[data-testid="stAlertContentError"] svg { fill: #C46A6A !important; }

    /* Buttons: gold primary, quiet secondary */
    button[kind="primary"], button[data-testid="baseButton-primary"] {
        background: linear-gradient(135deg, #E8C84A, var(--gold));
        border-color: var(--gold); color: #111;
        font-weight: 700; border-radius: 10px;
        box-shadow: 0 0 18px rgba(201,162,39,.35); }
    button[kind="secondary"], button[data-testid="baseButton-secondary"] {
        border-radius: 10px; }

    /* Inputs + selects */
    [data-testid="stTextInput"] input, [data-testid="stSelectbox"] div {
        border-radius: 10px; }
    [data-baseweb="select"] { border-radius: 10px; }

    /* Metrics: tabular numbers, breathing room */
    [data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
    [data-testid="stMetric"] { background: var(--panel);
        border: 1px solid var(--line); border-radius: 12px; padding: 10px 14px; }

    /* Sidebar */
    [data-testid="stSidebar"] { background: #101012; }
    [data-testid="stSidebar"] h2 { font-size: 1.05em; }

    /* Dividers + spacing */
    hr { border-color: var(--line); margin: 1.2em 0; }
    .block-container { padding-top: 1.6rem; max-width: 1100px; }

    /* ---- Scan home: pick cards, hero edge, mini form bars ---- */
    .ev-hero { color: #7BC47F; font-size: 2.1em; font-weight: 800;
               font-variant-numeric: tabular-nums; line-height: 1.05;
               text-shadow: 0 0 24px rgba(123,196,127,.45); }
    .ev-hero.neg { color: #C46A6A;
                   text-shadow: 0 0 24px rgba(196,106,106,.45); }
    .ev-cap { color: var(--ink-dim); font-size: 0.72em;
              letter-spacing: 0.16em; font-weight: 700; }
    .pc-head { font-size: 1.06em; margin-bottom: 2px; }
    .pc-team { color: var(--ink-dim); font-weight: 400; font-size: 0.88em; }
    .pc-mid { display: flex; justify-content: space-between;
              align-items: center; margin: 8px 0 4px; gap: 12px; }
    .pc-bet { font-size: 1.14em; font-weight: 700; }
    .pc-odds { color: var(--ink-dim); font-weight: 600; font-size: 0.92em; }
    .pc-book { color: var(--ink-dim); font-size: 0.88em; margin-top: 3px; }
    .pc-book b { color: var(--gold); }
    .pc-hero { text-align: right; flex-shrink: 0; }
    .mini-bars { display: flex; align-items: flex-end; gap: 4px;
                 height: 38px; margin: 10px 0 4px; }
    .mbar { width: 16px; border-radius: 3px; min-height: 3px; }
    .mbar.hit { background: #7BC47F; }
    .mbar.miss { background: #C46A6A; }
    .mbar.push { background: #9a9aa0; }
    .pc-hit { color: var(--ink-dim); font-size: 0.9em; margin-top: 2px; }
    .hit-good { color: #7BC47F; font-weight: 700; }
    .hit-bad { color: #C46A6A; font-weight: 700; }
    .hit-mid { color: var(--gold); font-weight: 700; }
    .hit-na { color: var(--ink-dim); }
    .sug-card { border: 1px solid var(--line); border-radius: 10px;
                padding: 10px 12px; background: var(--panel);
                margin-bottom: 8px; }
    .sug-name { font-weight: 700; }
    .sug-reason { color: var(--ink-dim); font-size: 0.84em; margin-top: 2px; }
    /* Suggested strip: mini trading cards, not gray boxes */
    .sug-mini { display: flex; gap: 11px; align-items: center;
                border: 1px solid var(--line); border-radius: 12px;
                padding: 10px 12px; margin-bottom: 8px;
                background: linear-gradient(180deg, #18181c, var(--panel));
                box-shadow: 0 4px 16px rgba(0,0,0,.4); }
    .sug-mini-photo { flex-shrink: 0; }
    .sug-mini-photo img { width: 52px; height: 52px; border-radius: 12px;
                          object-fit: cover; border: 2px solid var(--gold);
                          background: #1c1c20; }
    .sug-mini-initials { width: 52px; height: 52px; border-radius: 12px;
                         background: #232327; border: 2px solid var(--line);
                         display: flex; align-items: center;
                         justify-content: center; font-weight: 800;
                         color: var(--gold); }
    .sug-mini-id { min-width: 0; }
    .sug-mini-name { font-weight: 800; font-size: 0.98em; line-height: 1.25; }
    .sug-mini-team { color: var(--ink-dim); font-size: 0.78em; margin-top: 1px; }
    .sug-mini-reason { color: var(--gold); font-size: 0.82em; margin-top: 4px;
                       font-weight: 600; font-variant-numeric: tabular-nums;
                       line-height: 1.4; }
    .scan-filter { color: var(--ink-dim); margin: 6px 0; }

    /* ---- Trading cards: photo + jersey badge + name plate ---- */
    .tcard-top { display: flex; gap: 12px; align-items: flex-start; }
    .tcard-photo { position: relative; width: 76px; height: 76px;
                   flex-shrink: 0; }
    .tcard-photo img { width: 76px; height: 76px; object-fit: cover;
                       border-radius: 14px; border: 2px solid var(--gold);
                       background: #1c1c20; }
    .tcard-initials { width: 76px; height: 76px; border-radius: 14px;
                      background: #232327; border: 2px solid var(--line);
                      display: flex; align-items: center; justify-content: center;
                      font-weight: 800; font-size: 1.5em; color: var(--gold); }
    .jersey-badge { position: absolute; right: -7px; bottom: -7px;
                    background: var(--gold); color: #111; font-weight: 800;
                    font-size: 0.82em; border-radius: 999px; min-width: 27px;
                    height: 27px; display: flex; align-items: center;
                    justify-content: center; padding: 0 6px;
                    border: 2px solid #141416;
                    font-variant-numeric: tabular-nums; }
    .tcard-id { flex: 1; min-width: 0; }
    .tcard-name { font-size: 1.08em; font-weight: 800; line-height: 1.2; }
    .tcard-pos { color: var(--ink-dim); font-weight: 700; font-size: 0.8em;
                 margin-left: 7px; letter-spacing: 0.06em; }
    .pc-cold { color: #C46A6A; font-size: 0.88em; margin-top: 8px;
               font-weight: 600; }
    .pc-edge-line { color: var(--ink-dim); font-size: 0.85em; margin-top: 8px;
                    line-height: 1.45; }
    .edge-why { margin-top: 8px; font-size: 0.85em; }
    .edge-why summary { color: #C9A227; cursor: pointer; font-weight: 600;
                        list-style: none; }
    .edge-why summary::-webkit-details-marker { display: none; }
    .edge-why summary::before { content: "+ "; font-weight: 800; }
    .edge-why[open] summary::before { content: "\2212  "; }
    .edge-why-body { color: var(--ink-dim); margin-top: 6px;
                     line-height: 1.55; }
    .prob-line { margin-top: 7px; }
    .prob-num { color: var(--ink); font-weight: 800; font-size: 1.02em;
                font-variant-numeric: tabular-nums;
                text-shadow: 0 0 16px rgba(201,162,39,.5); }
    .prob-cap { color: var(--ink-dim); font-size: 0.66em;
                letter-spacing: 0.14em; font-weight: 700; margin-left: 5px; }

    /* Pills/chips: rounded, gold when selected */
    div[data-testid="stPills"] button { border-radius: 999px; }
    div[data-testid="stPills"] button[aria-pressed="true"] {
        background: var(--gold); color: #111; border-color: var(--gold);
        font-weight: 700; }

    /* Phone: tighter padding, full-width cards, floating bottom tab bar */
    @media (max-width: 640px) {
        .block-container { padding-left: 0.9rem; padding-right: 0.9rem;
                           padding-bottom: 110px; }
        .pick-card { padding: 12px; }
        .ev-big { font-size: 1.25em; }
        [data-testid="stTabs"] [role="tablist"] {
            position: fixed; top: auto; bottom: 0; left: 0; right: 0;
            border-radius: 20px 20px 0 0; border: none;
            border-top: 1px solid var(--line);
            padding: 10px 10px calc(10px + env(safe-area-inset-bottom));
            background: rgba(14,14,17,.97); z-index: 200; }
        div[data-testid="stTab"] { padding: 10px 14px !important; }
        div[data-testid="stTab"] p { font-size: 0.85em; }
    }
    </style>""",
    unsafe_allow_html=True,
)


def key_status() -> dict:
    return {
        "ODDS_API_KEY": bool(os.environ.get("ODDS_API_KEY")),
        "LUMIFY_API_KEY": bool(os.environ.get("LUMIFY_API_KEY")),
    }


def _load_dists(model_mode: str) -> dict:
    # Learn mode: the model ("how good is this player lately?") lives in
    # two places. "sample" = bundled demo projections (works offline).
    # "live" = projections/live_distributions.json, built by
    # `python -m projections.build` from real nflverse data.
    if model_mode == "live":
        live_path = os.path.join("projections", "live_distributions.json")
        if os.path.exists(live_path):
            with open(live_path) as f:
                return json.load(f)
        return {}
    with open(os.path.join("projections", "samples",
                           "player_distributions.json")) as f:
        return json.load(f)["projections"]


@st.cache_data(show_spinner="Pulling props board...")
def _live_board():
    # The raw normalized board (with per-book lines), for the alerts
    # snapshot/check. Same graceful rules as run_scan: live when keyed,
    # sample data on failure — and the note says which.
    try:
        board = lumify.normalize(lumify.get_player_props())
        note = None
    except Exception:
        board = lumify.normalize(lumify.load_sample())
        # User-safe copy (see run_scan): no exception types for the public.
        note = "Couldn't reach the live props feed — showing sample data."
    return board, note


@st.cache_data(show_spinner="Running EV scan...")
def run_scan(model_mode: str, min_ev_pct: float):
    # Moneylines degrade gracefully: no key or dead API -> clear notice,
    # props-only scan. The adapter stays intact for when a key arrives.
    ml_games, ml_note = the_odds_api.get_moneylines_strict()
    ml_picks = engine.rank_moneylines(ml_games, min_ev=min_ev_pct / 100)
    # Props are the live source right now (Lumify). If the pull fails
    # (dead API, bad key), fall back to sample data and say so — a dead
    # feed is a UI state, never a crash, and never leaks key material.
    # If the pull succeeds but the board is empty (no upcoming games with
    # posted props — books usually post Thursday), say THAT instead of
    # pretending the market is sharp.
    props_note = None
    board_empty_live = False
    try:
        raw_props = lumify.get_player_props()
        props = lumify.normalize(raw_props)
        if not props and os.environ.get("LUMIFY_API_KEY"):
            board_empty_live = True
            props_note = ("No upcoming NFL games have posted player props "
                          "yet — books usually post them on Thursdays. "
                          "Nothing is hidden; there is just no board right now.")
    except Exception:
        props = lumify.normalize(lumify.load_sample())
        # User-safe copy: no exception types for the public. Dev detail
        # (which feed failed) is visible in dev mode via key_status.
        props_note = ("Couldn't reach the live props feed — "
                      "showing sample props for now.")
    dists = _load_dists(model_mode)
    prop_picks = engine.rank_props(props, dists, min_ev=min_ev_pct / 100)
    return ml_picks, prop_picks, ml_note, props_note, board_empty_live


@st.cache_data(show_spinner="Scanning fades...")
def run_fades(model_mode: str, max_neg_ev_pct: float):
    # The spots to stay away from: props priced against you. Reuses the
    # cached board (no second odds pull) and the same distributions.
    # Returns the most negative EV flags, worst first. NOT picks.
    board, _note = _live_board()
    dists = _load_dists(model_mode)
    return engine.rank_fades(board, dists, max_ev=max_neg_ev_pct / 100)


def pick_title(p: dict) -> str:
    if p["type"] == "prop":
        return f"{p['player']} {p['side']} {p['line']} {p['label']}"
    return f"{p['team']} moneyline"


# ---------- Scan-tab helpers: form bars, hit rates, matchups ----------
# Learn mode: the Scan tab is the "front page". Each pick card shows a
# mini last-N bar chart (green = beat the line, red = missed it) and a
# hit rate vs the line — the friendliest way to read recent form.
from ui import cards as ui_cards


def _player_stats_cached() -> bool:
    """True if the nflverse player-stats parquet is on disk.

    The Scan tab must NEVER trigger a multi-hundred-MB download just to
    draw the mini form bars — if the cache isn't there, the cards render
    without bars and say so.
    """
    import glob

    return bool(
        glob.glob(os.path.join("data", "nflverse", "player_stats*.parquet"))
    )


@lru_cache(maxsize=512)
def _window_games(player: str, window: str) -> list:
    """Past games for the mini-bars, oldest first.

    window: "Last 5" | "Last 10" | "Season" (all REG games this season).
    Returns list of dicts with the stat columns (may be empty).
    """
    from players import profiles
    import polars as pl

    if window == "Season":
        season, _ = _cur_week()
        df = _player_stats_df()
        cols = ["season", "week"] + [
            c for c in profiles.GAMELOG_COLS if c in df.columns
        ]
        games = (
            df.filter(
                (pl.col("player_display_name") == player)
                & (pl.col("season") == season)
                & (pl.col("season_type") == "REG")
            )
            .select(cols)
            .sort(["season", "week"])
        )
        return games.to_dicts()
    n = 5 if window == "Last 5" else 10
    log = profiles.game_log(_player_stats_df(), player, last_n=n)
    return list(reversed(log))  # game_log is newest-first; bars read oldest-first


@lru_cache(maxsize=2)
def _team_name_to_abbr() -> dict:
    """Full team name -> abbr ("Buffalo Bills" -> "BUF"), best effort."""
    mapping = {}
    for t in _teams_list():
        mapping[t["abbr"]] = t["abbr"]
        if t.get("name"):
            mapping[t["name"]] = t["abbr"]
    return mapping


def _matchup_str(team_full: str) -> str:
    """'vs KC · wk 6' for a pick card header; '' when unknown."""
    try:
        from players import profiles

        abbr = _team_name_to_abbr().get(team_full or "")
        if not abbr:
            return ""
        season, week = _cur_week()
        mu = profiles.upcoming_matchup(_schedules_df(), abbr, season, week)
        if mu:
            return f"{mu['home_away']} {mu['opponent']} · wk {mu['week']}"
    except Exception:
        pass
    return ""


def _card_form(p: dict, window: str) -> tuple[str, str, str]:
    """(mini-bars HTML, hit-rate HTML, cold-line HTML) for a prop pick card.

    Graceful by design: no stat mapping, no cached data, or no games ->
    empty strings, and the card renders fine without the form section.
    The cold line ("Missed 4 of last 5 vs this line") is the honest
    "what's not working" signal — a warning label, never a pick.
    """
    try:
        if not _player_stats_cached():
            return "", "", ""
        col = ui_cards.market_column(p["market"])
        if not col:
            return "", "", ""
        games = _window_games(p["player"], window)
        vals = [g[col] for g in games if g.get(col) is not None]
        if not vals:
            return "", "", ""
        bars = ui_cards.mini_bars_html(vals, p["line"], p["side"])
        hits, n = ui_cards.hit_stats(vals, p["line"], p["side"])
        pct = hits / n if n else None
        shade = ui_cards.hit_shade(pct)
        if window == "Season":
            _hn = f"{hits} of {n} this season"
        else:
            _hn = f"{hits} of last {n}"
        hit_html = (
            f'<div class="pc-hit">Hit <b>{_hn}</b> '
            f"vs this line · "
            f'<span class="{shade}">{pct:.0%}</span></div>'
        )
        _cold = ui_cards.cold_line(vals, p["line"], p["side"])
        cold_html = f"Cold: {_cold}" if _cold else ""
        return bars, hit_html, cold_html
    except Exception:
        return "", "", ""


# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Prop Analyzer")
    st.caption("NFL player props + moneyline EV scanner (v1)")
    # Key presence is computed for the mode label below, but key NAMES
    # only render in dev mode — the public never sees them.
    keys = key_status()
    if DEV_MODE:
        for k, v in keys.items():
            cls = "key-ok" if v else "key-miss"
            st.markdown(f"<span class='{cls}'>{'●' if v else '○'} {k} "
                        f"{'set' if v else 'missing — sample mode'}</span>",
                        unsafe_allow_html=True)
        st.divider()
    model_mode = st.radio("Projection model", ["sample", "live"],
                          help="'live' uses projections/live_distributions.json "
                               "(build with: python -m projections.build)")
    min_ev = st.slider("Min edge %", 0.0, 10.0, 2.0, 0.5)
    if st.button("Run scan", type="primary"):
        st.cache_data.clear()
    st.divider()
    st.caption("Paper mode: flat 1-unit stakes, max 10 plays/day. "
               "100 graded picks before real money is even discussed.")

mode_label = "SAMPLE DATA" if not any(keys.values()) else "LIVE ODDS"
st.caption(f"Mode: **{mode_label}** · model: {model_mode}")

ml_picks, prop_picks, ml_note, props_note, board_empty_live = run_scan(
    model_mode, min_ev)
all_picks = prop_picks + ml_picks

# ---------- Global player search (sidebar) ----------
with st.sidebar:
    st.divider()
    st.subheader("Player search")
    _q = st.text_input("Search all 32 teams", placeholder="e.g. allen",
                       key="player_search_box", label_visibility="collapsed")
    if _q:
        try:
            from players import search as psearch
            _hits = psearch.search_players(_rosters_df(), _q, limit=8)
            if not _hits:
                st.caption("No matches — check spelling.")
            for _h in _hits:
                _lbl = (f"{_h['name']} · {_h['team'] or ''} "
                        f"{_h['position'] or ''}".strip())
                if st.button(_lbl, key=f"srch_{_h['name']}"):
                    st.session_state["player_focus"] = _h["name"]
                    st.session_state["player_search_box"] = ""
                    st.rerun()
        except Exception:
            st.caption("Search needs the roster cache — run "
                       "`python -m players.build` once.")

(tab_scan, tab_record, tab_builder, tab_detail, tab_tracker, tab_players,
 tab_tend, tab_news, tab_alerts, tab_lab, tab_compare) = st.tabs(
    ["Scan", "Track Record", "Builder", "Pick detail", "Tracker", "Players",
     "Tendencies", "News", "Alerts", "Lab", "Compare"])

# ---------------- Scan (home) ----------------
with tab_scan:
    if ml_note:
        st.info(ml_note)
    # The empty-board note renders in the empty state below (as info),
    # not here — avoid showing it twice.
    if props_note and not board_empty_live:
        st.warning(props_note)

    # --- Suggested players strip: 100% data-driven (top EV + trending).
    # Nothing here is anyone's opinion — every suggestion carries its
    # reason string. Tapping one filters the cards below to that player.
    try:
        from players import suggest as psuggest

        _sugs = psuggest.suggestions(prop_picks, _espn_news(), _rosters_df())
    except Exception:
        _sugs = []
    if _sugs:
        st.markdown("**Worth a look this week**")
        st.caption("Hand-picked by the data — this week's sharpest +EV props "
                   "and the names buzzing in the headlines. Looks, not picks.")
        _rosters = _rosters_df()
        _scols = st.columns(min(len(_sugs), 4))
        _rendered = 0
        # Resolve the renderer defensively: a partially-updated deploy can
        # serve a new app.py against an older ui/cards.py that lacks the
        # safe renderer (live 2026-10-08: AttributeError at this exact call
        # after v6.1 shipped the fix). Missing renderer or any render
        # failure => skip the card, never break the Scan tab.
        _safe_card = getattr(ui_cards, "suggestion_card_safe", None)
        for _i, _s in enumerate(_sugs[:4]):
            with _scols[_i % 4]:
                try:
                    _card = _safe_card(_s, _rosters) if _safe_card else None
                except Exception:
                    _card = None
                if _card is None:
                    continue
                st.markdown(_card, unsafe_allow_html=True)
                _rendered += 1
                if st.button("View", key=f"scan_sug_{_s['name']}"):
                    st.session_state["scan_player"] = _s["name"]
                    st.rerun()
        if _rendered:
            st.divider()

    # --- Friendly explainer (BettingPros-style "what is edge?").
    with st.expander("What is +EV?"):
        st.markdown(
            "+EV means a bet is priced **in your favor**. If our model says "
            "a prop hits 55% of the time, the fair price is about −122. If a "
            "book offers −110, you're getting a better price than the bet is "
            "worth — repeat that hundreds of times and the gap is the edge.\n\n"
            "How we find it: we build the fair price from 2015–present stats "
            "(injuries factored in), shop every book for the best line, and "
            "only flag gaps of 2% or more. Nothing here is a lock — it's "
            "math, not a crystal ball.")

    # --- Player filter banner (from a suggestion tap).
    _scan_player = st.session_state.get("scan_player")
    if _scan_player:
        _fc1, _fc2 = st.columns([4, 1])
        _fc1.markdown(
            f"<div class='scan-filter'>Showing picks for "
            f"<b>{_scan_player}</b></div>",
            unsafe_allow_html=True)
        if _fc2.button("Clear", key="scan_player_clear"):
            st.session_state.pop("scan_player", None)
            st.rerun()

    # --- Chips, not settings pages: stat category, side, form window.
    _cat = st.pills("Stat", ["All", "Pass Yds", "Rush Yds", "Rec Yds",
                             "Receptions", "TDs"],
                    default="All", key="chip_cat",
                    label_visibility="collapsed")
    _cc1, _cc2 = st.columns(2)
    with _cc1:
        _side = st.pills("Side", ["All", "Over", "Under"], default="All",
                         key="chip_side", label_visibility="collapsed")
    with _cc2:
        _window = st.pills("Form", ["Last 5", "Last 10", "Season"],
                           default="Last 5", key="chip_window",
                           label_visibility="collapsed")

    # --- Board toggle: best edges vs the spots to avoid.
    _board = st.pills("Board", ["Best edges", "Fades"], default="Best edges",
                      key="chip_board", label_visibility="collapsed")
    _fades_mode = _board == "Fades"
    if _fades_mode:
        st.markdown("**Fades — spots to stay away from**")
        st.caption("Not picks — the props the model prices AGAINST you, "
                   "ranked by how negative the edge is. The cold line on "
                   "each card says what's not working.")

    picks = ui_cards.filter_picks(all_picks, _cat, _side)
    if _fades_mode:
        _fades = ui_cards.filter_picks(
            run_fades(model_mode, min_ev), _cat, _side)
        picks = _fades
    if _scan_player:
        picks = [p for p in picks if p.get("player") == _scan_player]

    if not picks:
        if board_empty_live:
            # Props board is empty because no games are posted — do NOT
            # claim "the market is sharp"; that would be dishonest.
            st.info(props_note)
        elif _scan_player:
            # "View" was tapped on a suggestion but this player has no +EV
            # flags right now (usually a news-trending name with no
            # mispriced props). Say so plainly with the player's context
            # instead of the generic empty state that looks broken.
            _bio = None
            try:
                from players import profiles as _prof
                _bio = _prof.find_player(_rosters_df(), _scan_player)
            except Exception:
                _bio = None
            _team_pos = ""
            if _bio:
                _team_pos = f" ({_bio.get('team', '')}" + \
                    (f" · {_bio.get('position', '')}"
                     if _bio.get('position') else "") + ")"
            st.info(f"No +EV flags for **{_scan_player}**{_team_pos} at the "
                    f"current threshold — the market has this one priced "
                    f"right, so there's nothing to show. That's a result "
                    f"too. Their full profile lives in the **Players** tab.")
        elif not all_picks and not _fades_mode:
            st.info("No +EV flags at the current threshold. The market is "
                    "sharp today — that's a result too.")
        elif _fades_mode:
            st.info("No fade flags at this threshold — nothing on the "
                    "board is priced badly enough to warn about.")
        else:
            st.info("No flags match these filters — try widening the net.")
    else:
        if not _fades_mode and st.button(f"Log {len(picks)} picks to paper tracker"):
            n = sum(1 for p in picks if db.log_pick(p))
            st.success(f"Logged {n} paper picks (1 unit each).")
        from players import headshots as _hs

        for i, p in enumerate(picks):
            # Trading-card anatomy (phone-first, single column):
            # photo + jersey badge + name/position/team/matchup → side +
            # line + odds → hero EDGE% → book → cold line → mini last-N
            # form bars → shaded hit rate.
            _ev_cls = "ev-hero" if p["ev_pct"] >= 0 else "ev-hero neg"
            if p["type"] == "moneyline":
                st.markdown(
                    f"""<div class="pick-card">
                    <div class="pc-head"><b>{html.escape(str(p['team']))}</b>
                    <span class="pc-team">moneyline · {html.escape(str(p['game']))}</span></div>
                    <div class="pc-mid">
                      <div><div class="pc-bet">{p['price']:+}</div>
                      <div class="pc-book">Best: <b>{html.escape(str(p['book']))}</b>
                      <span class="pc-team">(worst {p['worst_price']:+})</span>
                      </div></div>
                      <div class="pc-hero"><div class="{_ev_cls}">"""
                    f"""+{p['ev_pct']:.2f}%</div>"""
                    f"""<div class="ev-cap">EDGE</div></div>
                    </div>
                    {ui_cards.edge_line_html(p, source="sharp")}
                    {ui_cards.edge_explainer_html(p, source="sharp")}
                    </div>""",
                    unsafe_allow_html=True)
            else:
                _mu = _matchup_str(p.get("team"))
                _mu_html = (f" · {_mu}" if _mu
                            else f" · {html.escape(str(p.get('team', '')))}")
                _bars, _hit, _cold = _card_form(p, _window)
                st.markdown(
                    ui_cards.trading_card_html(
                        p,
                        matchup_html=_mu_html,
                        bars=_bars,
                        hit_html=_hit,
                        cold_html=_cold,
                        photo_b64=_hs.headshot_b64(p["player"], _rosters_df()),
                        jersey=_hs.jersey_number(p["player"], _rosters_df()),
                        position=_hs.position_abbr(p["player"], _rosters_df()),
                        negative=_fades_mode,
                    ),
                    unsafe_allow_html=True)
            if p.get("injury_flag"):
                _flag = html.escape(str(p["injury_flag"]))
                st.markdown(f"<span class='flag-warn'>{_flag}</span>",
                            unsafe_allow_html=True)
            if st.button("Details", key=f"det_{i}"):
                st.session_state["selected_pick"] = p
                st.rerun()

# ---------------- Track Record (the public proof page) ----------------
with tab_record:
    st.subheader("Track Record")
    st.caption("We publish every pick. Grade us.")
    st.caption("Every model flag is logged here with its line at pick time "
               "and graded after the game — wins, losses, and CLV. No "
               "cherry-picking: the log below is the complete record the "
               "totals are built from.")

    _tr = db.track_record()
    _r1, _r2, _r3 = st.columns(3)
    _r1.metric("Win rate",
               f"{_tr['win_rate']:.1%}" if _tr["win_rate"] is not None else "—")
    _r2.metric("ROI (paper units)",
               f"{_tr['roi']:+.1%}" if _tr["roi"] is not None else "—")
    _r3.metric("Profit (units)", f"{_tr['profit_units']:+.2f}")
    _r4, _r5, _r6 = st.columns(3)
    _r4.metric("Avg CLV (pts)",
               f"{_tr['avg_clv_pts']:+.4f}"
               if _tr["avg_clv_pts"] is not None else "—")
    _r5.metric("Avg EV at log",
               f"{_tr['avg_ev_pct']:+.2f}%"
               if _tr["avg_ev_pct"] is not None else "—")
    _r6.metric("Picks graded", _tr["picks_graded"])
    st.caption("CLV = closing line value: did the market move our way after "
               "we logged it? Positive = we beat the market = skill signal.")

    # The 100-pick gate, shown honestly.
    _g = _tr["picks_graded"]
    st.progress(min(_g / _tr["gate_target"], 1.0),
                text=(f"{_g} of {_tr['gate_target']} graded — early days. "
                      f"Every pick makes the record stronger."
                      if not _tr["gate_done"]
                      else f"{_tr['gate_target']}-pick gate cleared — "
                           f"the record speaks for itself"))

    st.divider()
    _trows = db.all_picks()
    if _trows:
        import pandas as pd

        st.markdown("**Every pick**")
        st.dataframe(pd.DataFrame(_trows)[
            ["logged_at", "label", "book", "line", "price", "ev_pct",
             "closing_price", "result", "profit_units", "clv_pts"]],
            use_container_width=True, hide_index=True)
        st.caption("price = our logged odds · closing_price = near kickoff · "
                   "clv_pts = implied-probability points in our favor")
    else:
        st.info("The record starts empty — every pick you log makes it "
                "stronger. Run a scan, log the flags, and this page grades "
                "them all in public. Nothing hidden, nothing cherry-picked.")

# ---------------- Builder (SGP-style, FREE to build) ----------------
with tab_builder:
    from builder import legs as blegs
    from builder import saves as bsaves
    from compare import compare as cmp_mod

    st.subheader("Prop builder")
    st.caption("Assemble a same-game parlay leg by leg. Each leg is priced "
               "with our model — the combined number assumes the legs are "
               "independent, and they aren't. Read the caution.")

    if "builder_legs" not in st.session_state:
        st.session_state["builder_legs"] = []
    _blegs = st.session_state["builder_legs"]

    with st.form("add_leg", clear_on_submit=True):
        _bml = st.checkbox("Moneyline leg (instead of a player prop)")
        if _bml:
            _bp = st.text_input("Team", placeholder="e.g. Chiefs")
            _bfair = st.number_input("Your fair win % for this team",
                                     min_value=1.0, max_value=99.0,
                                     value=55.0, step=1.0)
            _bm, _bs, _bl = "moneyline", "win", 0.0
        else:
            _bp = st.text_input("Player", placeholder="e.g. Josh Allen")
            _bm = st.selectbox(
                "Stat", list(blegs.BUILDER_MARKETS.keys()),
                format_func=lambda m: blegs.BUILDER_MARKETS[m])
            _bs = st.pills("Side", ["Over", "Under"], default="Over",
                           key="bleg_side", label_visibility="collapsed")
            _bl = st.number_input("Line", value=250.0, step=0.5)
            _bfair = None
        _add = st.form_submit_button("Add leg", type="primary")

    if _add:
        if not _bp.strip():
            st.warning("Name the player (or team) first.")
        elif _bml:
            _blegs.append({
                "player": _bp.strip(), "market": "moneyline",
                "label": "Moneyline", "side": "win", "line": None,
                "fair_p": round(_bfair / 100, 4),
                "note": "your estimate — we don't model team win prob yet",
            })
            st.rerun()
        else:
            priced = blegs.price_leg(_bp.strip(), _bm, _bs.lower(),
                                     float(_bl), _load_dists(model_mode))
            if priced is None:
                st.warning(
                    f"No projection for {_bp.strip()} on "
                    f"{blegs.BUILDER_MARKETS[_bm]} — check the spelling "
                    f"(must match the roster, e.g. 'Josh Allen').")
            else:
                _blegs.append(priced)
                st.rerun()

    if not _blegs:
        st.info("No legs yet — add your first leg above. Building is free; "
                "saving the slip is Premium.")
    else:
        for _i, _leg in enumerate(_blegs):
            _c1, _c2 = st.columns([4, 1])
            if _leg["market"] == "moneyline":
                _desc = (f"**{_leg['player']}** moneyline — your fair "
                         f"estimate **{_leg['fair_p']:.0%}**")
            else:
                _desc = (f"**{_leg['player']}** {_leg['side']} "
                         f"{_leg['line']:g} "
                         f"{blegs.BUILDER_MARKETS.get(_leg['market'], _leg['market'])}"
                         f" — fair P **{_leg['fair_p']:.1%}**")
            _c1.markdown(_desc)
            if _c2.button("Remove", key=f"bleg_rm_{_i}"):
                _blegs.pop(_i)
                st.rerun()

        _combo = blegs.combine_legs([l["fair_p"] for l in _blegs])
        st.markdown(f"### Combined fair P: {_combo['combined_p']:.1%} "
                    f"(naive, {_combo['n_legs']} legs)")
        # Honesty requirement: the caution is ALWAYS shown with the number.
        st.warning(_combo["caution"])

        _book = st.number_input(
            "Book's SGP price (American odds — optional)",
            value=0, step=10,
            help="The combined odds your book offers, e.g. +260. We only "
                 "do the math; the bet itself happens on their site.")
        _ev = None
        if _book:
            _ev = blegs.sgp_ev(_combo["combined_p"], float(_book))
            st.metric("SGP EV%", f"{_ev['ev_pct']:+.2f}%")
            st.caption(f"Fair {_combo['combined_p']:.1%} vs book "
                       f"{_book:+.0f} ({_ev['book_decimal']:.2f}x). The "
                       f"correlation caution applies to this EV too.")

        st.divider()
        # Saving builds is premium; building is free.
        if not cmp_mod.is_unlocked():
            st.markdown(ui_cards.premium_lock_html(
                "Saved builds",
                ["Name and keep your SGP slips",
                 "Reload them anytime — stop rebuilding from scratch"]),
                unsafe_allow_html=True)
        else:
            _nm = st.text_input("Name this build",
                                placeholder="e.g. Allen Sunday special")
            if st.button("Save build", type="primary"):
                try:
                    bsaves.save_build(
                        _nm, _blegs, _combo["combined_p"],
                        float(_book) if _book else None,
                        _ev["ev_pct"] if _ev else None)
                    st.success(f"Saved '{_nm.strip()}'.")
                except ValueError as e:
                    st.warning(str(e))
            _saved = bsaves.list_builds()
            if _saved:
                st.markdown("**Saved builds**")
                for _s in _saved:
                    _sc1, _sc2 = st.columns([4, 1])
                    _ev_txt = (f" · EV {_s['ev_pct']:+.1f}%"
                               if _s["ev_pct"] is not None else "")
                    _sc1.markdown(f"**{_s['name']}** — {len(_s['legs'])} "
                                  f"legs · fair {_s['combined_p']:.1%}"
                                  f"{_ev_txt}")
                    if _sc2.button("Delete", key=f"bsave_del_{_s['id']}"):
                        bsaves.delete_build(_s["id"])
                        st.rerun()

# ---------------- Pick detail ----------------
with tab_detail:
    # "Details" on a Scan card stores the pick itself (filters change the
    # list order, so a bare index would point at the wrong pick).
    _sel = st.session_state.get("selected_pick")
    if _sel is None:
        idx = st.session_state.get("selected", 0)
        _sel = all_picks[min(idx, len(all_picks) - 1)] if all_picks else None
    if _sel is None:
        st.info("Run a scan first — no picks to inspect.")
    else:
        p = _sel
        st.subheader(pick_title(p))
        c1, c2, c3 = st.columns(3)
        c1.metric("Edge (EV%)", f"{p['ev_pct']:+.2f}%")
        c2.metric("Book price", f"{p['price']:+} @ {p['book']}")
        c3.metric("Fair price", f"{p['fair_american']:+.0f}")
        st.markdown("**The math**")
        st.code(p["math"])
        if p.get("injury_flag"):
            st.warning(p["injury_flag"])
        if p["type"] == "moneyline":
            st.caption(f"Line shopping: best {p['price']:+} vs worst {p['worst_price']:+} "
                       f"— {p['shop_uplift_pct']:+.2f}% payout uplift just for picking the book.")
        else:
            st.caption(f"Projection based on {p.get('n_games', '?')} games "
                       f"(recency-weighted, 2015–present).")

# ---------------- Tracker ----------------
with tab_tracker:
    s = db.weekly_summary(days=7)
    st.subheader("Paper record — last 7 days")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Picks logged", s["picks_logged"])
    m2.metric("Win rate", f"{s['win_rate']:.1%}" if s["win_rate"] is not None else "—")
    m3.metric("Profit (units)", f"{s['profit_units']:+.2f}")
    m4.metric("Avg CLV (pts)", f"{s['avg_clv_pts']:+.4f}" if s["avg_clv_pts"] is not None else "—")
    st.caption(f"ROI: {s['roi']:+.1%}" if s["roi"] is not None else "ROI: —")
    st.progress(min(s["picks_graded"] / 100, 1.0),
                text=f"{s['picks_graded']}/100 graded picks before real money is discussed")
    st.divider()
    rows = db.all_picks()
    if rows:
        import pandas as pd

        df = pd.DataFrame(rows)
        st.dataframe(df[["logged_at", "label", "book", "line", "price",
                         "ev_pct", "closing_price", "result",
                         "profit_units", "clv_pts"]],
                     use_container_width=True, hide_index=True)
    else:
        st.info("No paper picks logged yet. Run a scan and log the flags.")

# ---------------- Players ----------------
with tab_players:
    from players import profiles
    from players import search as psearch
    from players import suggest as psuggest
    from players import preseason as preseason_mod

    st.subheader("Player profiles — all 32 teams")

    # --- Suggested players: this week's +EV props + headlines ---
    try:
        _sugs = psuggest.suggestions(prop_picks, _espn_news(), _rosters_df())
        if _sugs:
            st.markdown("**Suggested**")
            st.caption("From this week's +EV props and current headlines — "
                       "players worth a look, not picks.")
            _scols = st.columns(min(len(_sugs), 4))
            for _i, _s in enumerate(_sugs[:8]):
                with _scols[_i % 4]:
                    if st.button(f"{_s['name']}",
                                 help=_s["reason"], key=f"sug_{_s['name']}"):
                        st.session_state["player_focus"] = _s["name"]
                        st.rerun()
            st.divider()
    except Exception:
        pass  # suggestions are a nicety; the tab works without them

    try:
        teams = _teams_list()
        # A sidebar-search or suggestion click pre-selects team + player.
        _focus = st.session_state.pop("player_focus", None)
        _focus_team, _focus_name = None, None
        if _focus:
            _fbio = profiles.find_player(_rosters_df(), _focus)
            if _fbio:
                _focus_team, _focus_name = _fbio.get("team"), _fbio.get("name")
        _abbrs = [t["abbr"] for t in teams]
        team_abbr = st.selectbox(
            "Team", _abbrs,
            index=_abbrs.index(_focus_team) if _focus_team in _abbrs else 0,
            format_func=lambda a: next(
                (f"{t['abbr']} — {t['name']}" for t in teams
                 if t["abbr"] == a), a))
        roster = profiles.get_roster(_rosters_df(), team_abbr)
        names = [p["name"] for p in roster if p["name"]]
        player_name = st.selectbox(
            "Player", names,
            index=names.index(_focus_name) if _focus_name in names else 0)
        if player_name:
            season, week = _cur_week()
            bio = profiles.find_player(_rosters_df(), player_name)
            if bio:
                st.markdown(f"### {bio['name']} "
                            f"<span style='color:#C9A227'>#{bio['jersey'] or ''} "
                            f"{bio['position'] or ''} · {bio['team'] or ''}</span>",
                            unsafe_allow_html=True)
                if bio.get("status") and bio["status"] != "Active":
                    st.warning(f"Roster status: {bio['status']}")
            inj = profiles.latest_injury_status(_injuries_df(), player_name,
                                                team_abbr, season, week)
            if inj and inj.get("status"):
                st.warning(f"Injury report (wk {inj['week']}): **{inj['status']}**"
                           f" — {inj.get('details') or ''}")

            st.markdown("**Season averages (per game)**")
            avgs = profiles.season_averages(_player_stats_df(), player_name, season)
            if avgs.get("games"):
                import pandas as pd
                st.dataframe(pd.DataFrame([avgs]), use_container_width=True,
                             hide_index=True)
            else:
                st.caption("No regular-season snaps yet this year.")

            st.markdown("**Game log**")
            window = st.radio("Last N games", [5, 10, 15], horizontal=True,
                              key="gamelog_window")
            log = profiles.game_log(_player_stats_df(), player_name, last_n=window)
            if log:
                import pandas as pd
                st.dataframe(pd.DataFrame(log), use_container_width=True,
                             hide_index=True)
            else:
                st.caption("No game log available.")

            mu = profiles.upcoming_matchup(_schedules_df(), team_abbr, season, week)
            if mu:
                st.caption(f"Next: {mu['home_away']} {mu['opponent']} "
                           f"(wk {mu['week']}, {mu['date']})")

            st.markdown("**Related headlines**")
            try:
                from news import espn as news_mod
                hits = news_mod.news_for_player(_espn_news(), player_name)[:3]
                for h in hits:
                    st.markdown(f"- [{h['headline']}]({h['link']})")
                if not hits:
                    st.caption("No recent headlines mention this player.")
            except Exception:
                st.caption("News feed unavailable right now.")
    except Exception as e:
        st.info("Player data isn't cached yet — run `python -m players.build` "
                f"once to download it (free). ({e})")

    with st.expander("Preseason data — what's actually available"):
        for line in preseason_mod.summary_lines():
            st.caption(line)

# ---------------- Tendencies ----------------
with tab_tend:
    from tendencies import team as tteam
    from tendencies import player as tplayer
    from tendencies import plays as tplays

    st.subheader("Tendencies — the way they play")
    SEASONS_KEY = "2024,2025,2026"
    try:
        teams = _teams_list()
        t_abbr = st.selectbox("Team", [t["abbr"] for t in teams], key="tend_team")
        pbp = _pbp_df(SEASONS_KEY)

        splits = tteam.run_pass_splits(pbp, t_abbr)
        c1, c2, c3 = st.columns(3)
        c1.metric("Run rate", f"{splits['run_rate']:.1%}" if splits.get("run_rate") is not None else "—")
        c2.metric("Pass rate", f"{splits['pass_rate']:.1%}" if splits.get("pass_rate") is not None else "—")
        c3.metric("Snaps (sample)", splits.get("snaps", 0))
        st.markdown("**Run/pass by down**")
        import pandas as pd
        st.dataframe(pd.DataFrame([
            {"down": d, "snaps": v["snaps"],
             "run%": f"{v['run_rate']:.0%}" if v["run_rate"] is not None else "—",
             "pass%": f"{v['pass_rate']:.0%}" if v["pass_rate"] is not None else "—"}
            for d, v in splits.get("by_down", {}).items()
        ]), use_container_width=True, hide_index=True)
        st.markdown("**Run/pass by distance**")
        st.dataframe(pd.DataFrame([
            {"distance": d, "snaps": v["snaps"],
             "run%": f"{v['run_rate']:.0%}" if v["run_rate"] is not None else "—",
             "pass%": f"{v['pass_rate']:.0%}" if v["pass_rate"] is not None else "—"}
            for d, v in splits.get("by_distance", {}).items()
        ]), use_container_width=True, hide_index=True)

        fp = tteam.formation_proxies(pbp, t_abbr)
        pc = tteam.pace(pbp, t_abbr)
        f1, f2, f3 = st.columns(3)
        f1.metric("Shotgun rate", f"{fp['shotgun_rate']:.0%}" if fp.get("shotgun_rate") is not None else "—")
        f2.metric("No-huddle rate", f"{fp['no_huddle_rate']:.0%}" if fp.get("no_huddle_rate") is not None else "—")
        f3.metric("Snaps/game", pc.get("snaps_per_game") or "—")
        st.caption(fp.get("personnel_note", ""))

        st.markdown("**Most-used play types**")
        st.caption(tplays.HONEST_LABEL)
        mut = tplays.most_used_play_types(pbp, team=t_abbr, top_n=10)
        st.dataframe(pd.DataFrame([
            {"play type": m["play_type"], "share": f"{m['share']:.1%}",
             "count": m["count"]} for m in mut
        ]), use_container_width=True, hide_index=True)

        st.markdown("**Player style**")
        pname = st.text_input("Player name", key="style_player",
                              placeholder="e.g. Josh Allen")
        if pname:
            season, _ = _cur_week()
            style = tplayer.style_from_weekly(_player_stats_df(), pname, season)
            if style.get("games"):
                s1, s2, s3 = st.columns(3)
                s1.metric("aDOT", style.get("adot") or "—")
                s2.metric("YAC/rec", style.get("yac_per_reception") or "—")
                s3.metric("Catch rate", f"{style['catch_rate']:.0%}" if style.get("catch_rate") else "—")
                st.caption(f"{style['games']} games · "
                           f"{style.get('targets_per_game')} targets/gm · "
                           f"{style.get('yards_per_reception')} yds/rec")
                st.caption(style.get("slot_note", ""))
            else:
                st.caption("No stats for that name this season — check spelling.")
    except Exception as e:
        st.info("Tendency data needs charted play-by-play — it downloads on "
                f"first use (free, ~50MB/season, cached). ({e})")

# ---------------- News ----------------
with tab_news:
    from news import espn as news_mod

    st.subheader("NFL news + injury report")
    try:
        articles = _espn_news()
        for a in articles[:12]:
            st.markdown(f"**[{a['headline']}]({a['link']})**")
            if a.get("description"):
                st.caption(a["description"][:220])
        st.divider()
        st.markdown("**Injury report (latest)**")
        season, week = _cur_week()
        rep = news_mod.get_injury_report(_injuries_df(), season, week)
        if rep:
            import pandas as pd
            st.dataframe(pd.DataFrame([{
                "player": r["player"], "team": r["team"],
                "pos": r["position"], "status": r["status"],
                "details": (r["details"] or "")[:80]} for r in rep[:40]
            ]), use_container_width=True, hide_index=True)
            st.caption(f"Week {rep[0]['week']} report · {len(rep)} players listed · "
                       "source: nflverse (same feed the projections read)")
        else:
            st.caption("No injury report rows for this week yet.")
    except Exception as e:
        st.info(f"News feed unavailable right now. ({e})")

# ---------------- Alerts: line-movement watchlist (FREE) ----------------
with tab_alerts:
    from alerts import watchlist as wl
    from builder import legs as _blegs_mod

    st.subheader("Line-movement alerts")
    st.caption("Free. Books move lines on news and sharp money — snapshot "
               "the board, come back later, and see what moved. "
               "Push notifications are the next step (needs scheduled runs).")
    with st.form("watch_add", clear_on_submit=True):
        _wa, _wb = st.columns(2)
        _wp = _wa.text_input("Player", placeholder="e.g. Josh Allen")
        _wm = _wb.selectbox(
            "Stat", list(_blegs_mod.BUILDER_MARKETS.keys()),
            format_func=lambda m: _blegs_mod.BUILDER_MARKETS[m])
        _wadd = st.form_submit_button("Watch")
    if _wadd:
        try:
            wl.add_watch(_wp, _wm)
            st.success(f"Watching {_wp.strip()} "
                       f"({_blegs_mod.BUILDER_MARKETS[_wm]}).")
            st.rerun()
        except ValueError as e:
            st.warning(str(e))

    _watched = wl.list_watch()
    if _watched:
        for _w in _watched:
            _wc1, _wc2 = st.columns([4, 1])
            _wc1.markdown(f"**{_w['player']}** — "
                          f"{_blegs_mod.BUILDER_MARKETS.get(_w['market'], _w['market'])}")
            if _wc2.button("Remove", key=f"watch_rm_{_w['player']}_{_w['market']}"):
                wl.remove_watch(_w["player"], _w["market"])
                st.rerun()
    else:
        st.info("Watchlist is empty — add a player above.")

    st.divider()
    _bc1, _bc2 = st.columns(2)
    if _bc1.button("Snapshot current lines", type="primary"):
        _board, _note = _live_board()
        _n = wl.snapshot_board(_board)
        st.success(f"Snapshotted {_n} watched lines.")
    if _bc2.button("Check for movements"):
        _board, _note = _live_board()
        _alerts = wl.detect_movements(_board)
        if not _alerts:
            st.info("No snapshot yet, or nothing moved past the "
                    "thresholds (1.5 pts / 10¢).")
        for _a in _alerts:
            st.markdown(
                f"<div class='pick-card'><b>{_a['player']}</b> "
                f"<span class='pc-team'>{_a['market']} @ {_a['book']}</span><br>"
                + "<br>".join(f"· {r}" for r in _a["reasons"])
                + "</div>",
                unsafe_allow_html=True)

# ---------------- Lab: backtest calibration (PREMIUM) ----------------
with tab_lab:
    from backtest import lab as blab
    from compare import compare as cmp_mod

    st.subheader("Backtest lab")
    if not cmp_mod.is_unlocked():
        st.markdown(ui_cards.premium_lock_html(
            "Backtest lab",
            ["Walk-forward calibration of the model over past weeks",
             "Hit-rate by probability bucket + Brier score"]),
            unsafe_allow_html=True)
    else:
        st.caption("Does 'the model says 60%' actually happen 60% of the "
                   "time? We rebuild every projection using only games "
                   "before each week — no peeking.")
        season, cur_week = _cur_week()
        _max_wk = max(cur_week - 1, 2)
        _w1, _w2 = st.slider("Week range", 1, _max_wk,
                             (max(_max_wk - 3, 1), _max_wk),
                             key="lab_weeks")
        if st.button("Run calibration", type="primary"):
            with st.spinner("Running walk-forward calibration..."):
                try:
                    res = blab.run_lab(_player_stats_df(), season, _w1, _w2)
                except Exception as e:
                    st.info(f"Lab needs cached player stats — run "
                            f"`python -m projections.build` first. ({e})")
                    res = None
            if res:
                _lc1, _lc2 = st.columns(2)
                _lc1.metric("Brier score",
                            f"{res['brier']:.4f}" if res["brier"] is not None else "—")
                _lc2.metric("Predictions", res["n_predictions"])
                st.caption("Brier: 0 = perfect, 0.25 = coin flip. Lower wins.")
                import pandas as pd

                _mrows = [
                    {"Market": m["label"], "n": m["n"],
                     "Brier": m["brier"],
                     "Hit rate": (f"{m['base_rate']:.1%}"
                                  if m["base_rate"] is not None else "—")}
                    for m in res["markets"].values() if m["n"]
                ]
                if _mrows:
                    st.markdown("**Calibration by market**")
                    st.dataframe(pd.DataFrame(_mrows),
                                 use_container_width=True, hide_index=True)
                if res["buckets"]:
                    st.dataframe(pd.DataFrame(res["buckets"]),
                                 use_container_width=True, hide_index=True)
                    st.caption("Predicted = model's average fair P in the "
                               "bucket. Actual = how often it hit. Close "
                               "together = well calibrated.")
                else:
                    st.info("No predictions in that range — try more weeks.")
                st.caption(res["note"])

# ---------------- Compare (PREMIUM) ----------------
with tab_compare:
    import config
    from compare import compare as cmp_mod

    st.subheader("Compare players")
    if not cmp_mod.is_unlocked():
        st.markdown("""<div class="pick-card" style="border-color:#C9A227">
            <span class="ev-big">Premium</span><br>
            Side-by-side player comparison lives here.</div>""",
                    unsafe_allow_html=True)
        for t in config.PREMIUM_TEASER:
            st.markdown(f"- {t}")
        st.caption("Free tier covers the EV scan, player profiles, tendencies "
                   "and news. Compare unlocks with Premium — flip "
                   "`PREMIUM_ENABLED` in config.py (no payments built yet).")
    else:
        try:
            season, week = _cur_week()
            dists = {}
            live_path = os.path.join("projections", "live_distributions.json")
            if os.path.exists(live_path):
                with open(live_path) as f:
                    dists = json.load(f)
            c1, c2 = st.columns(2)
            name_a = c1.text_input("Player A", value="Josh Allen")
            name_b = c2.text_input("Player B", value="Lamar Jackson")
            if st.button("Compare", type="primary"):
                ctx = {"rosters_df": _rosters_df(),
                       "player_stats_df": _player_stats_df(),
                       "distributions": dists,
                       "prop_picks": prop_picks,
                       "season": season, "week": week}
                res = cmp_mod.compare_players(name_a, name_b, ctx)
                pa, pb = res["players"]
                st.markdown(f"### {pa['bio'].get('name')} "
                            f"vs {pb['bio'].get('name')}")
                import pandas as pd
                st.dataframe(pd.DataFrame([
                    {"stat": r["stat"], name_a: r["a"], name_b: r["b"]}
                    for r in res["stat_rows"]
                ]), use_container_width=True, hide_index=True)
                e1, e2 = st.columns(2)
                with e1:
                    st.markdown(f"**{name_a} prop EVs**")
                    for e in pa["prop_evs"] or [{"label": "none flagged"}]:
                        st.caption(f"{e.get('label','')}: "
                                   f"{e.get('ev_pct','')}%" if "ev_pct" in e
                                   else "No +EV props flagged")
                with e2:
                    st.markdown(f"**{name_b} prop EVs**")
                    for e in pb["prop_evs"] or [{"label": "none flagged"}]:
                        st.caption(f"{e.get('label','')}: "
                                   f"{e.get('ev_pct','')}%" if "ev_pct" in e
                                   else "No +EV props flagged")
        except Exception as e:
            st.info(f"Compare needs data cached — run `python -m players.build` "
                    f"first. ({e})")
