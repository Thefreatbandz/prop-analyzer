"""News feed — free sources only, no keys.

  - NFL headlines: ESPN's public site API (verified keyless 2026-10-07).
  - Injury updates: nflverse weekly injury reports (structured, free) —
    the same source the projection downgrades already consume, so the
    News tab and the model can never disagree.

Cache: headlines 30 min (file cache in data/news/); injuries ride the
24h nflverse parquet cache.
"""
