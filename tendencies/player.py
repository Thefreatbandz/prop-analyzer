"""Player style metrics — "the way THEY play".

Two sources, used where each is strongest:
  - Weekly box scores (player_stats): targets, receptions, receiving
    yards, receiving_air_yards, receiving_yards_after_catch — so aDOT
    and YAC come straight from the weekly table, no PBP needed.
  - Play-by-play: target share vs team pass attempts, deep-target rate,
    rush direction splits (run_location / run_gap).

Honest gaps: slot rate / alignment (slot vs wide vs inline) is NOT in
the free data — returns None with a reason, never a guess.
"""
from __future__ import annotations


def style_from_weekly(player_stats_df, player_name: str, season: int) -> dict:
    """aDOT, YAC/reception, catch rate from weekly box scores.

    aDOT (average depth of target) = receiving_air_yards / targets.
    High aDOT = downfield threat; low aDOT = underneath/checkdown role.
    """
    import polars as pl

    games = player_stats_df.filter(
        (pl.col("player_display_name") == player_name)
        & (pl.col("season") == season)
        & (pl.col("season_type") == "REG")
    )
    n = games.height
    if n == 0:
        return {"player": player_name, "season": season, "games": 0}
    want = ("targets", "receptions", "receiving_yards",
            "receiving_air_yards", "receiving_yards_after_catch",
            "carries", "rushing_yards")
    have = [c for c in want if c in games.columns]
    sums = games.select(
        [pl.col(c).sum() for c in have]
    ).to_dicts()[0]

    def div(a, b):
        a = a or 0
        return round(a / b, 2) if b else None

    tgt, rec = sums.get("targets") or 0, sums.get("receptions") or 0
    return {
        "player": player_name,
        "season": season,
        "games": n,
        "targets_per_game": round(tgt / n, 1),
        "adot": div(sums.get("receiving_air_yards"), tgt),          # avg depth of target
        "yac_per_reception": div(sums.get("receiving_yards_after_catch"), rec),
        "catch_rate": div(rec, tgt),
        "yards_per_reception": div(sums.get("receiving_yards"), rec),
        "yards_per_carry": div(sums.get("rushing_yards"), sums.get("carries")),
        "slot_rate": None,  # not in free data — see module docstring
        "slot_note": "Alignment (slot vs wide) isn't charted in the free "
                     "nflverse tables, so we don't estimate it.",
    }


def _name_forms(player_name: str) -> list[str]:
    """nflverse PBP uses 'J.Allen' format; box scores use 'Josh Allen'.
    Match both so usage splits never silently come back empty."""
    parts = player_name.split()
    forms = [player_name]
    if len(parts) > 1:
        forms.append(f"{parts[0][0]}.{parts[-1]}")
    return forms


def usage_splits(pbp_df, player_stats_df, player_name: str, team: str,
                 season: int) -> dict:
    """Target share, deep-target rate, rush direction splits (PBP-based).

    Target share = player targets / team pass attempts. Deep target =
    air_yards >= 20. Rush direction from run_location (LEFT/MIDDLE/RIGHT).
    """
    import polars as pl

    forms = _name_forms(player_name)
    out: dict = {"player": player_name, "season": season}
    pbp = pbp_df.filter(
        (pl.col("season") == season) & (pl.col("posteam") == team)
        & (pl.col("play_type") == "pass")
    )
    team_attempts = pbp.height
    targets = pbp.filter(pl.col("receiver_player_name").is_in(forms))
    n_tgt = targets.height
    out["target_share"] = round(n_tgt / team_attempts, 3) if team_attempts else None
    if n_tgt and "air_yards" in targets.columns:
        airs = [a for a in targets["air_yards"].to_list() if a is not None]
        out["deep_target_rate"] = (
            round(sum(1 for a in airs if a >= 20) / len(airs), 3) if airs else None
        )
    else:
        out["deep_target_rate"] = None

    rushes = pbp_df.filter(
        (pl.col("season") == season)
        & (pl.col("rusher_player_name").is_in(forms))
        & (pl.col("play_type") == "run")
    )
    n_rush = rushes.height
    out["rushes"] = n_rush
    if n_rush and "run_location" in rushes.columns:
        locs = [(l or "").upper() for l in rushes["run_location"].to_list()]
        for loc in ("LEFT", "MIDDLE", "RIGHT"):
            out[f"rush_{loc.lower()}_share"] = round(
                sum(1 for l in locs if l == loc) / n_rush, 3
            )
    return out
