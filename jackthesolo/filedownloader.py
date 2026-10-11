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
    retries: int = 3,
) -> Path:
    import time

    from .progress import backoff_delay, is_transient_http

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

    last_err: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return _fetch_once(
                session,
                common,
                url,
                safe,
                out_dir,
                output_file,
                cookies_file,
                timeout,
            )
        except PermissionError:
            raise
        except Exception as e:  # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", None)
            if isinstance(e, requests.HTTPError):
                status = e.response.status_code if e.response is not None else None
            transient = isinstance(
                e, (requests.Timeout, requests.ConnectionError)
            ) or is_transient_http(status)
            if not transient or attempt >= max(1, retries):
                raise
            last_err = e
            delay = backoff_delay(attempt)
            retry_after = getattr(getattr(e, "response", None), "headers", {}).get(
                "Retry-After"
            )
            try:
                delay = max(delay, min(60.0, float(retry_after)))
            except (TypeError, ValueError):
                pass
            print(
                f"[jackthesolo] transient failure ({type(e).__name__}), "
                f"retry {attempt}/{max(1, retries)} in {delay:.1f}s..."
            )
            time.sleep(delay)
            session = load_session_with_cookies(None, **common)
    raise last_err  # unreachable, appeases type checkers


def _total_from_range(content_range: str | None) -> int:
    """Parse 'bytes 100-999/2000' -> 2000, else 0."""
    try:
        return int((content_range or "").split("/")[-1])
    except (ValueError, AttributeError):
        return 0


def _fetch_once(
    session,
    common: dict,
    url: str,
    safe: str,
    out_dir: Path,
    output_file: str | None,
    cookies_file: str | None,
    timeout: int,
) -> Path:

    # Resume only when the name is deterministic (--output-file); otherwise a
    # renamed download would append to the wrong bytes.
    fname0 = output_file or guess_filename(url, None)
    dest = out_dir / fname0
    tmp = dest.with_name(dest.name + ".part")
    have = tmp.stat().st_size if (tmp.exists() and output_file) else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    r = session.get(
        url, stream=True, timeout=timeout, allow_redirects=True, headers=headers
    )
    if r.status_code in (401, 403) and cookies_file:
        r.close()
        print("[jackthesolo] server requires login, using cookies")
        session = load_session_with_cookies(cookies_file, **common)
        r = session.get(
            url, stream=True, timeout=timeout, allow_redirects=True, headers=headers
        )

    with r:
        print(
            f"[jackthesolo] GET {safe} -> {r.status_code} ({r.headers.get('content-type')})"
        )
        if r.status_code in (401, 403):
            raise PermissionError(
                f"HTTP {r.status_code}: denied. "
                + (
                    "cookies expired/wrong account, or URL is not a direct file. "
                    "Re-export your cookies."
                    if cookies_file
                    else "This URL needs login. Retry with --cookies /path/to/your/cookies.txt."
                )
            )
        if r.status_code == 416:
            tmp.unlink(missing_ok=True)
            raise ValueError("server rejected resume offset, restarted clean")
        resumed = bool(have) and r.status_code == 206
        if resumed:
            print(f"[jackthesolo] resuming at {fmt_bytes(have)}")
            total = _total_from_range(r.headers.get("content-range")) or have
        else:
            if have:
                tmp.unlink(missing_ok=True)
            total = int(r.headers.get("content-length", 0) or 0)
        r.raise_for_status()
        fname = output_file or guess_filename(url, r)
        if fname != fname0:
            tmp.unlink(missing_ok=True)
            dest = out_dir / fname
            tmp = dest.with_name(dest.name + ".part")
            have, resumed, total = (
                0,
                False,
                int(r.headers.get("content-length", 0) or 0),
            )
        done = have if resumed else 0
        rate = Rate()
        spin = Spinner().start("connecting...")
        with open(tmp, "ab" if resumed else "wb") as f:
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
