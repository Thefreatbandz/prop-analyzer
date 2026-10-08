"""NFL team brand colors for the trading-card UI.

All 32 teams: (primary, secondary) hex, from each club's public brand
guide. Used ONLY as accents — card border/glow, the jersey-number
badge, a faint tint wash. Text stays the default ink colors so every
card remains readable; unknown teams fall back to gold-on-charcoal.
"""
from __future__ import annotations

# abbr -> (primary, secondary)
TEAM_COLORS: dict[str, tuple[str, str]] = {
    "ARI": ("#97233F", "#000000"),  # Cardinals: cardinal red / black
    "ATL": ("#A71930", "#000000"),  # Falcons: red / black
    "BAL": ("#241773", "#9E7C0C"),  # Ravens: purple / metallic gold
    "BUF": ("#00338D", "#C60C30"),  # Bills: royal blue / red
    "CAR": ("#0085CA", "#101820"),  # Panthers: panther blue / black
    "CHI": ("#0B162A", "#C83803"),  # Bears: navy / orange
    "CIN": ("#FB4F14", "#000000"),  # Bengals: orange / black
    "CLE": ("#311D00", "#FF3C00"),  # Browns: brown / orange
    "DAL": ("#003594", "#869397"),  # Cowboys: navy / silver
    "DEN": ("#FB4F14", "#002244"),  # Broncos: orange / navy
    "DET": ("#0076B6", "#B0B7BC"),  # Lions: honolulu blue / silver
    "GB": ("#203731", "#FFB612"),   # Packers: green / gold
    "HOU": ("#03202F", "#A71930"),  # Texans: deep steel blue / battle red
    "IND": ("#002C5F", "#A2AAAD"),  # Colts: speed blue / gray
    "JAX": ("#006778", "#D7A22A"),  # Jaguars: teal / gold
    "KC": ("#E31837", "#FFB81C"),   # Chiefs: red / gold
    "LAC": ("#0080C6", "#FFC20E"),  # Chargers: powder blue / gold
    "LAR": ("#003594", "#FFA300"),  # Rams: royal / sol yellow
    "LV": ("#000000", "#A5ACAF"),   # Raiders: black / silver
    "MIA": ("#008E97", "#FC4C02"),  # Dolphins: aqua / orange
    "MIN": ("#4F2683", "#FFC62F"),  # Vikings: purple / gold
    "NE": ("#002244", "#C60C30"),   # Patriots: navy / red
    "NO": ("#D3BC8D", "#101820"),   # Saints: old gold / black
    "NYG": ("#0B2265", "#A71930"),  # Giants: blue / red
    "NYJ": ("#125740", "#000000"),  # Jets: gotham green / black
    "PHI": ("#004C54", "#A5ACAF"),  # Eagles: midnight green / silver
    "PIT": ("#FFB612", "#000000"),  # Steelers: gold / black
    "SEA": ("#002244", "#69BE28"),  # Seahawks: navy / action green
    "SF": ("#AA0000", "#B3995D"),   # 49ers: red / gold
    "TB": ("#D50A0A", "#FF7900"),   # Buccaneers: red / orange
    "TEN": ("#0C2340", "#4B92DB"),  # Titans: navy / light blue
    "WAS": ("#5A1414", "#FFB612"),  # Commanders: burgundy / gold
}

NAME_TO_ABBR: dict[str, str] = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN",
    "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LAR",
    "Las Vegas Raiders": "LV", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE",
    "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT", "Seattle Seahawks": "SEA",
    "San Francisco 49ers": "SF", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}

# Abbr aliases: nflverse data (rosters, schedules, teams table) uses
# "LA" for the Rams while the league's legacy abbr is "LAR".
# team_accent() resolves these so Rams cards keep their colors.
ABBR_ALIASES = {"LA": "LAR"}


def _luminance(hex_color: str) -> float:
    """Relative luminance 0..1 — used to keep accents visible on charcoal."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def team_accent(team: str | None) -> tuple[str, str] | None:
    """(accent, tint) for a team abbr ("BUF") or full name ("Buffalo Bills").

    accent: the visible edge color — primary, unless the primary is too
    dark to read on charcoal (Raiders black), in which case secondary.
    tint: secondary for the faint background wash, or None when it's
    near-black (a black wash is invisible anyway).
    Returns None for unknown teams -> caller falls back to gold.
    """
    if not team or not isinstance(team, str):
        return None
    abbr = NAME_TO_ABBR.get(team.strip(), team.strip().upper())
    # "LA" (nflverse's Rams abbr) -> "LAR" (canonical key).
    abbr = ABBR_ALIASES.get(abbr, abbr)
    colors = TEAM_COLORS.get(abbr)
    if not colors:
        return None
    primary, secondary = colors
    accent = primary if _luminance(primary) >= 0.07 else secondary
    tint = secondary if _luminance(secondary) >= 0.07 else None
    return accent, tint


def badge_text_color(accent: str) -> str:
    """Readable text on the jersey badge: dark on bright, white on dark."""
    return "#141416" if _luminance(accent) >= 0.35 else "#FFFFFF"
