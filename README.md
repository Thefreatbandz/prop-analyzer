# Prop Analyzer v1 (working title)

NFL player-props + moneyline **EV analyzer**. It pulls lines from multiple
sportsbooks, builds its own fair price for each bet from stats (free nflverse
data, 2015–present), and flags the ones mispriced in your favor. Every flag
is paper-tracked and graded two ways: vs the closing line (CLV) and vs the
actual result.

**Analysis only — this tool never places bets.** You bet on the sportsbooks;
this just does the math.

## v2 — players, tendencies, news, compare (gated)

- **Players tab** — every rostered player on all 32 teams: bio, season
  averages, game logs with last 5 / 10 / 15 toggle, upcoming matchup,
  injury status, related headlines. `python -m players.build` refreshes
  the league database (free nflverse data).
- **Tendencies tab** — "the way they play": team run/pass splits by down,
  distance and red zone, formation proxies (shotgun / no-huddle / motion),
  pace, most-used play *types* (honestly labeled — concept-level charting
  isn't in the free data), and player style metrics (aDOT, YAC, target
  share, deep-target rate, rush direction).
- **News tab** — ESPN headlines (no key) + the nflverse injury report.
  The scan cross-checks picks against the latest injury report, so the
  model and the news can never silently disagree.
- **Compare tab (PREMIUM, locked)** — side-by-side player comparison is
  fully built but gated behind `PREMIUM_ENABLED = False` in `config.py`.
  Flip it to unlock locally. No payment processing yet — the gate is the
  product decision (freemium: free = scan, paid = compare).
- **Preseason, honestly:** nflverse charts no preseason games (verified:
  schedules list no PRE games, player stats are REG/POST only). The
  Players tab says exactly what's available (rosters, depth charts) and
  what isn't. Nothing is invented.

## v3 — search, data-driven suggestions, props-only mode, security

- **Player search** (sidebar): substring search across all 32 teams'
  rosters — type "allen", get Josh Allen etc. with team/position shown;
  clicking a result opens the profile. Ranked exact → starts-with →
  contains. Sanitized by construction (polars literal matching — no SQL,
  no shell, no interpolation anywhere in the app).
- **Suggested players** (top of the Players tab): 100% data-driven —
  this week's top +EV prop players plus players trending in headlines.
  Every suggestion carries its reason ("Top +EV prop this week…",
  "In the news: N headlines"). Nothing here is anyone's opinion, and
  there are no personal favorite lists.
- **Props-only mode:** with The Odds API unreachable, moneyline views
  show a clear "Moneyline data unavailable — showing player props only"
  notice instead of erroring. The adapter is intact for when a key
  arrives. Live props pulls that fail also degrade to labeled sample
  data rather than crashing.
- **Security (2026-10-07 pass):**
  - No third-party tracking: `.streamlit/config.toml` sets
    `browser.gatherUsageStats = false` (Streamlit telemetry off).
  - Secrets hygiene: keys live only in gitignored `.env` (chmod 600 —
    owner-read-only; keep it that way). The dashboard shows key
    *presence* (set/missing) only — never values or prefixes. Adapter
    exceptions are sanitized before they can reach logs/UI (The Odds
    API puts its key in the request URL, so its HTTP errors are
    re-raised without the URL).
  - Input handling: search is polars literal-substring (no injection
    surface); all SQLite writes use parameterized queries; no shell
    calls anywhere in the codebase.
  - Dependencies pinned in `requirements.txt`; `pip-audit` run
    2026-10-07: no known vulnerabilities in the pinned set.

## Quick start (runs with zero keys)

Without API keys everything runs on bundled sample data and says so.

## Adding the free API keys

1. Copy `.env.example` to `.env` and `chmod 600 .env` (owner-read-only —
   keys must never be world-readable; the repo's `.gitignore` already
   excludes `.env` from version control).
2. **The Odds API** (NFL moneylines, free tier): https://the-odds-api.com
   → set `ODDS_API_KEY`.
3. **Lumify** (NFL player props, 1,000 free credits): https://lumify.ai
   → set `LUMIFY_API_KEY`.

Both adapters cache aggressively (moneylines 15 min, props 6 h) — credits
are never burned twice. With keys set, `scan.py` and the dashboard
automatically switch from sample mode to live odds.

## Live projections (the accurate path)

Sample distributions ship for zero-key runs. For real accuracy:

```bash
~/workspace/venvs/prop-analyzer/bin/python -m projections.build
```

This downloads nflverse data (2015–present: weekly box scores, injuries,
snap counts — cached as parquet in `data/`), detects the current NFL week,
builds recency-weighted per-player distributions with injury adjustments,
and writes `projections/live_distributions.json`. Then:

