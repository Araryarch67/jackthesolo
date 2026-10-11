"""Scribd downloader: /document|doc/<id> docs -> PDF, no login.

Technique adapted from themrsami/scribd-downloader (MIT): the URL becomes an
embed, pages load in bounded batches via docManager, Chrome is cleaned,
each page prints to exactly 1 sheet via CDP printToPDF, then merged with
pypdf. This port uses Playwright (not Selenium) to share one browser stack.
one browser stack across modes.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from .privacy import pick_ua, sanitize_url
from .progress import Spinner
from .tiktok import unique_path

CDP_TIMEOUT = int(os.getenv("SCRIBD_CDP_TIMEOUT", "600"))
SETTLE_TIMEOUT = int(os.getenv("SCRIBD_RENDER_SETTLE_TIMEOUT", "30"))
PAGE_LOAD_TIMEOUT = max(10, int(os.getenv("SCRIBD_PAGE_LOAD_TIMEOUT", "120")))
BATCH_SIZE = max(1, int(os.getenv("SCRIBD_EXPORT_BATCH_SIZE", "8")))
HEADLESS = os.getenv("SCRIBD_HEADLESS", "1").strip().lower() not in {"0", "false", "no"}


def is_scribd_url(url: str) -> bool:
    return "scribd.com" in urlsplit_host(url)


def urlsplit_host(url: str) -> str:
    return urlparse(url).netloc.lower()


def scribd_doc_id(url: str) -> str:
    m = re.search(r"scribd\.com/(?:document|doc|embeds)/(\d+)", url)
    if not m:
        raise ValueError(f"not a Scribd document URL: {url}")
    return m.group(1)


def convert_scribd_link(url: str) -> str:
    return f"https://www.scribd.com/embeds/{scribd_doc_id(url)}/content"


def get_filename_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    last = path.split("/")[-1] if path else "scribd_document"
    name = unquote(last)
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


_HIDE_COOKIES_JS = """() => {
const closeSels = ['[class*="cookie"] [class*="close"]','[class*="consent"] [class*="dismiss"]','button[aria-label="Close"]','[data-dismiss]'];
closeSels.forEach((s) => { try { document.querySelectorAll(s).forEach((b) => b.click()); } catch (e) {} });
const hideSels = ['[class*="cookie"]','[class*="Cookie"]','[class*="consent"]','[class*="Consent"]','[class*="gdpr"]','[id*="cookie"]','[id*="consent"]','.cc-window','#onetrust-consent-sdk','[class*="osano-cm"]'];
hideSels.forEach((s) => { try { document.querySelectorAll(s).forEach((el) => el.remove()); } catch (e) {} });
}"""

_PREPARE_PRINT_JS = """() => {
const out = { toolbarTop: false, toolbarBottom: false, containers: 0 };
const tt = document.querySelector('.toolbar_top');
if (tt) { tt.remove(); out.toolbarTop = true; }
const tb = document.querySelector('.toolbar_bottom');
if (tb) { tb.remove(); out.toolbarBottom = true; }
document.querySelectorAll('.document_scroller').forEach((el) => {
el.setAttribute('data-scribd-print-root', 'true');
el.style.position = 'static'; el.style.top = 'auto'; el.style.bottom = 'auto';
el.style.left = 'auto'; el.style.right = 'auto'; el.style.overflow = 'visible';
el.style.maxHeight = 'none'; el.style.height = 'auto';
el.style.margin = '0'; el.style.padding = '0';
out.containers += 1;
});
return out;
}"""

_PRINT_CSS = """
[class*="cookie"],[class*="Cookie"],[class*="consent"],[class*="Consent"],
[class*="gdpr"],[id*="cookie"],[id*="consent"]{display:none !important;}
[data-scribd-print-root="true"],.document_scroller{position:static !important;
top:auto !important;left:auto !important;right:auto !important;bottom:auto !important;
overflow:visible !important;height:auto !important;max-height:none !important;
margin:0 !important;padding:0 !important;}
@media print{html,body{margin:0 !important;padding:0 !important;
-webkit-print-color-adjust:exact !important;print-color-adjust:exact !important;}
.toolbar_top,.toolbar_bottom{display:none !important;}
mjx-container,.MathJax,.katex,math,svg{visibility:visible !important;overflow:visible !important;}}
"""

_LOAD_BATCH_JS = """async (pageNumbers, timeoutMs) => {
const manager = window.docManager;
if (!manager || !manager.pages) return { supported: false };
const states = pageNumbers.map((n) => ({ pageNum: n, page: manager.pages[n], error: null }));
const startedAt = Date.now();
for (const st of states) {
if (!st.page) { st.error = 'page object missing'; continue; }
try { if (!st.page.innerPageElem && !st.page.loadHasStarted) st.page.load(); }
catch (e) { st.error = String(e); }
}
while (true) {
let ready = 0;
for (const st of states) {
if (st.error) { ready += 1; continue; }
const pg = st.page;
if (!pg.innerPageElem) continue;
try { pg.display(); if (!pg._imagesTurnedOn) pg.turnOnImages(); }
catch (e) { st.error = String(e); ready += 1; continue; }
const imgs = Array.from(pg.innerPageElem.querySelectorAll('img'));
if (imgs.every((i) => i.complete)) ready += 1;
}
if (ready === states.length) {
return { supported: true, failed: states.filter((s) => s.error).map((s) => ({ pageNum: s.pageNum, reason: s.error })) };
}
if (Date.now() - startedAt >= timeoutMs) {
return { supported: true, failed: states.filter((s) => (s.error || !s.page || !s.page.innerPageElem)).map((s) => ({ pageNum: s.pageNum, reason: s.error || 'timed out' })) };
}
await new Promise((r) => setTimeout(r, 50));
}
}"""

_RELEASE_BATCH_JS = """(pageNumbers) => {
const manager = window.docManager;
if (!manager || !manager.pages) return;
for (const n of pageNumbers) {
const pg = manager.pages[n];
if (!pg) continue;
try { pg.remove(); } catch (e) {
const c = document.getElementById('outer_page_' + n);
if (c) { const inner = c.querySelector('.newpage'); if (inner) inner.remove(); }
}
}
}"""

_ISOLATE_PAGE_JS = """(index) => {
const pages = Array.from(document.querySelectorAll('.outer_page'));
const target = pages[index];
if (!target) return null;
const old = document.getElementById('isolated-page-print-style');
if (old) old.remove();
pages.forEach((p) => {
p.removeAttribute('data-export-target');
['display','visibility','position','top','left','right','bottom','margin',
'break-after','page-break-after','break-before','page-break-before'].forEach((k) => p.style.removeProperty(k));
});
const rect = target.getBoundingClientRect();
const width = Math.ceil(rect.width), height = Math.ceil(rect.height);
target.setAttribute('data-export-target', 'true');
const style = document.createElement('style');
style.id = 'isolated-page-print-style';
style.textContent = '@page{size:' + width + 'px ' + height + 'px;margin:0;}'
+ '@media print{html,body{width:' + width + 'px !important;height:' + height + 'px !important;'
+ 'margin:0 !important;padding:0 !important;overflow:hidden !important;'
+ '-webkit-print-color-adjust:exact !important;print-color-adjust:exact !important;}'
+ '.outer_page{display:none !important;}'
+ '.outer_page[data-export-target="true"]{display:block !important;visibility:visible !important;'
+ 'position:absolute !important;top:0 !important;left:0 !important;'
+ 'width:' + width + 'px !important;height:' + height + 'px !important;'
+ 'margin:0 !important;padding:0 !important;overflow:hidden !important;}}';
document.head.appendChild(style);
return { width, height };
}"""


def _launch(page_url: str, user_agent: str):
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    exe = shutil.which("brave")
    kw: dict = {
        "headless": HEADLESS,
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--hide-scrollbars",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    if exe:
        kw["executable_path"] = exe
    browser = pw.chromium.launch(**kw)
    ctx = browser.new_context(
        user_agent=user_agent,
        viewport={"width": 1600, "height": 900},
        locale="en-US",
        timezone_id="UTC",
    )
    page = ctx.new_page()
    page.set_default_timeout(PAGE_LOAD_TIMEOUT * 1000)
    return pw, browser, page


def download_scribd(
    page_url: str,
    output_dir: str | Path = str(Path.home() / "Downloads"),
    output_file: str | None = None,
    batch_size: int = BATCH_SIZE,
    user_agent: str | None = None,
    random_ua: bool = True,
) -> Path:
    from pypdf import PdfReader, PdfWriter

    ua = pick_ua(user_agent, random_ua)
    embed_url = convert_scribd_link(page_url)
    print(f"[jackthesolo] scribd: {sanitize_url(page_url)}")
    print(f"Link embed: {embed_url}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / (output_file or get_filename_from_url(page_url))
    dest = unique_path(dest)

    pw, browser, page = _launch(page_url, ua)
    try:
        spin = Spinner().start("loading document...")
        try:
            page.goto(embed_url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(2000)
        finally:
            spin.stop()
        page.evaluate(_HIDE_COOKIES_JS)
        print("Cookie dialogs hidden.")

        count = page.evaluate("() => document.querySelectorAll('.outer_page').length")
        if not count:
            raise ValueError("No document pages detected (wrong/private URL?).")

        info = page.evaluate(_PREPARE_PRINT_JS)
        if info.get("toolbarTop"):
            print("Top toolbar removed.")
        if info.get("toolbarBottom"):
            print("Bottom toolbar removed.")
        page.evaluate(
            "(css) => { const s = document.createElement('style'); "
            "s.id = 'scribd-print-styles'; s.textContent = css; "
            "document.head.appendChild(s); }",
            _PRINT_CSS,
        )
        print("Print CSS injected.")

        try:
            page.evaluate(
                """async (budgetMs) => {
await (document.fonts ? document.fonts.ready.catch(() => {}) : Promise.resolve());
const t0 = Date.now();
let last = '', stable = 0;
while (stable < 2 && Date.now() - t0 < budgetMs) {
const pages = Array.from(document.querySelectorAll("[class*='page']"));
const pending = Array.from(document.images || []).filter((i) => !i.complete).length;
const cur = pages.length + ':' + pending;
stable = (!pending && cur === last) ? stable + 1 : 0;
last = cur;
await new Promise((r) => setTimeout(r, 300));
}
}""",
                SETTLE_TIMEOUT * 1000,
            )
            print("Document render settled before export.")
        except Exception:  # noqa: BLE001
            print("Render settle over budget, continuing best-effort.")

        cdp_session = page.context.new_cdp_session(page)
        cdp_session.send("Emulation.setEmulatedMedia", {"media": "print"})

        print(f"Exporting {count} document pages in bounded batches of {batch_size}...")
        spool = tempfile.TemporaryDirectory(prefix="scribd-pdf-pages-")
        page_files: list[str] = []
        try:
            for index in range(count):
                if index % batch_size == 0:
                    batch = list(range(index + 1, min(count, index + batch_size) + 1))
                    print(f"  Loading page batch {batch[0]}-{batch[-1]}/{count}...")
                    res = page.evaluate(_LOAD_BATCH_JS, batch, PAGE_LOAD_TIMEOUT * 1000)
                    if not res.get("supported"):
                        raise ValueError("Direct page loader unavailable.")
                    if res.get("failed"):
                        det = ", ".join(
                            f"{x['pageNum']} ({x['reason']})" for x in res["failed"]
                        )
                        raise ValueError(f"Failed to load pages: {det}")

                geo = page.evaluate(_ISOLATE_PAGE_JS, index)
                if not geo or geo["width"] <= 0 or geo["height"] <= 0:
                    print(f"  Skip page {index + 1}: invalid geometry")
                    continue
                w_in, h_in = geo["width"] / 96.0, geo["height"] / 96.0
                print(f"  Page {index + 1}/{count} {geo['width']}x{geo['height']}px")

                t0 = time.time()
                result = cdp_session.send(
                    "Page.printToPDF",
                    {
                        "landscape": False,
                        "displayHeaderFooter": False,
                        "printBackground": True,
                        "scale": 1,
                        "paperWidth": w_in,
                        "paperHeight": h_in,
                        "marginTop": 0,
                        "marginBottom": 0,
                        "marginLeft": 0,
                        "marginRight": 0,
                        "preferCSSPageSize": True,
                        "pageRanges": "1",
                        "transferMode": "ReturnAsStream",
                    },
                )
                if time.time() - t0 > CDP_TIMEOUT:
                    print("  Warning: printToPDF over budget, continuing.")

                import base64

                stream = result.get("stream")
                if not stream:
                    pdf_bytes = base64.b64decode(result["data"])
                else:
                    buf = bytearray()
                    while True:
                        chunk = cdp_session.send(
                            "IO.read", {"handle": stream, "size": 1024 * 1024}
                        )
                        data = chunk.get("data", "")
                        if chunk.get("base64Encoded"):
                            buf += base64.b64decode(data)
                        else:
                            buf += data.encode("utf-8")
                        if chunk.get("eof"):
                            break
                    try:
                        cdp_session.send("IO.close", {"handle": stream})
                    except Exception:  # noqa: BLE001
                        pass
                    pdf_bytes = bytes(buf)

                reader = PdfReader(__import__("io").BytesIO(pdf_bytes))
                if len(reader.pages) != 1:
                    raise ValueError(
                        f"Page {index + 1} produced {len(reader.pages)} sheets, expected 1."
                    )
                fpath = os.path.join(spool.name, f"page-{index + 1:08d}.pdf")
                with open(fpath, "wb") as f:
                    f.write(pdf_bytes)
                page_files.append(fpath)
                print("    OK: exactly 1 PDF sheet")

                if (index + 1) % batch_size == 0 or index + 1 == count:
                    page.evaluate(_RELEASE_BATCH_JS, batch)
                    try:
                        cdp_session.send("HeapProfiler.collectGarbage", {})
                    except Exception:  # noqa: BLE001
                        pass

            if not page_files:
                raise ValueError("No valid pages exported.")
            print(f"Merging {len(page_files)} disk-spooled PDF pages...")
            writer = PdfWriter()
            try:
                for fpath in page_files:
                    writer.append(fpath)
                tmp = dest.with_name(dest.name + ".part")
                with open(tmp, "wb") as f:
                    writer.write(f)
                os.replace(tmp, dest)
            finally:
                writer.close()
        finally:
            spool.cleanup()
    finally:
        browser.close()
        pw.stop()

    print(f"[jackthesolo] done: {dest}")
    return dest
