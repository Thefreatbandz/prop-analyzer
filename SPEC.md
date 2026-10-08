# Prop Analyzer v1 — Spec (working title)

**Scope (locked 2026-10-07):** NFL football. Player props + moneyline. Other sports plug in later — the architecture is sport-agnostic from day one.

## What it is / what it isn't

**Is:** a tool that pulls real lines from multiple sportsbooks, builds its own fair price for each bet from stats, and flags the ones where a book's line is mispriced in your favor (+EV). Plus a paper tracker that grades every pick.

**Isn't:** an "AI that predicts games." No model predicts the NFL. Anyone selling certainty is lying. The edge here is math, not magic: find prices that are wrong, bet only those, track everything.

## How the edge actually works (plain language)

Every bet has two prices:
1. **The book's price** — e.g. Josh Allen over 267.5 passing yards at -110.
2. **The fair price** — what the bet *should* cost based on the stats. If our model says Allen goes over 54% of the time, fair odds are about -117.

If a book offers -110 on something that's fairly -117, that's a +EV bet — over hundreds of such bets, the math favors you. Two ways we find them:
- **Line shopping:** the same prop at different prices across books (DraftKings -110 vs FanDuel -105). Always take the best number — free money on the table.
- **Model edge:** our projection disagrees with the line (model says 54%, line implies 52.4%).

**CLV (closing line value)** is the report card: if the line moves toward our pick after we log it, we beat the market — that's the skill signal, even before the game ends.

## v1 architecture

```
odds API ──→ line board ──→ EV engine ──→ ranked picks ──→ paper tracker
(nflverse) ──→ projections ──↗                (Streamlit dashboard)
```

**1. Line board** — pulls NFL moneylines + player props from every available book. Caches aggressively (API credits cost money).
**2. Projections** — free nflverse data (play-by-play back to 1999, rosters, snap counts, injuries) via `nflreadpy`. Per-player mean + std for each stat → Monte Carlo simulation (10k runs) → fair probability for every prop line.
**3. EV engine** — fair prob vs best book price → EV%. Rank everything. Moneyline gets the same treatment, checked against the sharp books (Pinnacle) as a second opinion.
**4. Paper tracker** — every flagged pick logged with timestamp, book, line, fair prob, EV. Graded two ways: vs closing line (CLV) and vs actual result. This is the Stackz rule: **no real money until the paper record proves an edge.**
**5. Dashboard** — Streamlit (same stack as Bandz Terminal): scan view, pick detail with the math shown, tracker with win rate / ROI / CLV.