```bash
~/workspace/venvs/prop-analyzer/bin/python scan.py --model live --log
```

...or pick "live" in the dashboard sidebar. First run downloads a few
hundred MB; after that it's a 24 h cache.

## The paper rule (the Stackz rule, applied)

1. `scan.py --log` writes every +EV flag to the SQLite tracker **before** the game.
2. Near kickoff, record closing lines → the tracker computes **CLV**
   (closing line value): did the market move our way?
3. After the game, grade win/loss → win rate + ROI in paper units.
4. The dashboard's Tracker view shows a progress bar: **100 graded picks
   before real money is even discussed.** Flat 1-unit paper stakes,
   max 10 plays/day — enforced in code.

## How the edge math works

- Implied prob: `-110 → 52.4%`, `+150 → 40%`.
- Strip the vig: normalize both sides to 100% → the book's true price.
- `EV% = fair_prob × decimal_odds − 1`. Positive = mispriced in our favor.
- Fair prob comes from a 10,000-run Monte Carlo over the player's
  recency-weighted stat distribution.
- Moneylines get a second opinion: best price vs Pinnacle's no-vig price
  (the sharp book). Beating Pinnacle = the sharpest book says it's value.

The full teacher-style walkthrough lives in `engine/odds_math.py`.

## Project layout

```
app.py                  Streamlit dashboard (Scan / Pick detail / Tracker /
                        Players / Tendencies / News / Compare)
scan.py                 CLI: run the full EV scan, optionally log paper picks
config.py               PREMIUM_ENABLED flag (Compare tool gate)
odds/
  the_odds_api.py       NFL moneylines adapter (The Odds API, cached 15 min)
  lumify.py             NFL player props adapter (Lumify, cached 6 h)
  cache.py              SQLite response cache — never re-fetch within TTL
  samples/              sample boards so everything runs with zero keys
projections/
  nflverse.py           free data layer (2015–present, parquet cache;
                        + pbp/teams/depth_charts loaders in v2)
  model.py              recency-weighted distributions + injury adjustments
  montecarlo.py         10k-sim fair-probability engine
  build.py              CLI: build live distributions for the current week
  samples/              sample distributions for zero-key runs
players/
  profiles.py           teams, rosters, game logs (5/10/15), season avgs, matchup
  build.py              CLI: refresh the 32-team league database
  preseason.py          honest preseason data inventory (no invented stats)
news/
  espn.py               ESPN headlines (keyless) + nflverse injury report +
                        pick/injury cross-check wired into scan.py
tendencies/
  team.py               run/pass splits, formation proxies, pace
  player.py             aDOT, YAC, target share, deep-target rate, rush splits
  plays.py              most-used play TYPES (honest labeling)
compare/
  compare.py            side-by-side comparison, PREMIUM-gated
builder/                prop builder (SGP-style) — FREE to build
  legs.py               per-leg fair P (model), naive combined P, SGP EV%,
                        correlation caution (always shown)
  saves.py              named saved builds (SQLite) — PREMIUM-gated
alerts/                 line-movement alerts — FREE tier
  watchlist.py          player watchlist + line snapshots + movement
                        detection (≥1.5 pts / ≥10¢); push via cron = future
backtest/
  lab.py                walk-forward calibration lab — PREMIUM-gated
                        (hit-rate buckets + Brier; validates the model,
                        not a betting P&L)
ui/
  cards.py              pick-card builders: hero EV, mini form bars,
                        hit-rate shading, filters, premium lock card
engine/
  odds_math.py          American/implied/decimal conversions, no-vig, EV%
  picks.py              rank props + moneylines by EV%
tracker/
  db.py                 SQLite paper log, CLV, grading, weekly summary
tests/                  32 tests: known-answer math + sample-data pipeline +
                        v2 (game logs, tendencies, premium gate, news)
data/                   gitignored caches (odds, nflverse parquet, tracker.db)
```

## Freemium model

- **Free:** EV scan + picks, player profiles, tendencies, news, prop
  builder (assemble SGPs, see per-leg and combined fair P), public
  track record (every paper pick + CLV + running ROI, fully auditable),
  line-movement alerts (watchlist + movement detection).
- **Premium** (`config.PREMIUM_ENABLED`, no payments built yet):
  Compare tool, saved/named prop builds, backtest lab (model
  calibration).

## What's deliberately NOT in v1

- Bet placement (analysis only, by design).
- Kelly sizing (flat paper units until the edge is proven).
- Other sports (architecture is sport-agnostic; NFL first, per the locked scope).
- Push notifications for alerts (detection is built; scheduling via cron
  is the documented next step).
- Social "favorited by people" (needs user accounts + a backend that can
  see everyone's stars — future; nothing faked in the meantime).
