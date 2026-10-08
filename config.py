"""Product configuration — freemium gates live here.

Locked decision (2026-10-07, Tbandz; alerts moved to free 2026-10-07):
  FREE tier  = EV scan + picks, player profiles, tendencies, news,
               prop builder (build SGPs), public track record,
               line-movement alerts (watchlist).
  PREMIUM    = Compare tool (side-by-side player comparison),
               saved/shared prop builds,
               backtest lab (model calibration).

Everything premium is fully built and working — it just sits behind the
flag below. Flip PREMIUM_ENABLED to True to unlock locally.

No payment processing exists yet. When the business is ready, the flow
is: flip this flag per-user from a license/entitlement check (Stripe,
etc.) instead of a module constant. The gate is the product decision;
the plumbing comes later.
"""

# Master switch for the premium tier. False = locked (shows the upsell).
PREMIUM_ENABLED = False

# What the locked screen promises (keep honest — only list what exists).
PREMIUM_TEASER = [
    "Side-by-side stat lines, game logs and projections",
    "Each player's live prop EVs, head to head",
    "Saved + named prop builds (your SGP slips, kept)",
    "Backtest lab: model calibration over past weeks",
]