## Locked decisions (2026-10-07, Tbandz)
- **Budget: $0 bootstrap.** Free tiers only until the paper record earns a paid feed.
- **Data window: 2015–present** for the model (not 1999 — his call; modern NFL only), plus live/current data and injury reports. Accuracy is the product.
- **Business model: analysis only.** Users never place bets on our site — the tool flags +EV spots, betting happens on the sportsbooks. (This also keeps us out of gambling-operator territory legally: we're a picks/analysis product, not a book.)
- **Product bar:** accurate enough that people want to use it (future SaaS door stays open; v1 is personal use).

## Data sources + the cost reality

| Need | Source | Cost |
|---|---|---|
| Moneyline odds (multi-book) | The Odds API free tier | $0 (limited credits) |
| Player props odds (multi-book) | The Odds API paid tier, or Lumify (1,000 free credits, then paid) | Props data is the expensive part industry-wide (~$200–500/mo for premium). Bootstrap on free credits first. |
| Stats for projections | nflverse (play-by-play, rosters, injuries, 1999–present) | $0, no key needed |
| Scores/grading | nflverse + odds API | $0 |

**Recommended bootstrap ($0):** Lumify's 1,000 free credits for props + The Odds API free tier for moneylines + nflverse for everything else. Pay for a props feed only if the paper record says the edge is real.

## The math (simple version)

- Implied probability from American odds: -110 → 52.4%, +100 → 50%.
- Remove the vig: normalize the over/under (or both sides of the moneyline) so they sum to 100% → the book's *true* price.
- EV% = (fair_prob × decimal_odds) − 1. Positive = +EV.
- Bet sizing for the tracker: flat paper units in v1 (no Kelly until the edge is proven — Kelly on an unproven edge is how bankrolls die).

## Paper-testing protocol (the Stackz rule, applied)

1. Log every +EV flag with timestamp, book, line, odds, fair prob, EV%.
2. Record the closing line for CLV.
3. Grade after the game: win/loss, profit in paper units.
4. Review weekly: is CLV positive? Is ROI positive over 100+ picks? **100 graded picks minimum before real money is even discussed** — same bar as Stackz.

## Build phases

1. **Line board** — odds pull, caching, multi-book comparison view. (Moneyline works on the free tier day one.)
2. **Projections** — nflverse pull, per-player distributions, Monte Carlo engine.
3. **EV rank + paper tracker** — the actual picks list + grading.
4. **Dashboard polish** — make it clean, phone-readable, Bandz-styled.

## Open decisions (Tbandz's call)

- **Odds API budget:** start $0 on free credits (recommended), or pay for a props feed now?
- **Name:** needs a real name eventually (working title is just "prop analyzer").
- **Sportsbook accounts:** which books does he actually have access to? The analyzer can only flag lines he can bet.

## v2 scope (locked 2026-10-07, Tbandz's feature list)

- **Player profiles:** every player gets a detail page — name, position, team, full stat lines, game logs with last 5 / 10 / 15 game toggle, season averages, and the matchup ahead.
- **Full league coverage:** all 32 teams, all rostered players in the database — not just the ones with props listed.
- **Preseason:** include where the free data allows (rosters/depth charts). Note: nflverse does not chart preseason play-by-play, so preseason *stats* may not be available free — verify and use what's there.
- **News feed:** NFL news + injuries (free ESPN API or similar), surfaced on the dashboard and linked to players (injuries already feed the projection downgrades).
- **Tendencies / "the way they play":** team run/pass splits by down & distance, personnel/formation tendencies (FTN charting where nflverse has it), pace; player style metrics (aDOT, YAC, slot rate, etc.).
- **"Most used plays":** honest version = most-used play *types* and tendencies from play-by-play (run/pass, direction, personnel) — granular play-concept charting isn't in the free data.
- **Compare tool = PREMIUM (paid tier):** side-by-side player comparison (stats, game logs, projections, their prop EVs). Built working but gated behind a `PREMIUM` flag (locked for now, unlockable later). Freemium model: free = EV scan + picks; paid = compare tool (+ future deep features). No payments built in v2 — the gate is the product decision.
- **Premium tier (expanded 2026-10-07):** Compare tool (gated, kept) + **saved/shared prop builds** (name and keep SGP slips) + **backtest lab** (walk-forward model calibration: hit-rate by probability bucket + Brier score over past weeks). Free tier: EV scan, player profiles, tendencies, news, the prop builder itself (building is free; saving is premium), the **public track record** (every paper pick published with line at pick time, closing line, graded result, CLV, running win rate/ROI — "we publish every pick, grade us"), and **line-movement alerts** (player watchlist; flags line moves ≥1.5 pts or odds moves ≥10¢ between scans; push scheduling via cron is the documented future step).

**v2 BUILT 2026-10-07:** `players/` (32-team league DB via `python -m players.build`, profiles with last 5/10/15 game logs, season avgs, matchup, injury status), `news/` (ESPN keyless headlines + nflverse injury report; scan cross-checks picks vs latest report), `tendencies/` (team run/pass splits by down/distance/red zone, formation proxies, pace, most-used play *types* with honest labeling, player aDOT/YAC/target share/deep rate/rush splits), `compare/` (fully built, gated by `config.PREMIUM_ENABLED = False`). Preseason verified: nflverse has NO preseason games/PBP/stats (REG/POST only) — rosters + depth charts only, labeled in UI. 32/32 tests pass.

## v3 scope (locked 2026-10-07, Tbandz course correction)

- **Player search bar** (sidebar): substring search over all 32-team rosters, ranked, click-to-profile.
- **Suggested players**: 100% DATA-DRIVEN ONLY — top current-week prop EV% + trending (news mentions). No personal/opinion favorites anywhere (removed entirely per Tbandz). Logic labeled in the UI.
- **Props-only mode**: moneyline views degrade to a clear notice when The Odds API is unreachable; adapter kept intact.
- **Security pass**: no third-party tracking (Streamlit telemetry off via .streamlit/config.toml), secrets hygiene (keys only in chmod-600 gitignored .env, sanitized adapter exceptions, presence-only key status in UI), input sanitization (no SQL/shell interpolation), pinned deps + pip-audit clean.
- **UI polish**: full dark gold-on-charcoal theme, clean typography, phone-readable.
- **Social "favorited by people": NOT built** — needs user accounts + backend. Documented future item only; nothing faked.

## v4 scope (locked 2026-10-07, UI redesign + game-changers)

- **UI redesign** (from live survey of props.cash, Action Network, BettingPros): hero EDGE% per pick card, card anatomy (player/matchup → line/odds → EV → book), mini last-5 bar viz per card, category chips, hit-rate shading, plain-English "What is +EV?" explainer, Scan tab as front page. Gold-on-charcoal kept.
- **Prop builder (FREE)**: SGP-style leg stacking (prop + moneyline legs), per-leg model pricing, combined fair probability with an honest same-game correlation caution on every combined number. Saving/naming builds is premium.
- **Public track record (FREE)**: every paper pick published with line-at-pick, closing line, result, CLV; lifetime win rate / ROI / avg CLV; 100-pick gate progress shown honestly. Copy: "We publish every pick. Grade us."
- **Line-movement alerts (FREE)**: watchlist + snapshot/diff detection (≥1.5 pts / ≥10¢). Push scheduling is a future step.
- **Premium tier** (gated by `PREMIUM_ENABLED`): compare tool, saved builds, backtest lab (walk-forward calibration + Brier score; honest note that it validates the model, not betting P&L — no free historical lines). Pricing direction: $12/mo or $99/yr; $0 charged until 100 graded picks prove the record. No payments/accounts built until Tbandz approves.

## v5 scope (locked 2026-10-07, trading cards)

- **Trading-card pick cards**: player headshot (nflverse roster CDN, downloaded once, thumbnailed, cached locally with LRU cap; initials-monogram fallback), jersey-number badge, team-colored accents (32-team color map), photo/name/number like a real card.
- **MODEL PROB on every card (FREE)**: fair P(hit) from the Monte Carlo sim shown next to EDGE% — the math stays free forever; premium is power tools, not hidden numbers. Builder per-leg probabilities match Scan exactly (stable seeding).
- **"What's not working"**: per-card cold lines ("missed 4 of last 5 vs this line") + a **Fades** view ranking most-negative-EV spots to avoid (explicitly not picks; no log button).
- **Security sweep**: headshot cache hardened (filename allowlist, 8s timeout, 8MB cap, image content-type check, LRU eviction), HTML escaping on all interpolated names (cards, suggested strip, moneyline card), secrets audit clean, 112/112 tests green.

## Responsible gambling (one line, not a lecture)

This is an analysis tool. Set a bankroll rule in v1 (e.g. max 1–2% per pick, stop-loss per week) and the tracker enforces it on paper first.
