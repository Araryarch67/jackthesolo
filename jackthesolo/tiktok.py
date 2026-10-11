"""TikTok downloader: video + foto (termasuk subs-only).

TLS impersonate Chrome via curl_cffi, ambil
__UNIVERSAL_DATA_FOR_REHYDRATION__ from the HTML, extract itemStruct,
prioritize aweme/v1/play URLs (they pass 403 with cookies).
Fallback foto: tangkap <img photomode> via browser headless.
Butuh cookies milik sendiri + curl_cffi.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import time
import urllib.parse
from pathlib import Path

from .privacy import (
    TOR_DEFAULT,
    ensure_private,
    isolated_tor_proxy,
    pick_ua,
    sanitize_url,
)
from .progress import Spinner

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"


def unique_path(wanted: Path) -> Path:
    if not wanted.exists():
        return wanted
    if wanted.suffix:
        stem, suffix, parent = wanted.stem, wanted.suffix, wanted.parent
    else:
        stem, suffix, parent = wanted.name, "", wanted.parent
    i = 1
    while True:
        cand = parent / f"{stem}_{i:03d}{suffix}"
        if not cand.exists():
            return cand
        i += 1


def load_netscape_cookies(path: str) -> dict:
    ensure_private(path)
    cookies = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5]] = parts[6]
    if not cookies:
        raise ValueError(f"empty cookies / wrong format: {path}")
    return cookies


def extract_video_id(url: str) -> str:
    m = re.search(r"/(?:video|photo)/(\d+)", url)
    if not m:
        raise ValueError(f"no /video/<id> or /photo/<id> in URL: {url}")
    return m.group(1)


def is_tiktok_detail_url(url: str) -> bool:
    return "tiktok.com" in url and bool(re.search(r"/(?:video|photo)/(\d+)", url))


def is_tiktok_profile_url(url: str) -> bool:
    if "tiktok.com" not in url or is_tiktok_detail_url(url):
        return False
    return bool(re.search(r"tiktok\.com/@[\w.-]+", url))


def clean_url(url: str) -> str:
    """Tolerate stray quotes: "'https://...'" / '"https://..."'."""
    page_url = url.strip()
    while len(page_url) >= 2 and (
        (page_url.startswith('"') and page_url.endswith('"'))
        or (page_url.startswith("'") and page_url.endswith("'"))
    ):
        page_url = page_url[1:-1].strip()
    page_url = page_url.strip("'\" ")
    if page_url.startswith("'https"):
        page_url = page_url[1:]
    return page_url


def get_item_struct(data: dict, video_id: str) -> dict:
    for scope_key in ("webapp.video-detail", "webapp.photo-detail", "webapp.detail"):
        try:
            item = data["__DEFAULT_SCOPE__"][scope_key]["itemInfo"]["itemStruct"]
        except KeyError:
            continue
        if str(item.get("id")) != str(video_id):
            print(
                f"warning: page holds {item.get('id')}, not {video_id}",
                file=sys.stderr,
            )
        return item
    if video_id not in json.dumps(data):
        raise ValueError("itemStruct not found in universal data.")
    raise ValueError("itemStruct not found in standard paths.")


def _new_session(cookies: dict, proxy: str | None):
    try:
        from curl_cffi import requests as cr
    except ImportError:
        raise ValueError("mode TikTok butuh: pip install curl-cffi")

    s = cr.Session(impersonate="chrome124")
    s.cookies.update(cookies)
    if proxy == TOR_DEFAULT:
        proxy = isolated_tor_proxy()  # fresh circuit, downloads stay unlinkable
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def fetch_universal_data(
    page_url: str, cookies: dict, proxy: str | None = None, retries: int = 4
) -> tuple:
    try:
        from curl_cffi import requests as cr  # noqa: F401
    except ImportError:
        raise ValueError("mode TikTok butuh: pip install curl-cffi")

    last_len = 0
    for attempt in range(1, retries + 1):
        s = _new_session(cookies, proxy)
        r = s.get(page_url, headers={"User-Agent": UA}, timeout=60)
        r.raise_for_status()
        html = r.text
        last_len = len(html)
        m = re.search(
            r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        if m:
            return json.loads(m.group(1)), s
        print(
            f"attempt {attempt}/{retries}: universal data missing (html {len(html)}b), retrying..."
        )
        time.sleep(2 * attempt)
    raise ValueError(
        "__UNIVERSAL_DATA_FOR_REHYDRATION__ missing "
        f"after {retries}x (last html {last_len}b). "
        "Retry later, or re-export cookies from a logged-in browser."
    )


def collect_urls(item: dict, tt_token: str) -> list[str]:
    cand: list[str] = []
    for b in item.get("video", {}).get("bitrateInfo") or []:
        for u in (b.get("PlayAddr") or {}).get("UrlList") or []:
            cand.append(u)
    pa = item.get("video", {}).get("playAddr")
    if pa:
        cand.append(pa)

    fixed = []
    for u in cand:
        if "tt_chain_token" in u and tt_token:
            u = u.replace("tt_chain_token", urllib.parse.quote(tt_token, safe=""))
        fixed.append(u)

    # aweme/v1/play first (passes 403 with cookies), then v16/v19 CDNs
    fixed.sort(key=lambda u: 0 if "/aweme/v1/play/" in u else 1)
    seen, out = set(), []
    for u in fixed:
        if u not in seen:
            seen, out = seen | {u}, out + [u]
    return out


def collect_images(item: dict) -> list[str]:
    imgs = (item.get("imagePost") or {}).get("images") or []
    urls: list[str] = []
    for im in imgs:
        for key in ("imageURL", "displayImage", "thumbnail"):
            node = im.get(key) or {}
            lst = node.get("urlList") or node.get("UrlList") or []
            if lst:
                urls.append(lst[0])
                break
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen, out = seen | {u}, out + [u]
    return out


def download_video(urls: list[str], page_url: str, session, out: Path) -> Path:
    last = None
    for i, u in enumerate(urls):
        print(f"[{i + 1}/{len(urls)}] trying {sanitize_url(u)[:80]}...")
        try:
            r = session.get(
                u,
                headers={
                    "Referer": page_url,
                    "Origin": "https://www.tiktok.com",
                    "User-Agent": UA,
                },
                timeout=90,
            )
        except Exception as e:  # noqa: BLE001
            last = str(e)
            print(f"  failed: {e}")
            continue
        ctype = r.headers.get("content-type", "")
        if r.status_code == 200 and "video" in ctype and len(r.content) > 10_000:
            out.write_bytes(r.content)
            print(f"  OK: {len(r.content)} bytes -> {out}")
            return out
        last = f"HTTP {r.status_code} {ctype} {len(r.content)}b"
        print(f"  failed: {last}")
    raise ValueError(f"all candidates failed. last: {last}")


def _photo_folder(out_base: str) -> tuple[Path, str]:
    p = Path(out_base)
    name = p.stem if p.suffix in (".jpg", ".jpeg", ".png", ".webp") else p.name
    folder = p.parent / name if p.suffix in (".jpg", ".jpeg", ".png", ".webp") else p
    folder = unique_path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return folder, name


def download_images(
    urls: list[str], page_url: str, session, out_base: str
) -> list[Path]:
    saved: list[Path] = []
    if len(urls) == 1:
        p = Path(out_base)
        parent = p.parent if str(p.parent) else Path(".")
        parent.mkdir(parents=True, exist_ok=True)
        fname = p if p.suffix else p.with_suffix(".jpg")
        fname = unique_path(fname)
        print(f"[1/1] downloading photo {sanitize_url(urls[0])[:80]}...")
        r = session.get(
            urls[0], headers={"Referer": page_url, "User-Agent": UA}, timeout=90
        )
        if r.status_code == 200 and len(r.content) > 5_000:
            fname.write_bytes(r.content)
            print(f"  OK -> {fname}")
            return [fname]
        raise ValueError(
            f"photo download failed: HTTP {r.status_code} {len(r.content)}b"
        )
    folder, _ = _photo_folder(out_base)
    for i, u in enumerate(urls, 1):
        fname = folder / f"{i:02d}.jpg"
        print(f"[{i}/{len(urls)}] downloading photo {sanitize_url(u)[:80]}...")
        r = session.get(u, headers={"Referer": page_url, "User-Agent": UA}, timeout=90)
        ctype = r.headers.get("content-type", "")
        if r.status_code == 200 and len(r.content) > 5_000:
            fname.write_bytes(r.content)
            print(f"  OK: {len(r.content)} bytes ({ctype}) -> {fname}")
            saved.append(fname)
        else:
            print(f"  failed: HTTP {r.status_code} {ctype} {len(r.content)}b")
    if not saved:
        raise ValueError("all photo downloads failed.")
    return saved


def fetch_photos_via_browser(
    page_url: str, cookies_path: str | None, out_base: str
) -> list[Path]:
    """Photo fallback: /photo/ pages are just a JS shell, grab <img photomode> from the browser.

    No cookies (public content): the browser opens plain. The browser connection
    bypasses Tor (IP visible to TikTok), openly not silently.
    """
    import urllib.request

    from playwright.async_api import async_playwright

    async def _run() -> list[str]:
        cookies = []
        if cookies_path:
            for line in Path(cookies_path).read_text().splitlines():
                if not line.strip() or line.startswith("#"):
                    continue
                dom, _, path, sec, exp, name, val = line.split("\t")
                cookies.append(
                    {
                        "domain": dom,
                        "path": path,
                        "name": name,
                        "value": val,
                        "expires": int(exp) if exp.lstrip("-").isdigit() else 0,
                        "httpOnly": False,
                        "secure": sec.upper() == "TRUE",
                        "sameSite": "None" if sec.upper() == "TRUE" else "Lax",
                    }
                )
        else:
            print("[jackthesolo] browser without login (direct IP visible to TikTok!)")
        exe = shutil.which("brave")
        async with async_playwright() as pw:
            kw = {
                "args": [
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ]
            }
            if exe:
                kw["executable_path"] = exe
            browser = await pw.chromium.launch(**kw)
            ctx = await browser.new_context(
                user_agent=UA,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
                timezone_id="UTC",
            )
            await ctx.add_cookies(cookies)
            page = await ctx.new_page()
            spin = Spinner().start("loading page...")
            try:
                await page.goto(page_url, wait_until="networkidle", timeout=90000)
                await page.wait_for_timeout(8000)
            finally:
                spin.stop()
            srcs = await page.eval_on_selector_all(
                "img",
                "els => els.map(e => e.src).filter(s => s.includes('photomode-image'))",
            )
            await browser.close()
            seen, out = set(), []
            for u in srcs:
                if u not in seen:
                    seen, out = seen | {u}, out + [u]
            return out

    urls = asyncio.run(_run())
    print(f"photos from browser: {len(urls)}")
    if not urls:
        raise ValueError("browser found no photos (login/cookies invalid?).")
    if len(urls) == 1:
        p = Path(out_base)
        parent = p.parent if str(p.parent) else Path(".")
        parent.mkdir(parents=True, exist_ok=True)
        fname = p if p.suffix else p.with_suffix(".jpg")
        fname = unique_path(fname)
        req = urllib.request.Request(
            urls[0], headers={"User-Agent": UA, "Referer": page_url}
        )
        with urllib.request.urlopen(req, timeout=90) as r, open(fname, "wb") as f:
            f.write(r.read())
        print(f"  OK -> {fname}")
        return [fname]
    folder, _ = _photo_folder(out_base)
    saved = []
    for i, u in enumerate(urls, 1):
        fname = folder / f"{i:02d}.jpg"
        req = urllib.request.Request(u, headers={"User-Agent": UA, "Referer": page_url})
        with urllib.request.urlopen(req, timeout=90) as r, open(fname, "wb") as f:
            f.write(r.read())
        print(f"  OK -> {fname}")
        saved.append(fname)
    return saved


def resolve_tikwm(page_url: str, session) -> dict | None:
    """Public resolver without login (like cobalt/invidious). Asks for images + play."""
    import urllib.parse

    try:
        u = "https://www.tikwm.com/api/?url=" + urllib.parse.quote(page_url, safe="")
        r = session.get(u, timeout=40)
        d = r.json()
        if d.get("code") != 0 or not d.get("data"):
            return None
        return d["data"]
    except Exception:  # noqa: BLE001
        return None


def download_tikwm_public(
    page_url: str,
    video_id: str,
    out_dir: Path,
    output_file: str | None,
    proxy: str | None,
    allow_direct_fallback: bool,
) -> list[Path]:
    from .privacy import TOR_DEFAULT, isolated_tor_proxy

    def attempt(px: str | None) -> list[Path]:
        session = _new_session({}, px)
        data = resolve_tikwm(page_url, session)
        if not data:
            raise ValueError("public resolver returned no data")
        imgs = data.get("images") or []
        if imgs:
            base = output_file or video_id
            if str(Path(base).parent) in ("", "."):
                base = str(out_dir / Path(base).name)
            return download_images(imgs, page_url, session, base)
        if data.get("play"):
            out = Path(output_file) if output_file else out_dir / f"{video_id}.mp4"
            if not out.suffix:
                out = out.with_suffix(".mp4")
            out = unique_path(out)
            out.parent.mkdir(parents=True, exist_ok=True)
            return [download_video([data["play"]], page_url, session, out)]
        raise ValueError("public resolver: neither photos nor video")

    try:
        return attempt(proxy)
    except ValueError:
        # Coba circuit Tor lain (exit berbeda, kadang lolos blokir)
        if proxy and (proxy == TOR_DEFAULT or "@127.0.0.1:9050" in proxy):
            for i in range(2):
                print(
                    f"[jackthesolo] resolver blocked, trying a fresh circuit ({i + 1}/2)..."
                )
                try:
                    return attempt(isolated_tor_proxy())
                except ValueError:
                    continue
        if not allow_direct_fallback or not proxy:
            raise
        print("[jackthesolo] resolver blocked via Tor, trying direct (IP visible!)")
        return attempt(None)


def download_tiktok(
    page_url: str,
    cookies_file: str | None = None,
    output_dir: str | Path = str(Path.home() / "Downloads"),
    output_file: str | None = None,
    proxy: str | None = None,
    user_agent: str | None = None,
    random_ua: bool = True,
    allow_direct_fallback: bool = False,
) -> list[Path]:
    _ = pick_ua(user_agent, random_ua)  # random UA for non-TLS logs/sessions
    page_url = clean_url(page_url)
    print(f"[jackthesolo] tiktok: {sanitize_url(page_url)}")
    video_id = extract_video_id(page_url)
    cookies = load_netscape_cookies(cookies_file) if cookies_file else {}
    if cookies:
        print(f"cookies: {len(cookies)} loaded")
    else:
        print("no cookies: trying public content first")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def resolve_out(given: str | None, default_name: str) -> str:
        if not given:
            return str(out_dir / default_name)
        p = Path(given)
        if str(p.parent) in ("", "."):
            return str(out_dir / p.name)
        return given

    try:
        data, session = fetch_universal_data(page_url, cookies, proxy=proxy)
        item = get_item_struct(data, video_id)
    except ValueError as e:
        if "/photo/" in page_url:
            print(f"{e} -> browser fallback...")
            base = resolve_out(output_file, video_id)
            if base.endswith(".mp4"):
                base = base[: -len(".mp4")]
            try:
                return fetch_photos_via_browser(page_url, cookies_file, base)
            except Exception as e2:  # noqa: BLE001
                print(
                    f"browser failed ({type(e2).__name__}), trying public resolver..."
                )
        else:
            print(f"{e} -> trying public resolver (no login)...")
        return download_tikwm_public(
            page_url, video_id, out_dir, output_file, proxy, allow_direct_fallback
        )
    tt_token = cookies.get("tt_chain_token", "")

    urls = collect_urls(item, tt_token)
    imgs = collect_images(item)
    print(f"video candidates: {len(urls)}, photos: {len(imgs)}")

    if urls:
        try:
            raw_out = resolve_out(output_file, f"{video_id}.mp4")
            out = Path(raw_out)
            if not out.suffix:
                out = out.with_suffix(".mp4")
            out = unique_path(out)
            out.parent.mkdir(parents=True, exist_ok=True)
            return [download_video(urls, page_url, session, out)]
        except ValueError as e:
            if not imgs:
                raise
            print(f"video failed ({e}), trying photos...")

    if imgs:
        return download_images(
            imgs, page_url, session, resolve_out(output_file, video_id)
        )

    raise ValueError("no downloadable video or photo URL found.")
