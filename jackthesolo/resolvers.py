"""Third-party resolvers for locked videos (e.g. age-gated YouTube).

Last resort after built-in yt-dlp clients fail: public APIs fetch the
stream from their own backend, so no login needed on our side.
Order: Cobalt first (redirect/tunnel mp4), then Invidious (formatStreams).
"""

from __future__ import annotations

import re

from typing import Any

COBALT_INSTANCES = [
    "https://cobalt-api.kwiatekmiki.com",
    "https://cobalt.api.timothyjamesmiller.com",
]

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://iv.melmac.space",
]


def extract_youtube_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/(?:shorts|embed|live)/)([A-Za-z0-9_-]{6,})", url)
    return m.group(1) if m else None


def resolve_cobalt(page_url: str, session, timeout: float = 12) -> str | None:
    for base in COBALT_INSTANCES:
        try:
            r = session.post(
                base.rstrip("/") + "/api/json",
                json={"url": page_url, "videoQuality": "720", "filenameStyle": "basic"},
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=timeout,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if data.get("status") in ("tunnel", "redirect") and data.get("url"):
                return data["url"]
        except Exception:  # noqa: BLE001
            continue
    return None


def resolve_invidious(video_id: str, session, timeout: float = 12) -> str | None:
    for base in INVIDIOUS_INSTANCES:
        try:
            r = session.get(
                f"{base.rstrip('/')}/api/v1/videos/{video_id}", timeout=timeout
            )
            if r.status_code != 200:
                continue
            data = r.json()
            streams = data.get("formatStreams") or []
            mp4 = [s for s in streams if s.get("url")]
            if not mp4:
                continue
            mp4.sort(key=lambda s: int(str(s.get("quality", "0p")).rstrip("p") or 0))
            return mp4[-1]["url"]
        except Exception:  # noqa: BLE001
            continue
    return None


def resolve_any(page_url: str, session) -> tuple[str | None, str]:
    """Kembalikan (direct_url, via). via: 'cobalt' | 'invidious' | ''."""
    u = resolve_cobalt(page_url, session)
    if u:
        return u, "cobalt"
    vid = extract_youtube_id(page_url)
    if vid:
        u = resolve_invidious(vid, session)
        if u:
            return u, "invidious"
    return None, ""
