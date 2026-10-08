"""Player profiles — the "baseball card" for every rostered NFL player.

Learn-mode tour:
  - get_teams()       -> the 32 current teams (nflverse lists a few
                         historical ones too, so we filter by "has a
                         current roster").
  - get_roster()      -> every rostered player: name, position, team,
                         jersey, status.
  - find_player()     -> bio lookup by name (fuzzy on last name).
  - game_log()        -> weekly stat lines, most recent first, with a
                         last 5 / 10 / 15 toggle.
  - season_averages() -> per-game averages for one season.
  - upcoming_matchup()-> next scheduled game for a team.

All functions take DataFrames and return plain Python — that keeps them
unit-testable with synthetic data (see tests/test_v2.py).
"""
from __future__ import annotations

# Stat columns shown in game logs, in display order. Intersected with
# whatever the nflverse table actually has (columns shift over years).
GAMELOG_COLS = [
    "passing_yards", "passing_tds", "passing_interceptions",
    "rushing_yards", "rushing_tds", "carries",
    "receptions", "targets", "receiving_yards", "receiving_tds",
    "receiving_air_yards", "receiving_yards_after_catch",
]

VALID_WINDOWS = (5, 10, 15)

# Position -> (nflverse stat column, friendly label) for the "season
# form" line on the player spotlight card. Skill positions only — a
# lineman's card honestly shows no form line instead of a fake one.
POS_FORM_STAT = {
    "QB": ("passing_yards", "Passing yards"),
    "RB": ("rushing_yards", "Rushing yards"),
    "WR": ("receiving_yards", "Receiving yards"),
    "TE": ("receiving_yards", "Receiving yards"),
}


def normalize_name(name: str | None) -> str:
    """Name match key: lowercase, punctuation stripped.

    Books and headlines don't punctuate the way nflverse does
    ("AJ Brown" vs "A.J. Brown", "Erick All" vs "Erick All Jr." is
    handled by prefix tiers below). Comparing normalized keys instead
    of raw strings is what makes "AJ Brown" find the right player
    instead of some other Brown.
    """
    import re

    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _cols(df, want: list[str]) -> list[str]:
    have = set(df.columns)
    return [c for c in want if c in have]


def get_teams(teams_df, rosters_df) -> list[dict]:
    """The 32 current teams. nflverse's team table keeps historical rows
    (OAK, STL, SD...), so a team counts as current only if it has players
    on the latest roster."""
    import polars as pl

    current_abbrs = set(rosters_df["team"].unique().to_list())
    rows = []
    for r in teams_df.to_dicts():
        abbr = r.get("team_abbr")
        if abbr in current_abbrs:
            rows.append(
                {
                    "abbr": abbr,
                    "name": r.get("team_name"),
                    "nick": r.get("team_nick"),
                    "conf": r.get("team_conf"),
                    "division": r.get("team_division"),
                }
            )
    rows.sort(key=lambda r: r["abbr"])
    return rows


def get_roster(rosters_df, team_abbr: str | None = None) -> list[dict]:
    """Every rostered player (optionally one team)."""
    import polars as pl

    df = rosters_df
    if team_abbr:
        df = df.filter(pl.col("team") == team_abbr)
    out = []
    for r in df.to_dicts():
        out.append(
            {
                "name": r.get("full_name"),
                "first": r.get("first_name"),
                "last": r.get("last_name"),
                "team": r.get("team"),
                "position": r.get("position"),
                "depth_position": r.get("depth_chart_position"),
                "jersey": r.get("jersey_number"),
                "status": r.get("status"),
            }
        )
    out.sort(key=lambda p: (p["team"] or "", p["position"] or "", p["name"] or ""))
    return out


def _pick_row(rows: list[dict], team: str | None) -> dict | None:
    """Choose the right row when several share a name.

    Same-name players exist (8 dup full_names in the 2026 roster).
    Prefer the requested team, then Active status — deterministic,
    and it never silently returns a lineman for a wideout the way the
    old "first row wins" fallback did.
    """
    if not rows:
        return None
    if team:
        trows = [r for r in rows
                 if (r.get("team") or "").upper() == team.upper()]
        if trows:
            rows = trows
    act = [r for r in rows if (r.get("status") or "").upper() == "ACT"]
    cands = act or rows
    # Final tiebreak is alphabetical — neutral and deterministic, never
    # a popularity guess (the app doesn't do favorites).
    cands = sorted(cands, key=lambda r: r.get("full_name") or "")
    return cands[0]


