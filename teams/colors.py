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

# NBA: 30 teams, (primary, secondary) from each club's public brand guide.
NBA_COLORS: dict[str, tuple[str, str]] = {
    "ATL": ("#E03A3E", "#C1D32F"),  # Hawks
    "BOS": ("#007A33", "#BA9653"),  # Celtics
    "BKN": ("#000000", "#FFFFFF"),  # Nets
    "CHA": ("#1D1160", "#00788C"),  # Hornets
    "CHI": ("#CE1141", "#000000"),  # Bulls
    "CLE": ("#860038", "#FDBB30"),  # Cavaliers
    "DAL": ("#00538C", "#002B5E"),  # Mavericks
    "DEN": ("#0E2240", "#FEC524"),  # Nuggets
    "DET": ("#C8102E", "#1D42BA"),  # Pistons
    "GS": ("#1D428A", "#FFC72C"),   # Warriors (nba_api uses GS)
    "GSW": ("#1D428A", "#FFC72C"),  # Warriors (alt abbr)
    "HOU": ("#CE1141", "#000000"),  # Rockets
    "IND": ("#002D62", "#FDBB30"),  # Pacers
    "LAC": ("#C8102E", "#1D428A"),  # Clippers
    "LAL": ("#552583", "#FDB927"),  # Lakers
    "MEM": ("#5D76A9", "#12173F"),  # Grizzlies
    "MIA": ("#98002E", "#F9A01B"),  # Heat
    "MIL": ("#00471B", "#EEE1C6"),  # Bucks
    "MIN": ("#0C2340", "#78BE20"),  # Timberwolves
    "NO": ("#0C2340", "#C8102E"),   # Pelicans
    "NOP": ("#0C2340", "#C8102E"),  # Pelicans (alt abbr)
    "NY": ("#006BB6", "#F58420"),   # Knicks (nba_api uses NY)
    "NYK": ("#006BB6", "#F58420"),  # Knicks (alt abbr)
    "OKC": ("#007AC1", "#EF3B24"),  # Thunder
    "ORL": ("#0077C0", "#C4CED4"),  # Magic
    "PHI": ("#006BB6", "#ED174C"),  # 76ers
    "PHX": ("#1D1160", "#E56020"),  # Suns
    "POR": ("#E03A3E", "#000000"),  # Trail Blazers
    "SAC": ("#5A2D81", "#63727A"),  # Kings
    "SA": ("#C4CED4", "#000000"),   # Spurs (nba_api uses SA)
    "SAS": ("#C4CED4", "#000000"),  # Spurs (alt abbr)
    "TOR": ("#CE1141", "#000000"),  # Raptors
    "UTA": ("#002B5C", "#F9A01B"),  # Jazz
    "WAS": ("#002B5C", "#E31837"),  # Wizards
}

NBA_NAME_TO_ABBR = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GS", "Houston Rockets": "HOU",
    "Indiana Pacers": "IND", "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NO",
    "New York Knicks": "NY", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC", "San Antonio Spurs": "SA",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}

