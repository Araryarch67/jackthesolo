"""Privacy helpers: UA rotation, proxy/Tor, URL sanitizing.

Default: anonymous (random UA + automatic Tor/proxy when available).
"""

from __future__ import annotations

import os
import random
import secrets
import socket
from urllib.parse import urlsplit, parse_qsl, urlunsplit, urlencode

UA_POOL = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

TOR_DEFAULT = "socks5h://127.0.0.1:9050"


def isolated_tor_proxy() -> str:
    """Satu circuit Tor fresh per download (Tor mengisolasi per kredensial SOCKS)."""
    u = secrets.token_hex(4)
    p = secrets.token_hex(4)
    return f"socks5h://{u}:{p}@127.0.0.1:9050"


# query keys hidden from logs (session tokens, share ids)
_SENSITIVE_KEYS = {
    "share",
    "shareid",
    "access_token",
    "token",
    "auth",
    "authkey",
    "guestaccesstoken",
    "cs",
    "docid",
    "e",
    "ga",
    "ct",
    "sig",
    "signature",
    "key",
    "passwd",
    "password",
    "sessionid",
    "session",
    "sid",
}

import re as _re

_PAIR_RE = _re.compile(
    r"(?i)\b(share|shareid|access_token|token|auth|authkey|guestaccesstoken"
    r"|cs|docid|e|ga|ct|sig|signature|key|passwd|password|sessionid|session|sid)\b\s*=\s*[^&\s\"']+"
)


def pick_ua(user_agent: str | None = None, random_ua: bool = True) -> str:
    if user_agent:
        return user_agent
    if not random_ua:
        return UA_POOL[0]
    return random.choice(UA_POOL)


def tor_available(
    host: str = "127.0.0.1", port: int = 9050, timeout: float = 0.5
) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_proxy(
    proxy: str | None = None,
    use_tor: bool = False,
    no_proxy: bool = False,
    auto: bool = True,
) -> str | None:
    """Anonymous by default: env JACKTHESOLO_PROXY > automatic Tor (when port 9050 is open).

    Use no_proxy=True for direct connections (e.g. login content,
    since providers often block Tor IPs + login means identified).
    """
    if no_proxy:
        return None
    if proxy:
        return proxy
    if use_tor:
        return TOR_DEFAULT
    env = (
        os.environ.get("JACKTHESOLO_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
    )
    if env:
        return env
    if auto and tor_available():
        return TOR_DEFAULT
    return None


def requests_proxies(proxy: str | None) -> dict[str, str] | None:
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def sanitize_text(text: str) -> str:
    """Redact sensitive key=value pairs in free text (e.g. -v error output)."""
    try:
        return _PAIR_RE.sub(lambda m: m.group(0).split("=", 1)[0] + "=***", str(text))[
            :2000
        ]
    except Exception:
        return "***"


def ensure_private(path: str) -> str:
    """Lock sensitive file (cookies) permissions to 600 when loose."""
    try:
        mode = os.stat(path).st_mode & 0o777
        if mode & 0o077:
            os.chmod(path, 0o600)
            print(f"[jackthesolo] locked {path}: {oct(mode)} -> 0o600")
    except OSError as e:  # noqa: BLE001
        print(f"[jackthesolo] warning: cannot check {path}: {e}")
    return path


def egress_ip(proxy: str | None = None, timeout: float = 8) -> str | None:
    """Prove the egress IP, direct or via proxy. None on failure."""
    try:
        import requests

        proxies = requests_proxies(proxy) if proxy else None
        r = requests.get(
            "https://api.ipify.org",
            proxies=proxies,
            timeout=timeout,
            headers={"User-Agent": UA_POOL[0]},
        )
        ip = r.text.strip()
        return ip or None
    except Exception:  # noqa: BLE001
        return None


def sanitize_url(url: str) -> str:
    """Mask sensitive query keys so tokens never leak into logs/screenshots."""
    try:
        parts = urlsplit(url)
        if not parts.query:
            return url[:160]
        q = [
            (k, ("***" if k.lower() in _SENSITIVE_KEYS else v))
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
        ]
        clean = urlunsplit(
            (parts.scheme, parts.netloc, parts.path[:100], urlencode(q)[:300], "")
        )
        return clean[:400]
    except Exception:
        return url[:160] + "..."