def _bio_row(r: dict) -> dict:
    return {
        "name": r.get("full_name"),
        "team": r.get("team"),
        "position": r.get("position"),
        "depth_position": r.get("depth_chart_position"),
        "jersey": r.get("jersey_number"),
        "status": r.get("status"),
        "status_detail": r.get("status_description_abbr"),
    }


def find_player(rosters_df, name: str, team: str | None = None) -> dict | None:
    """Bio lookup, punctuation-blind and team-aware.

    Tiers, first hit wins:
      1. exact full_name ("Erick All")
      2. normalized full_name ("AJ Brown" -> "A.J. Brown")
      3. normalized prefix — query is the start of the roster name
         ("Chris Godwin" -> "Chris Godwin Jr.")
      4. last name — but ONLY when it identifies exactly one player
         (team-narrowed, Active preferred). "Allen" matching five guys
         returns None: an honest miss beats a wrong player.

    The old code's last-name fallback returned to_dicts()[0] — an
    arbitrary row — so "AJ Brown" resolved to Trent Brown (HOU, OL).
    Tier 2 fixes the name; tier 4's exactly-one rule fixes the row.
    """
    import polars as pl

    if not name:
        return None
    rows = rosters_df.to_dicts()

    hit = [r for r in rows if r.get("full_name") == name]
    if hit:
        return _bio_row(_pick_row(hit, team))

    want = normalize_name(name)
    if want:
        hit = [r for r in rows
               if normalize_name(r.get("full_name")) == want]
        if hit:
            return _bio_row(_pick_row(hit, team))
        # Prefix tier: the query is a leading chunk of the roster name
        # ("Chris Godwin" is how everyone writes "Chris Godwin Jr.").
        hit = [r for r in rows
               if normalize_name(r.get("full_name")).startswith(want)
               and len(want) >= 4]
        if hit:
            return _bio_row(_pick_row(hit, team))

    # Last-name tier: exactly-one-or-None (see _pick_last_name).
    last = normalize_name(name.split()[-1]) if name.split() else ""
    if len(last) > 2:
        hit = [r for r in rows if normalize_name(r.get("last_name")) == last]
        row = _pick_last_name(hit, team)
        if row:
            return _bio_row(row)
    return None


def _pick_last_name(rows: list[dict], team: str | None) -> dict | None:
    """Last-name tier picker: exactly-one-or-None.

    A bare last name ("Allen") can match several players. Guessing one
    is how the old code showed Trent Brown for "AJ Brown" — a wrong
    player presented as fact. So: narrow by team, prefer Active, and if
    several real candidates remain, return None. The UI then shows its
    honest "couldn't match this name" fallback instead of a wrong card.
    Accuracy is the product; a miss beats a wrong hit.
    """
    if team:
        trows = [r for r in rows
                 if (r.get("team") or "").upper() == team.upper()]
        if trows:
            rows = trows
    act = [r for r in rows if (r.get("status") or "").upper() == "ACT"]
    cands = act or rows
    # De-dupe to distinct players (the roster table can carry a player
    # twice across status rows).
    seen = {r.get("full_name") for r in cands}
    if len(seen) == 1:
        return cands[0]
    return None


def game_log(player_stats_df, player_name: str, last_n: int = 10) -> list[dict]:
    """Weekly stat lines, most recent first. last_n in {5, 10, 15}.

    Each row: season, week, team, opponent + the stat columns.
    Bye weeks simply don't appear (no row = didn't play).
    """
    import polars as pl

    if last_n not in VALID_WINDOWS:
        raise ValueError(f"last_n must be one of {VALID_WINDOWS}")
    cols = ["season", "week", "team", "opponent_team"] + _cols(player_stats_df, GAMELOG_COLS)
    games = (
        player_stats_df.filter(
            (pl.col("player_display_name") == player_name)
            & (pl.col("season_type") == "REG")
        )
        .select(cols)
        .sort(["season", "week"], descending=True)
        .head(last_n)
    )
    return games.to_dicts()


