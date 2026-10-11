"""Generic file downloader via URL + cookies (for private files that need login)."""

from __future__ import annotations

import http.cookiejar
import os
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests

from .privacy import (
    TOR_DEFAULT,
    isolated_tor_proxy,
    pick_ua,
    requests_proxies,
    resolve_proxy,
    sanitize_url,
)
from .progress import Rate, Spinner, fmt_bytes


def load_session_with_cookies(
    cookies_file: str | None,
    user_agent: str | None = None,
    random_ua: bool = True,
    proxy: str | None = None,
    use_tor: bool = False,
    no_proxy: bool = False,
) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": pick_ua(user_agent, random_ua),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
        }
    )
    px = resolve_proxy(proxy, use_tor, no_proxy=no_proxy)
    if px == TOR_DEFAULT:
        px = isolated_tor_proxy()  # fresh circuit, downloads stay unlinkable
    if px:
        s.proxies.update(requests_proxies(px) or {})
        s.trust_env = False  # never leak through other HTTP(S)_PROXY env vars
    if cookies_file:
        jar = http.cookiejar.MozillaCookieJar(cookies_file)
        jar.load(ignore_discard=True, ignore_expires=True)
        s.cookies.update(
            requests.utils.cookiejar_from_dict({c.name: c.value for c in jar})
        )
        # keep domain/path info by merging raw jar too
        for c in jar:
            s.cookies.set_cookie(c)
    return s


def guess_filename(url: str, response: requests.Response | None = None) -> str:
    if response is not None:
        cd = response.headers.get("content-disposition", "")
        if "filename" in cd:
            # content-disposition: attachment; filename="x.pdf"; filename*=UTF-8''x.pdf
            for part in cd.split(";"):
                part = part.strip()
                if part.lower().startswith("filename*="):
                    v = part.split("=", 1)[1].strip().strip("'\"")
                    if "''" in v:
                        v = v.split("''", 1)[1]
                    return unquote(v)
                if part.lower().startswith("filename="):
                    return part.split("=", 1)[1].strip().strip('"')
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1] or "download.bin")
    if not name or "." not in name:
        return "download.bin"
    return name


def download_file(
    url: str,
    output_dir: str | Path = str(Path.home() / "Downloads"),
    output_file: str | None = None,
    cookies_file: str | None = None,
    timeout: int = 60,
    proxy: str | None = None,
    use_tor: bool = False,
    no_proxy: bool = False,
    user_agent: str | None = None,
    random_ua: bool = True,
) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    common = dict(
        user_agent=user_agent,
        random_ua=random_ua,
        proxy=proxy,
        use_tor=use_tor,
        no_proxy=no_proxy,
    )
    # Try anonymous first; cookies are only sent when the server demands login.
    session = load_session_with_cookies(None, **common)
    safe = sanitize_url(url)

    r = session.get(url, stream=True, timeout=timeout, allow_redirects=True)
    if r.status_code in (401, 403) and cookies_file:
        r.close()
        print("[jackthesolo] server minta login, cookies dipakai")
        session = load_session_with_cookies(cookies_file, **common)
        r = session.get(url, stream=True, timeout=timeout, allow_redirects=True)

    with r:
        print(
            f"[jackthesolo] GET {safe} -> {r.status_code} ({r.headers.get('content-type')})"
        )
        if r.status_code in (401, 403):
            raise PermissionError(
                f"HTTP {r.status_code}: ditolak. "
                + (
                    "cookies expired/wrong account, or URL is not a direct file. "
                    "Re-export your cookies."
                    if cookies_file
                    else "This URL needs login. Retry with --cookies /path/to/your/cookies.txt."
                )
            )
        r.raise_for_status()
        fname = output_file or guess_filename(url, r)
        dest = out_dir / fname
        tmp = dest.with_name(dest.name + ".part")
        total = int(r.headers.get("content-length", 0) or 0)
        done = 0
        rate = Rate()
        spin = Spinner().start("menghubungi...")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                spin.update(rate.line(done, total))
        spin.stop()
        os.replace(tmp, dest)
        print(
            f"[jackthesolo] done: {dest} "
            f"({fmt_bytes(done)} @ {fmt_bytes(rate.avg(done))}/s)"
        )
        return dest
