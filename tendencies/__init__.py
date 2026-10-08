"""Tendencies — "the way they play", from charted play-by-play.

  team.py    run/pass splits (overall, by down, by distance, red zone),
             formation proxies (shotgun / no-huddle / motion rates), pace.
  player.py  style metrics: aDOT, YAC/reception, target share,
             deep-target rate, rush direction splits.
  plays.py   "most used plays" — the honest version: most-used play TYPES
             (run direction, pass depth buckets). Concept-level charting
             (Mesh, Duo, Power-O...) is NOT in the free data and we say so.

Honest-labeling rule: every metric carries its source; anything the free
data can't compute returns None with a reason instead of a made-up number.
"""