def season_averages(player_stats_df, player_name: str, season: int) -> dict:
    """Per-game averages for one season (REG only)."""
    import polars as pl

    cols = _cols(player_stats_df, GAMELOG_COLS)
    games = player_stats_df.filter(
        (pl.col("player_display_name") == player_name)
        & (pl.col("season") == season)
        & (pl.col("season_type") == "REG")
    )
    n = games.height
    if n == 0:
        return {"games": 0}
    avgs = {"games": n}
    for c in cols:
        vals = [v for v in games[c].to_list() if v is not None]
        avgs[c] = round(sum(vals) / n, 1) if vals else 0.0
    # Derived per-game rates people actually ask about.
    avgs["yards_per_carry"] = _safe_div(avgs.get("rushing_yards", 0), avgs.get("carries", 0))
    avgs["yards_per_reception"] = _safe_div(avgs.get("receiving_yards", 0), avgs.get("receptions", 0))
    avgs["catch_rate"] = _safe_div(avgs.get("receptions", 0), avgs.get("targets", 0))
    return avgs


def _safe_div(a: float, b: float) -> float | None:
    return round(a / b, 2) if b else None


def upcoming_matchup(schedules_df, team_abbr: str, season: int, week: int) -> dict | None:
    """Next scheduled game for a team at/after (season, week).

    Returns {opponent, home_away, date, week} or None if the season's over.
    """
    import polars as pl

    sched = schedules_df.filter(
        ((pl.col("home_team") == team_abbr) | (pl.col("away_team") == team_abbr))
        & (
            (pl.col("season") > season)
            | ((pl.col("season") == season) & (pl.col("week") >= week))
        )
    ).sort(["season", "week"])
    if sched.height == 0:
        return None
    g = sched.to_dicts()[0]
    home = g["home_team"] == team_abbr
    return {
        "opponent": g["away_team"] if home else g["home_team"],
        "home_away": "vs" if home else "@",
        "date": str(g.get("gameday")),
        "week": g["week"],
        "season": g["season"],
    }


def latest_injury_status(injuries_df, player_name: str, team: str,
                         season: int, week: int) -> dict | None:
    """Latest injury report row for a player (shared with the news tab)."""
    import polars as pl

    rep = injuries_df.filter(
        (pl.col("full_name") == player_name)
        & (pl.col("season") == season)
        & (pl.col("week") <= week)
    ).sort("week")
    if rep.height == 0:
        last = player_name.split()[-1]
        rep = injuries_df.filter(
            (pl.col("last_name") == last)
            & (pl.col("team") == team)
            & (pl.col("season") == season)
            & (pl.col("week") <= week)
        ).sort("week")
    if rep.height == 0:
        return None
    r = rep.to_dicts()[-1]
    return {
        "status": r.get("report_status"),
        "details": r.get("report_details") or r.get("injury"),
        "week": r.get("week"),
    }


def roster_coverage(rosters_df) -> dict:
    """Honest league-coverage stats for the Players tab header.

    Returns {players, teams, active, missing_headshots}. The roster is
    the full nflverse table for the season — it includes practice-squad
    and reserve players, not just the 53-man active roster, and we say
    so in the UI instead of pretending every row is a starter.
    """
    import polars as pl

    teams = rosters_df["team"].unique().to_list()
    teams = [t for t in teams if t]
    active = rosters_df.filter(pl.col("status") == "ACT").height
    missing_photo = rosters_df.filter(
        pl.col("headshot_url").is_null()
        | (pl.col("headshot_url") == "")
    ).height
    return {
        "players": rosters_df.height,
        "teams": len(teams),
        "active": active,
        "missing_headshots": missing_photo,
    }


def player_form_summary(player_stats_df, player_name: str,
                        position: str | None, season: int) -> dict | None:
    """Compact season form for the spotlight card.

    Returns {label, games, season_avg, last5} for the player's primary
    stat (pass/rush/rec yards by position), or None when the position
    has no meaningful yardage stat — a lineman's card shows no form
    line rather than a made-up one.
    """
    import polars as pl

    entry = POS_FORM_STAT.get((position or "").upper())
    if not entry:
        return None
    col, label = entry
    if col not in player_stats_df.columns:
        return None
    games = (
        player_stats_df.filter(
            (pl.col("player_display_name") == player_name)
            & (pl.col("season") == season)
            & (pl.col("season_type") == "REG")
        )
        .select(["week", col])
        .sort("week")
    )
    vals = [v for v in games[col].to_list() if v is not None]
    if not vals:
        return None
    return {
        "label": label,
        "games": len(vals),
        "season_avg": round(sum(vals) / len(vals), 1),
        "last5": vals[-5:],
    }