# MLB: 30 teams, (primary, secondary) from each club's public brand guide.
MLB_COLORS: dict[str, tuple[str, str]] = {
    "ARI": ("#A7194B", "#E3D4AD"),  # Diamondbacks
    "ATL": ("#CE1148", "#13274F"),  # Braves
    "BAL": ("#DF4601", "#000000"),  # Orioles
    "BOS": ("#BD3039", "#0C2340"),  # Red Sox
    "CHC": ("#0E3386", "#CC3433"),  # Cubs
    "CWS": ("#27251F", "#C4CED4"),  # White Sox
    "CHW": ("#27251F", "#C4CED4"),  # White Sox (alt abbr)
    "CIN": ("#C6011F", "#000000"),  # Reds
    "CLE": ("#00385D", "#E31937"),  # Guardians
    "COL": ("#33006F", "#C4CED4"),  # Rockies
    "DET": ("#0C2340", "#FA4616"),  # Tigers
    "HOU": ("#EB6E1F", "#002D62"),  # Astros
    "KC": ("#004687", "#BD9B60"),   # Royals
    "KCR": ("#004687", "#BD9B60"),  # Royals (alt abbr)
    "LAA": ("#BA0021", "#003263"),  # Angels
    "LAD": ("#005A9C", "#FFFFFF"),  # Dodgers
    "MIA": ("#00A3E0", "#EF3340"),  # Marlins
    "MIL": ("#FFC52F", "#12284B"),  # Brewers
    "MIN": ("#002B5C", "#D31145"),  # Twins
    "NYY": ("#0C2340", "#FFFFFF"),  # Yankees
    "NYM": ("#002D72", "#FF5910"),  # Mets
    "ATH": ("#003831", "#EFB21E"),  # Athletics
    "OAK": ("#003831", "#EFB21E"),  # Athletics (alt abbr)
    "PHI": ("#E81828", "#002D72"),  # Phillies
    "PIT": ("#FDB827", "#000000"),  # Pirates
    "SD": ("#2F241D", "#FFC425"),   # Padres
    "SDP": ("#2F241D", "#FFC425"),  # Padres (alt abbr)
    "SF": ("#FD5A1E", "#000000"),   # Giants
    "SFG": ("#FD5A1E", "#000000"),  # Giants (alt abbr)
    "SEA": ("#0C2C56", "#005C5C"),  # Mariners
    "STL": ("#C41E3A", "#0C2340"),  # Cardinals
    "TB": ("#092C5C", "#8FBCE6"),   # Rays
    "TBR": ("#092C5C", "#8FBCE6"),  # Rays (alt abbr)
    "TEX": ("#003278", "#C0111F"),  # Rangers
    "TOR": ("#134A8E", "#1D2D5C"),  # Blue Jays
    "WAS": ("#AB0003", "#14225A"),  # Nationals
    "WSH": ("#AB0003", "#14225A"),  # Nationals (alt abbr)
}

MLB_NAME_TO_ABBR = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET",
    "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN", "New York Yankees": "NYY",
    "New York Mets": "NYM", "Athletics": "ATH", "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB", "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR", "Washington Nationals": "WAS",
}


def _luminance(hex_color: str) -> float:
    """Relative luminance 0..1 — used to keep accents visible on charcoal."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def team_accent(team: str | None, sport: str = "nfl") -> tuple[str, str] | None:
    """(accent, tint) for a team abbr ("BUF") or full name ("Buffalo Bills").

    sport picks the color table ("nfl"/"nba"/"mlb") — abbreviations collide
    across leagues (MIA is Dolphins/Heat/Marlins), so cards must pass their
    sport. Unknown team or sport -> None -> caller falls back to gold.
    """
    if not team or not isinstance(team, str):
        return None
    sport = (sport or "nfl").lower()
    if sport == "nba":
        colors_table, name_table = NBA_COLORS, NBA_NAME_TO_ABBR
    elif sport == "mlb":
        colors_table, name_table = MLB_COLORS, MLB_NAME_TO_ABBR
    else:
        colors_table, name_table = TEAM_COLORS, NAME_TO_ABBR
    abbr = name_table.get(team.strip(), team.strip().upper())
    if sport == "nfl":
        # "LA" (nflverse's Rams abbr) -> "LAR" (canonical key).
        abbr = ABBR_ALIASES.get(abbr, abbr)
    colors = colors_table.get(abbr)
    if not colors:
        return None
    primary, secondary = colors
    accent = primary if _luminance(primary) >= 0.07 else secondary
    tint = secondary if _luminance(secondary) >= 0.07 else None
    return accent, tint


def badge_text_color(accent: str) -> str:
    """Readable text on the jersey badge: dark on bright, white on dark."""
    return "#141416" if _luminance(accent) >= 0.35 else "#FFFFFF"
