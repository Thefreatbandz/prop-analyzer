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
    """Roster row for a display name ("Josh Allen"), or None.

    Exact match first, then the same punctuation-blind key the bio
    lookup uses — "AJ Brown" must find "A.J. Brown"'s headshot too,
    not silently fall back to initials.
    """
    try:
        hit = rosters_df.filter(rosters_df["full_name"] == name)
        if hit.height:
            return hit.to_dicts()[0]
        from players.profiles import normalize_name

        want = normalize_name(name)
        if want:
            for r in rosters_df.to_dicts():
                if normalize_name(r.get("full_name")) == want:
                    return r
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


def _fetch_thumbnail(url: str, cache_key: str, cache_dir: str,
                     fetch=None) -> str | None:
    """Download + thumbnail-cache one image URL. Shared core behind
    headshot_path and the NBA/MLB sport resolvers below.

    Never raises — a missing photo is a UI fallback (initials), not an
    error. cache_key is sanitized to [A-Za-z0-9_-] (no path traversal).
    """
    # Defense in depth: only http(s) URLs are fetched. The NFL roster
    # feed supplies headshot_url; a poisoned feed entry must not turn
    # this into a file:// or internal-host fetch (SSRF).
    scheme = (url or "").strip().lower().split(":", 1)[0]
    if scheme not in ("http", "https"):
        return None
    sid = re.sub(r"[^A-Za-z0-9_-]+", "_", cache_key or "unknown")[:64] or "unknown"
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
    return _fetch_thumbnail(url, sid, cache_dir, fetch=fetch)


# ---- Cross-sport headshots (NBA/MLB) ----
# The NFL roster feed carries headshot_url; NBA/MLB have no roster feed
# wired, so these resolve the league's own photo CDN from the player ID
# we already resolve for game logs. Same thumbnail cache machinery,
# separate cache dirs (no key collisions across leagues). Verified
# 2026-10-11: cdn.nba.com/.../2544.png -> 200 image/png (LeBron),
# securea.mlb.com/.../head_shot/592450.jpg -> 200 image/jpeg (Judge).
# Unknown player or dead URL -> None -> initials fallback, honestly.

_NBA_HEADSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cache", "headshots_nba",
)
_MLB_HEADSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cache", "headshots_mlb",
)

_NBA_CDN = "https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png"
_MLB_CDN = "https://securea.mlb.com/mlb/images/players/head_shot/{pid}.jpg"


def _thumb_b64(path: str | None) -> str | None:
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            raw = f.read()
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
    except OSError:
        return None


def nba_headshot_b64(name: str, fetch=None) -> str | None:
    """data: URI for an NBA player's headshot, or None (initials fallback)."""
    try:
        from projections import nba_data
        pid = nba_data.resolve_player_id(name)
    except Exception:
        return None
    if not pid:
        return None
    path = _fetch_thumbnail(_NBA_CDN.format(pid=pid), f"nba_{pid}",
                            _NBA_HEADSHOT_DIR, fetch=fetch)
    return _thumb_b64(path)


def mlb_headshot_b64(name: str, fetch=None) -> str | None:
    """data: URI for an MLB player's headshot, or None (initials fallback)."""
    try:
        from projections import mlb_data
        pid = mlb_data.resolve_player(name)
    except Exception:
        return None
    if not pid:
        return None
    path = _fetch_thumbnail(_MLB_CDN.format(pid=pid), f"mlb_{pid}",
                            _MLB_HEADSHOT_DIR, fetch=fetch)
    return _thumb_b64(path)


def photo_for_sport(name: str, sport: str, rosters_df=None,
                    fetch=None) -> str | None:
    """Best-effort photo data URI for any sport. None -> initials fallback.

    NFL uses the roster feed (headshot_url); NBA/MLB hit the league CDNs.
    Never raises — the card always renders.
    """
    try:
        if sport == "nba":
            return nba_headshot_b64(name, fetch=fetch)
        if sport == "mlb":
            return mlb_headshot_b64(name, fetch=fetch)
        if rosters_df is not None:
            return headshot_b64(name, rosters_df, fetch=fetch)
    except Exception:
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
