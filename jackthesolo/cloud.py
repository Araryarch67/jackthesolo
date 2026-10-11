"""Download files from cloud-drive preview pages via Network-tab imitation.

Preview/share links (e.g. /shared?...) are web pages, not files.
The real browser loads the file bytes through internal requests,
so this module opens that page headless, taps the file response,
and saves it directly (no download button).
Needs: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import glob
import http.cookiejar
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .privacy import pick_ua, sanitize_url
from .progress import Spinner


def _chromium_executable() -> str | None:
    """Hint biner Chromium Playwright (khusus Linux). Di OS lain kembalikan
    None agar Playwright memakai mekanisme default-nya sendiri."""
    if not sys.platform.startswith("linux"):
        return None
    cands = sorted(
        glob.glob(
            os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")
        )
    )
    return cands[-1] if cands else None


def download_cloud(
    shared_url: str,
    output_dir: str | Path = str(Path.home() / "Downloads"),
    output_file: str | None = None,
    cookies_file: str | None = None,
    wait_s: int = 25,
    timeout_ms: int = 45000,
) -> Path:
    from playwright.sync_api import sync_playwright

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / (output_file or "download.pdf")
    host = urlsplit(shared_url).netloc or "cloud-drive"
    print(f"[jackthesolo] cloud: {sanitize_url(shared_url)}")
    print(
        "[jackthesolo] anonymous: random UA, direct connection (login = server still knows you)"
    )

    jar = http.cookiejar.MozillaCookieJar(cookies_file)
    jar.load(ignore_discard=True, ignore_expires=True)
    pw_cookies = [
        {
            "name": c.name,
            "value": c.value or "",
            "domain": c.domain or host,
            "path": c.path or "/",
        }
        for c in jar
    ]

    hits: list = []
    with sync_playwright() as p:
        exe = _chromium_executable()
        kw: dict = {"headless": True, "args": ["--no-sandbox"]}
        if exe:
            kw["executable_path"] = exe
        browser = p.chromium.launch(**kw)
        ctx = browser.new_context(
            user_agent=pick_ua(random_ua=True),
            accept_downloads=True,
            locale="en-US",
            timezone_id="UTC",  # never leak the real timezone via JS
        )
        ctx.add_cookies(pw_cookies)
        pg = ctx.new_page()
        pg.on(
            "response", lambda r: hits.append(r) if "mediap.svc.ms" in r.url else None
        )
        spin = Spinner().start("loading preview...")
        try:
            pg.goto(shared_url, wait_until="domcontentloaded", timeout=timeout_ms)
            pg.wait_for_timeout(wait_s * 1000)
        finally:
            spin.stop()
        saved = False
        for r in hits:
            try:
                body = r.body()
                if body[:5] == b"%PDF-":
                    dest.write_bytes(body)
                    print(
                        f"[jackthesolo] done: {dest} ({len(body) / 1024 / 1024:.2f} MB)"
                    )
                    saved = True
                    break
            except Exception as e:  # noqa: BLE001
                print(f"[jackthesolo] unreadable response: {type(e).__name__}")
        browser.close()
        if not saved:
            raise RuntimeError(
                "File not captured from Network (0 PDF stream responses). "
                "Likely: cookies expired, file not loaded yet (raise --wait), or access denied."
            )
        return dest
