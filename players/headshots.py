"""Player headshots + jersey numbers for the trading-card UI.

Roster data (nflverse load_rosters) carries headshot_url (NFL CDN) and
jersey_number for ~97% of players. We download each photo ONCE, shrink
it with Pillow (the raw files are multi-MB), and cache the thumbnail at
cache/headshots/<safe-id>.jpg so the dashboard never hotlinks on render.

Security notes (reviewed 2026-10-07):
- Filenames come from gsis_id ("00-0034857") or a sanitized name — never
  raw user input, never a URL path. No path traversal possible.
- The cache is capped (MAX_CACHED files, LRU eviction by mtime) so a
  growing roster can't fill the disk.
- Downloads have a short timeout, a size cap, and must serve image/*
  content-type; anything else is rejected and marked as a miss.
- A failed download writes a .miss marker so we don't re-hammer a dead
  URL on every Streamlit rerun.
"""
from __future__ import annotations

import base64
import io
import os
import re

# Default cache dir; tests inject their own via cache_dir=.
HEADSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cache",
    "headshots",
)

THUMB_PX = 160          # trading-card photo size
JPEG_QUALITY = 72
FETCH_TIMEOUT = 8       # seconds — a slow CDN must not stall a rerun
MAX_BYTES = 8_000_000   # raw headshots run ~4MB; thumbnails are ~12KB
MAX_CACHED = 400        # LRU cap on cached thumbnails


def _safe_id(name: str, gsis_id: str | None) -> str:
    """Filesystem-safe cache key: gsis_id when present, else sanitized name.

    Only [A-Za-z0-9_-] survive — a hostile or weird name can never
    escape the cache directory.
    """
    if gsis_id:
        # gsis_id looks like "00-0034857" — already safe, but verify.
        if re.fullmatch(r"[A-Za-z0-9_-]+", gsis_id):
            return gsis_id
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name or "unknown")[:64] or "unknown"


def _row_for(name: str, rosters_df):
    """Roster row for a display name ("Josh Allen"), or None."""
    try:
        hit = rosters_df.filter(rosters_df["full_name"] == name)
        if hit.height:
            return hit.to_dicts()[0]
    except Exception:
        pass
    return None


def jersey_number(name: str, rosters_df) -> str | None:
    """Jersey number as a string ("17"), or None when unknown."""
    row = _row_for(name, rosters_df)
    if not row:
        return None
    j = row.get("jersey_number")
    if j is None:
        return None
    try:
        return str(int(j))
    except (TypeError, ValueError):
        return None


def position_abbr(name: str, rosters_df) -> str | None:
    """Position ("QB"), or None."""
    row = _row_for(name, rosters_df)
    return row.get("position") if row else None


def _thumb_path(cache_dir: str, safe_id: str) -> str:
    return os.path.join(cache_dir, f"{safe_id}.jpg")


def _miss_path(cache_dir: str, safe_id: str) -> str:
    return os.path.join(cache_dir, f"{safe_id}.miss")


def _evict_lru(cache_dir: str) -> None:
    """Keep the cache under MAX_CACHED thumbnails, oldest first."""
    try:
        jpgs = [
            os.path.join(cache_dir, f)
            for f in os.listdir(cache_dir)
            if f.endswith(".jpg")
        ]
    except OSError:
        return
    if len(jpgs) <= MAX_CACHED:
        return
    jpgs.sort(key=lambda p: os.path.getmtime(p))
    for p in jpgs[: len(jpgs) - MAX_CACHED]:
        try:
            os.remove(p)
        except OSError:
            pass


def headshot_path(name: str, rosters_df, fetch=None,
                  cache_dir: str = HEADSHOT_DIR) -> str | None:
    """Local cached thumbnail path for a player, or None on any failure.

    fetch: injectable (url, timeout) -> response with .content and
    .headers (tests use this; default is requests.get). Never raises —
    a missing photo is a UI fallback, not an error.
    """
    row = _row_for(name, rosters_df)
    if not row:
        return None
    url = (row.get("headshot_url") or "").strip()
    if not url:
        return None
    sid = _safe_id(name, row.get("gsis_id"))
    os.makedirs(cache_dir, exist_ok=True)
    thumb = _thumb_path(cache_dir, sid)
    if os.path.exists(thumb):
        return thumb
    if os.path.exists(_miss_path(cache_dir, sid)):
        return None  # known dead — don't re-fetch every rerun

    try:
        if fetch is None:
            import requests

            def fetch(u, timeout):
                return requests.get(u, timeout=timeout)

        resp = fetch(url, FETCH_TIMEOUT)
        content = resp.content or b""
        ctype = (resp.headers.get("content-type", "") or "").lower()
        if not ctype.startswith("image/"):
            raise ValueError(f"not an image: {ctype!r}")
        if len(content) > MAX_BYTES or not content:
            raise ValueError(f"bad size: {len(content)}")

        # Shrink to a card-sized square thumbnail (center crop keeps
        # faces centered for portrait-ish headshots).
        from PIL import Image

        img = Image.open(io.BytesIO(content)).convert("RGB")
        w, h = img.size
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2,
                        (w + side) // 2, (h + side) // 2))
        img = img.resize((THUMB_PX, THUMB_PX), Image.LANCZOS)
        img.save(thumb, "JPEG", quality=JPEG_QUALITY)
        _evict_lru(cache_dir)
        return thumb
    except Exception:
        # Mark the miss so one bad URL doesn't cost a timeout per rerun.
        try:
            open(_miss_path(cache_dir, sid), "w").write("miss")
        except OSError:
            pass
        return None


def headshot_b64(name: str, rosters_df, **kwargs) -> str | None:
    """data: URI for embedding the thumbnail straight into card HTML.

    Embedded bytes can't fail to load (no hotlink, no broken image
    icon) — and a None return means "render the initials fallback".
    """
    path = headshot_path(name, rosters_df, **kwargs)
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            raw = f.read()
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
    except OSError:
        return None


def initials(name: str) -> str:
    """Fallback monogram ("Josh Allen" -> "JA") for the photo slot."""
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()
