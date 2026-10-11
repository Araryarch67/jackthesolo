"""CLI for jackthesolo."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .downloader import SUPPORTED_HINT, JackDownloader
from .filedownloader import download_file
from .privacy import resolve_proxy, sanitize_text, sanitize_url
from .sources import detect_source


DEFAULT_OUTPUT = str(Path.home() / "Downloads")

BANNER = r"""
      _         _____ _  _________ _    _ ______  _____  ____  _      ____
     | |  /\   / ____| |/ /__   __| |  | |  ____|/ ____|/ __ \| |    / __ \
     | | /  \ | |    | ' /   | |  | |__| | |__  | (___ | |  | | |   | |  | |
 _   | |/ /\ \| |    |  <    | |  |  __  |  __|  \___ \| |  | | |   | |  | |
| |__| / ____ \ |____| . \   | |  | |  | | |____ ____) | |__| | |___| |__| |
 \____/_/    \_\_____|_|\_\  |_|  |_|  |_|______|_____/ \____/|______\____/
"""

GREEN = "\033[92m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_banner() -> None:
    use_color = sys.stdout.isatty()
    art = BANNER.strip("\n")
    if use_color:
        print(f"{GREEN}{art}{RESET}")
        print(f"{DIM}>> all-platform downloader | anon by default <<{RESET}")
    else:
        print(art)
        print(">> all-platform downloader | anon by default <<")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jackthesolo",
        description=f"jackthesolo v{__version__} - all-platform downloader ({SUPPORTED_HINT})",
    )
    p.add_argument("url", nargs="?", help="Video/post URL to download")
    p.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help="output folder (default: ~/Downloads)",
    )
    p.add_argument("-a", "--audio-only", action="store_true", help="audio only (mp3)")
    p.add_argument(
        "-q",
        "--quality",
        default="best",
        help="quality: best, 1080, 720, 480, 360 (default: best)",
    )
    p.add_argument(
        "--allow-playlist", action="store_true", help="allow full playlist download"
    )
    p.add_argument(
        "--max",
        type=int,
        default=None,
        help="max batch items (profile/playlist), e.g. --max 5",
    )
    p.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="skip batch download confirmation",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="list batch items only, no downloading",
    )
    p.add_argument(
        "--cookies",
        default=None,
        help="path to YOUR cookies.txt (required for login content)",
    )
    p.add_argument(
        "--proxy",
        default=None,
        help="http/https/socks5 proxy, e.g. socks5h://127.0.0.1:9050 or http://127.0.0.1:8080",
    )
    p.add_argument(
        "--tor",
        action="store_true",
        help="force traffic through Tor (socks5h://127.0.0.1:9050). Tor must be running.",
    )
    p.add_argument(
        "--no-proxy",
        action="store_true",
        help="force direct connection without Tor/proxy (for login content)",
    )
    p.add_argument(
        "--random-ua",
        action="store_true",
        default=True,
        help="(default ON) randomize User-Agent each run",
    )
    p.add_argument(
        "--no-random-ua",
        action="store_true",
        help="disable random UA, use fixed default",
    )
    p.add_argument(
        "--user-agent",
        default=None,
        help="manual User-Agent (overrides default/random)",
    )
    p.add_argument(
        "--cloud",
        "--sharepoint",
        dest="cloud",
        action="store_true",
        help="force cloud-drive preview mode (auto from preview/share URLs)",
    )
    p.add_argument(
        "--scribd",
        action="store_true",
        help="force scribd document mode (auto from scribd.com URLs)",
    )
    p.add_argument(
        "--wait",
        type=int,
        default=25,
        help="seconds to wait for preview to load (default: 25)",
    )
    p.add_argument(
        "--direct",
        action="store_true",
        help="force direct-file mode (auto from .pdf/.zip/... extensions)",
    )
    p.add_argument(
        "--output-file",
        default=None,
        help="output file name (e.g. Thesis.pdf). Default: guess from URL/header)",
    )
    p.add_argument(
        "--list-formats",
        action="store_true",
        help="list available formats without downloading",
    )
    p.add_argument(
        "--info",
        action="store_true",
        help="show title/uploader/duration without downloading",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="verbose yt-dlp output")
    p.add_argument("--no-banner", action="store_true", help="hide ASCII banner")
    p.add_argument(
        "--paranoid",
        action="store_true",
        help="fail-closed: require proven anonymous route + refuse cookies/login",
    )
    p.add_argument(
        "--url-file",
        default=None,
        help="read URL from file (first non-empty line) so tokens stay out of shell history/ps",
    )
    p.add_argument(
        "--check", action="store_true", help="check ffmpeg & yt-dlp installation"
    )
    p.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="interactive Q&A wizard mode (auto when no URL given in terminal)",
    )
    return p


def _read_url(args: argparse.Namespace) -> str | None:
    if args.url_file:
        if args.url:
            print(
                "[jackthesolo] choose one: URL argument or --url-file",
                file=sys.stderr,
            )
            return None
        try:
            for line in Path(args.url_file).read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
            print("[jackthesolo] --url-file is empty", file=sys.stderr)
            return None
        except OSError as e:  # noqa: BLE001
            print(f"[jackthesolo] --url-file unreadable: {e}", file=sys.stderr)
            return None
    return args.url


def collect_wizard_argv(ask=input, default_url: str | None = None) -> list[str] | None:
    """Q&A wizard, return ready-to-run argv (None = cancelled)."""
    MODE_DESC = {
        "cloud": "cloud preview link (needs login)",
        "scribd": "scribd document (no login needed)",
        "direct": "direct file",
        "media": "video/music",
    }
    print("jackthesolo wizard (empty means default, Ctrl+C cancels).")
    url = (
        ask(f"1. Paste URL{f' [{default_url}]' if default_url else ''}: ") or ""
    ).strip()
    if not url:
        url = (default_url or "").strip()
    url = url.strip("'\" ")
    if not url:
        print("Empty URL, cancelled.")
        return None
    mode = detect_source(url)
    print(f"   Terdeteksi: {mode} ({MODE_DESC[mode]})")

    argv = [url, "--no-banner"]
    cookies = (
        ask("2. Path to your cookies.txt (required for login, empty = none): ") or ""
    ).strip()
    if cookies:
        argv += ["--cookies", cookies]
    out = (
        ask(f"3. Output folder [{DEFAULT_OUTPUT}]: ") or ""
    ).strip() or DEFAULT_OUTPUT
    argv += ["-o", out]
    if mode == "media":
        if (ask("4. Audio only (MP3)? [y/N]: ") or "").strip().lower() in ("y", "yes"):
            argv.append("-a")
        else:
            q = (ask("   Quality [best/720/480]: ") or "").strip() or "best"
            if q != "best":
                argv += ["-q", q]
        name = (ask("5. Output file name (empty = auto): ") or "").strip()
    else:
        name = (ask("4. Output file name (empty = auto): ") or "").strip()
    if name:
        argv += ["--output-file", name]
    if mode != "cloud":
        if (
            ask("6. Paranoid mode (IP proof + no login)? [y/N]: ") or ""
        ).strip().lower() in ("y", "yes"):
            argv.append("--paranoid")
    print("Summary: " + " ".join(argv))
    if (ask("Run? [Y/n]: ") or "").strip().lower() in ("n", "no"):
        print("Cancelled.")
        return None
    argv.append("--yes")
    return argv


def run_wizard(default_url: str | None = None) -> int:
    try:
        argv = collect_wizard_argv(default_url=default_url)
    except KeyboardInterrupt:
        print()
        return 130
    except EOFError:
        print()
        return 2
    if argv is None:
        return 2
    return main(argv)


def _batch_username(url: str) -> str:
    import re

    m = re.search(r"tiktok\.com/@([\w.-]+)", url)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", m.group(1)) if m else "batch"
    return name or "batch"


def _flat_entries(dl, url: str) -> list:
    """Fast ID-level enumeration for batch mode (flat, no per-item fetch)."""
    import yt_dlp

    opts = dl._ydl_opts({"quiet": True, "skip_download": True, "extract_flat": True})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info.get("entries") or []


def _entry_url(e: dict) -> str | None:
    u = e.get("url") or ""
    return u if u.startswith("http") else None


def _tiktok_single(args, url: str, cookies, anon_ua, output_file=None, output_dir=None):
    """Subsripper engine for one item. Returns files, None on failure."""
    from .tiktok import download_tiktok, is_tiktok_detail_url

    if not (is_tiktok_detail_url(url) and not (args.info or args.list_formats)):
        return None
    try:
        eff = resolve_proxy(args.proxy, args.tor, no_proxy=args.no_proxy)
        return download_tiktok(
            url,
            cookies_file=cookies,
            output_dir=output_dir or args.output,
            output_file=output_file,
            proxy=eff,
            user_agent=args.user_agent,
            random_ua=anon_ua,
            allow_direct_fallback=args.no_proxy,
        )
    except Exception as e:  # noqa: BLE001
        print(
            f"[jackthesolo] tiktok failed ({type(e).__name__}), falling back to yt-dlp...",
            file=sys.stderr,
        )
        if args.verbose:
            print(f"detail: {sanitize_text(e)}", file=sys.stderr)
        return None


def _run_batch(args, dl, url: str, cookies, anon_ua) -> int:
    """Batch into username/ folder: preview list first, confirm, then download."""
    from .progress import BatchView, Spinner

    user = _batch_username(url)
    out_dir = Path(args.output) / user
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[jackthesolo] batch folder: {out_dir}/")

    spin = Spinner().start("listing items...")
    try:
        entries = _flat_entries(dl, url)
    except Exception as e:  # noqa: BLE001
        spin.stop()
        print(
            f"[jackthesolo] batch list failed ({type(e).__name__}), aborting.",
            file=sys.stderr,
        )
        return 1
    spin.stop()
    if args.max:
        entries = entries[: args.max]
    print(
        f"[jackthesolo] preview: {len(entries)} item(s)"
        + (" (dry run)" if args.dry_run else "")
    )
    for i, e in enumerate(entries, 1):
        title = e.get("title") or e.get("id") or "?"
        print(f"  {i}. {title} ({e.get('id')})")
    if not args.dry_run and not args.yes and sys.stdin.isatty():
        try:
            ans = input(f"Continue to download {len(entries)} item(s)? [Y/n]: ")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 2
        if ans.strip().lower() in ("n", "no"):
            print("Cancelled.")
            return 2

    batch_dl = JackDownloader(
        output_dir=out_dir,
        audio_only=args.audio_only,
        quality=args.quality,
        no_playlist=True,
        cookies_file=cookies,
        verbose=args.verbose,
        proxy=args.proxy,
        use_tor=args.tor,
        no_proxy=args.no_proxy,
        user_agent=args.user_agent,
        random_ua=anon_ua,
    )
    view = BatchView()
    files_all: list = []
    videos = photos = 0
    for i, e in enumerate(entries, 1):
        item_url = _entry_url(e)
        if not item_url:
            view.add(f"  {i}. skip (no URL for id {e.get('id')})")
            continue
        if args.dry_run:
            try:
                info = batch_dl.get_info(item_url)
            except Exception:  # noqa: BLE001
                view.add(f"  {i}. [?] {item_url}")
                continue
            kind = "video" if (info.get("duration") or 0) > 0 else "photo"
            videos += kind == "video"
            photos += kind == "photo"
            view.add(f"  {i}. [{kind}] {info.get('title')} ({info.get('id')})")
            continue
        label = sanitize_url(item_url)
        if len(label) > 70:
            label = label[:67] + "..."
        idx = view.add(f"[{i}/{len(entries)}] {label} ... waiting")
        view.freeze()
        saved_here = _tiktok_single(
            args, item_url, cookies, anon_ua, output_dir=out_dir
        )
        if saved_here is None:
            try:
                saved_here = batch_dl.download(item_url, view=view, view_idx=idx)
            except Exception as e2:  # noqa: BLE001
                view.freeze()
                print(
                    f"  item failed ({type(e2).__name__}), continuing...",
                    file=sys.stderr,
                )
                view.set(idx, f"[{i}/{len(entries)}] FAILED")
                continue
        else:
            view.set(idx, f"[{i}/{len(entries)}] done: {len(saved_here)} file(s)")
        files_all += saved_here or []
    view.freeze()
    if args.dry_run:
        print(
            f"[jackthesolo] found {len(entries)} item(s): {videos} video, {photos} photo"
        )
    else:
        print(f"[jackthesolo] total {len(files_all)} file(s) -> {out_dir}/")
    return 0


def _enforce_paranoid(args: argparse.Namespace, mode: str) -> int:
    """Fail-closed mode. Return 0 on pass, exit code on failure."""
    from .privacy import egress_ip

    if args.cookies:
        print(
            "[jackthesolo] --paranoid refuses --cookies: login means identified. "
            "Drop --cookies for anonymous public downloads.",
            file=sys.stderr,
        )
        return 2
    if mode == "cloud":
        print(
            "[jackthesolo] --paranoid refuses cloud mode: needs login, cannot be anonymous.",
            file=sys.stderr,
        )
        return 2
    eff = resolve_proxy(args.proxy, args.tor, no_proxy=args.no_proxy)
    if not eff:
        print(
            "[jackthesolo] --paranoid: no anonymous route. Start Tor or set --proxy.",
            file=sys.stderr,
        )
        return 2
    direct = egress_ip(None)
    via = egress_ip(eff)
    if not via:
        print(
            f"[jackthesolo] --paranoid: egress via {eff} failed. Fix proxy/Tor.",
            file=sys.stderr,
        )
        return 2
    if direct and via == direct:
        print(
            f"[jackthesolo] --paranoid: proxy IP ({via}) equals direct IP. Leaking.",
            file=sys.stderr,
        )
        return 2
    print(f"[jackthesolo] --paranoid: egress {via} (direct: {direct or '?'}) [pass]")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.no_banner:
        print_banner()

    if args.check:
        from importlib.metadata import version

        from .privacy import egress_ip, tor_available

        try:
            print(f"yt-dlp: {version('yt-dlp')}")
        except Exception:
            print("yt-dlp: NOT INSTALLED")
        print(
            f"ffmpeg: {'OK' if JackDownloader.check_ffmpeg() else 'MISSING (audio-only/merge needs ffmpeg)'}"
        )
        print(f"jackthesolo: v{__version__}")
        eff = resolve_proxy(args.proxy, args.tor, no_proxy=args.no_proxy)
        print(f"default proxy: {eff or 'direct'}")
        print(
            f"default user-agent: {'random (ON)' if not args.no_random_ua else 'fixed (OFF)'}"
        )
        print(f"tor 127.0.0.1:9050: {'OPEN' if tor_available() else 'closed'}")
        print(f"direct egress: {egress_ip(None) or 'check failed'}")
        if eff:
            print(f"egress via route: {egress_ip(eff) or 'FAILED: route leaking/dead'}")
        else:
            print(
                "egress via route: - (no proxy/Tor, your real IP is visible to servers)"
            )
        try:
            import playwright  # noqa: F401

            print("playwright: OK (cloud mode ready)")
        except ImportError:
            print("playwright: MISSING (needed for cloud mode: pip install playwright)")
        return 0

    if args.interactive and not args.check:
        return run_wizard(default_url=args.url)

    url = _read_url(args)
    if not url:
        if not args.url_file and sys.stdin.isatty():
            return run_wizard()
        if not args.url_file:
            build_parser().print_help()
        return 2

    anon_ua = True  # paranoid forces it; otherwise random by default
    if args.no_random_ua and not args.paranoid:
        anon_ua = False

    # Auto-detect: scribd/cloud/direct/media
    if args.scribd:
        mode = "scribd"
    elif args.cloud:
        mode = "cloud"
    elif args.direct:
        mode = "direct"
    else:
        mode = detect_source(url)
        print(f"[jackthesolo] mode otomatis: {mode}", flush=True)

    if args.paranoid:
        rc = _enforce_paranoid(args, mode)
        if rc:
            return rc

    # Without a Tor/proxy route, direct/media are refused (bypass: --no-proxy). Cloud is
    # always direct since it needs login (identity known, Tor likely blocked).
    if mode == "cloud":
        print(
            "[jackthesolo] cloud mode: direct connection (login = server knows your account)",
            flush=True,
        )
    else:
        eff = resolve_proxy(args.proxy, args.tor, no_proxy=args.no_proxy)
        if not eff and not args.no_proxy:
            print(
                "[jackthesolo] anonymity required: Tor is down and no --proxy.\n"
                "Start Tor (sudo systemctl start tor) or set --proxy.\n"
                "Emergency bypass (IP visible): add --no-proxy.",
                file=sys.stderr,
            )
            return 2
        if args.no_proxy and not eff:
            print(
                "[jackthesolo] WARNING: --no-proxy = direct connection, your real IP is visible to servers.",
                flush=True,
            )

    # Cookies only via --cookies param (each user brings their own).
    cookies = args.cookies
    if cookies:
        from .privacy import ensure_private

        ensure_private(cookies)

    # Mode cloud (link preview/share) : wajib --cookies
    if mode == "cloud":
        from .cloud import download_cloud

        try:
            if not cookies:
                print(
                    "[jackthesolo] This link needs login.\n"
                    "Use YOUR OWN cookies:\n"
                    "  1. Open the link in Chrome logged into your account\n"
                    "  2. Export via the 'Get cookies.txt LOCALLY' extension (pick the site domain)\n"
                    '  3. jackthesolo "URL" --cookies /path/to/your/cookies.txt',
                    file=sys.stderr,
                )
                return 2
            dest = download_cloud(
                url,
                output_dir=args.output,
                output_file=args.output_file,
                cookies_file=cookies,
                wait_s=args.wait,
            )
            print(f"[jackthesolo] saved: {dest}")
            return 0
        except Exception:  # noqa: BLE001
            print(
                "[jackthesolo] ERROR: download failed (rerun with -v for details)",
                file=sys.stderr,
            )
            if args.verbose:
                import traceback

                traceback.print_exc()
            return 1

    # Scribd mode: document -> PDF via embed, no login needed
    if mode == "scribd":
        from .scribd import download_scribd

        try:
            dest = download_scribd(
                url,
                output_dir=args.output,
                output_file=args.output_file,
                user_agent=args.user_agent,
                random_ua=anon_ua,
            )
            print(f"[jackthesolo] saved: {dest}")
            return 0
        except Exception:  # noqa: BLE001
            print(
                "[jackthesolo] ERROR: download failed (rerun with -v for details)",
                file=sys.stderr,
            )
            if args.verbose:
                import traceback

                traceback.print_exc()
            return 1

    # Direct mode: straight file URL (cookies optional, bring your own if needed)
    if mode == "direct" or args.output_file:
        try:
            dest = download_file(
                url,
                output_dir=args.output,
                output_file=args.output_file,
                cookies_file=cookies,
                proxy=args.proxy,
                use_tor=args.tor,
                no_proxy=args.no_proxy,
                user_agent=args.user_agent,
                random_ua=anon_ua,
            )
            print(f"[jackthesolo] saved: {dest}")
            return 0
        except Exception as e:  # noqa: BLE001
            print("[jackthesolo] ERROR: download failed", file=sys.stderr)
            if args.verbose:
                print(
                    f"detail: {type(e).__name__}: {sanitize_text(e)}", file=sys.stderr
                )
            return 1

    # TikTok mode: TLS impersonation + universal data when available.
    # URL /video|photo/<id> + own cookies; otherwise plain yt-dlp.
    from .tiktok import download_tiktok, is_tiktok_detail_url, is_tiktok_profile_url

    tiktok_tried = False
    if is_tiktok_detail_url(url) and not (args.info or args.list_formats):
        tiktok_tried = True
        files = _tiktok_single(
            args, url, cookies, anon_ua, output_file=args.output_file
        )
        if files is not None:
            print(f"[jackthesolo] total {len(files)} file(s) -> {args.output}/")
            return 0

    batch_profile = is_tiktok_profile_url(url)
    if batch_profile and not args.allow_playlist:
        print("[jackthesolo] Profile URL detected: batch mode (playlist ON)")

    dl = JackDownloader(
        output_dir=args.output,
        audio_only=args.audio_only,
        quality=args.quality,
        no_playlist=(not args.allow_playlist and not batch_profile),
        cookies_file=cookies,
        verbose=args.verbose,
        proxy=args.proxy,
        use_tor=args.tor,
        no_proxy=args.no_proxy,
        user_agent=args.user_agent,
        random_ua=anon_ua,
        max_downloads=args.max,
    )

    try:
        if args.info:
            info = dl.get_info(url)
            print(f"title    : {info.get('title')}")
            print(f"uploader : {info.get('uploader')}")
            print(f"duration : {info.get('duration')} s")
            print(f"source   : {info.get('webpage_url')}")
            return 0
        if args.list_formats:
            for f in dl.list_formats(url):
                print(
                    f"{f.get('format_id'):10} {str(f.get('ext')):6} {str(f.get('resolution') or f.get('format_note') or ''):15} {f.get('filesize_approx') or ''}"
                )
            return 0
        if batch_profile:
            return _run_batch(args, dl, url, cookies, anon_ua)
        files = dl.download(url)
        print(f"[jackthesolo] total {len(files)} file(s) -> {args.output}/")
        return 0
    except Exception as e:  # noqa: BLE001
        print(
            "[jackthesolo] ERROR: failed (rerun with -v for details)",
            file=sys.stderr,
        )
        if tiktok_tried and not cookies:
            print(
                "[jackthesolo] This post has no data on public pages "
                "(tried direct and via Tor). Retry with --cookies "
                "from an account that can open that post.",
                file=sys.stderr,
            )
        if args.verbose:
            print(f"detail: {type(e).__name__}: {sanitize_text(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
