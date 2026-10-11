"""Auto-detect the URL source.

Cookies come only from --cookies (each user brings their own).
No location fallback of any kind.
"""

from __future__ import annotations

from urllib.parse import urlsplit

# cloud-drive preview link hosts (opened via Network-tab imitation)
CLOUD_HOSTS = (
    "sharepoint.com",
    "sharepointonline.com",
    "onedrive.live.com",
    "1drv.ms",
)

# scribd document hosts (downloaded via embed + per-page print)
SCRIBD_HOSTS = ("scribd.com",)

DIRECT_EXTS = (
    ".pdf",
    ".zip",
    ".rar",
    ".7z",
    ".tar.gz",
    ".tgz",
    ".exe",
    ".dmg",
    ".iso",
    ".apk",
    ".csv",
    ".txt",
    ".docx",
    ".xlsx",
    ".pptx",
    ".epub",
    ".mp3",
    ".mp4",
    ".mkv",
    ".mov",
)


def detect_source(url: str) -> str:
    """Return 'cloud' | 'direct' | 'media' | 'scribd'."""
    host = urlsplit(url).netloc.lower()
    path = urlsplit(url).path.lower()
    if any(h in host for h in SCRIBD_HOSTS):
        return "scribd"
    if any(h in host for h in CLOUD_HOSTS):
        return "cloud"
    if path.endswith(DIRECT_EXTS):
        return "direct"
    return "media"
