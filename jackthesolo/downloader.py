"""Core downloader wrapping yt-dlp."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yt_dlp

from .privacy import (
    TOR_DEFAULT,
    isolated_tor_proxy,
    pick_ua,
    resolve_proxy,
    sanitize_url,
)
from .progress import Spinner, bar


SUPPORTED_HINT = "video, music, direct files, cloud drive, all platforms"


class _Logger:
    def debug(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        print(f"\n{msg}")


class JackDownloader:
    def __init__(
        self,
        output_dir: str | Path = str(Path.home() / "Downloads"),
        audio_only: bool = False,
        quality: str = "best",
        no_playlist: bool = True,
        cookies_file: str | None = None,
        verbose: bool = False,
        proxy: str | None = None,
        use_tor: bool = False,
        no_proxy: bool = False,
        user_agent: str | None = None,
        random_ua: bool = True,
        max_downloads: int | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.audio_only = audio_only
        self.quality = quality
        self.no_playlist = no_playlist
        self.cookies_file = cookies_file
        self.verbose = verbose
        self.max_downloads = max_downloads
        self.proxy = resolve_proxy(proxy, use_tor, no_proxy=no_proxy)
        if self.proxy == TOR_DEFAULT:
            self.proxy = isolated_tor_proxy()  # circuit fresh per proses
        if self.proxy and self.proxy.endswith("@127.0.0.1:9050"):
            print("[jackthesolo] anonymous: via Tor, isolated circuit (random UA)")
        self.user_agent = pick_ua(user_agent, random_ua)

    def _format_selector(self) -> str:
        if self.audio_only:
            return "bestaudio/best"
        q = self.quality.lower().strip()
        if q in ("best", "worst"):
            return q + "video+bestaudio/best" if q == "best" else "worst"
        # q like 720, 720p, 1080
        h = "".join(c for c in q if c.isdigit())
        if h:
            return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
        return "bestvideo+bestaudio/best"

    def _ydl_opts(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "outtmpl": str(self.output_dir / "%(title)s [%(id)s].%(ext)s"),
            "format": self._format_selector(),
            "noplaylist": self.no_playlist,
            "quiet": not self.verbose,
            "no_warnings": not self.verbose,
            "merge_output_format": "mp4",
            "http_headers": {
                "User-Agent": self.user_agent,
                "Accept-Language": "en-US,en;q=0.5",
            },
            "socket_timeout": 30,
            "retries": 3,
            "logger": _Logger(),
        }
        if self.proxy:
            opts["proxy"] = self.proxy
        if self.audio_only:
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
        if self.max_downloads:
            opts["max_downloads"] = self.max_downloads
        if extra:
            opts.update(extra)
        return opts

    def get_info(self, url: str) -> dict[str, Any]:
        extra: dict[str, Any] = {"quiet": True, "skip_download": True}
        if self._is_youtube(url):
            winner = self._pick_client([url], {})
            if winner:
                extra["extractor_args"] = {"youtube": {"player_client": [winner]}}
        with yt_dlp.YoutubeDL(self._ydl_opts(extra)) as ydl:
            info = ydl.extract_info(url, download=False)
        return info or {}

    def list_formats(self, url: str) -> list[dict[str, Any]]:
        info = self.get_info(url)
        if "entries" in info:  # playlist
            info = info["entries"][0]
        return info.get("formats", [])

    _AGE_GATE_MARKERS = (
        "Sign in to confirm your age",
        "confirm your age",
        "age-gated",
    )
    _YT_CLIENT_FALLBACKS = ("android", "ios")
    _YT_CLIENT_PROBE = (None, "android", "ios", "tv")

    def _client_max_height(self, url: str, client: str | None) -> int:
        try:
            opts = self._ydl_opts({"quiet": True, "skip_download": True})
            if client:
                opts["extractor_args"] = {"youtube": {"player_client": [client]}}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            return max(
                (f.get("height") or 0 for f in info.get("formats", [])), default=0
            )
        except Exception:  # noqa: BLE001
            return 0

    def _pick_client(self, urls: list[str], overrides: dict[str, Any]) -> str | None:
        """Pick the highest-resolution client (YouTube only, no override)."""
        if "youtube" in str(overrides.get("extractor_args", "")):
            return None
        yt_urls = [u for u in urls if self._is_youtube(u)]
        if not yt_urls:
            return None
        best, winner = 0, None
        for client in self._YT_CLIENT_PROBE:
            h = self._client_max_height(yt_urls[0], client)
            print(f"[jackthesolo] client {client or 'default'}: max {h or 'failed'}p")
            if h > best:
                best, winner = h, client
        if winner:
            print(f"[jackthesolo] using client {winner} ({best}p)")
        return winner

    _LOGIN_COOKIE_NAMES = {
        "SID",
        "HSID",
        "SSID",
        "SAPISID",
        "__Secure-1PSID",
        "LOGIN_INFO",
    }

    @staticmethod
    def _cookies_look_logged_in(path: str | None) -> bool:
        if not path:
            return False
        try:
            import http.cookiejar

            jar = http.cookiejar.MozillaCookieJar(path)
            jar.load(ignore_discard=True, ignore_expires=True)
            names = {c.name for c in jar}
            return bool(names & JackDownloader._LOGIN_COOKIE_NAMES)
        except Exception:  # noqa: BLE001
            return True

    @staticmethod
    def _is_age_gate_error(e: Exception) -> bool:
        msg = str(e)
        return any(m in msg for m in JackDownloader._AGE_GATE_MARKERS)

    @staticmethod
    def _is_youtube(url: str) -> bool:
        host = url.lower()
        return "youtube.com" in host or "youtu.be" in host

    def download(
        self, url: str | list[str], view=None, view_idx: int = 0, **overrides: Any
    ) -> list[str]:
        urls = [url] if isinstance(url, str) else list(url)
        downloaded: list[str] = []
        _prep: list[Spinner] = [Spinner()]

        def _row(text: str) -> None:
            if view is not None:
                view.set(view_idx, text)

        def _hook(d: dict[str, Any]) -> None:
            if d.get("status") == "finished":
                f = d.get("filename", "")
                if f:
                    downloaded.append(f)
                if view is not None:
                    _row(f"done: {f or 'download'}")
                else:
                    _prep[0].stop()
                    if f:
                        print(f"[jackthesolo] done: {f}")
            elif d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes", 0)
                speed = (d.get("_speed_str") or "").strip()
                eta = (d.get("_eta_str") or "").strip()
                tail = f"@ {speed} ETA {eta}" if speed else ""
                if total:
                    line = f"{bar(done, total)} {tail}".rstrip()
                else:
                    line = f"… {done / 1024 / 1024:.1f} MB {tail}".rstrip()
                if view is not None:
                    _row(line)
                    return
                _prep[0].stop()
                sys.stdout.write(f"\r{line}")
                sys.stdout.flush()

        def _run(extra: dict[str, Any] | None = None) -> None:
            import yt_dlp.utils

            opts = self._ydl_opts()
            opts["progress_hooks"] = [_hook]
            if overrides:
                opts.update(overrides)
            if extra:
                opts.update(extra)
            if view is None:
                _prep[0] = Spinner().start("preparing download...")
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    for u in urls:
                        if view is None:
                            print(f"[jackthesolo] download: {sanitize_url(u)}")
                        try:
                            ydl.download([u])
                        except yt_dlp.utils.MaxDownloadsReached:
                            print(
                                "[jackthesolo] --max reached, stopping (saved files are safe)"
                            )
                            break
            finally:
                if view is None:
                    _prep[0].stop()
                    print()

        winner = self._pick_client(urls, overrides)
        base = (
            {"extractor_args": {"youtube": {"player_client": [winner]}}}
            if winner
            else None
        )
        try:
            _run(base)
        except Exception as e:  # noqa: BLE001
            if (
                any(self._is_youtube(u) for u in urls)
                and self._is_age_gate_error(e)
                and "youtube" not in str(overrides.get("extractor_args", ""))
            ):
                if self.cookies_file and not self._cookies_look_logged_in(
                    self.cookies_file
                ):
                    print(
                        "[jackthesolo] your cookies hold no login session "
                        "(no SID/HSID). Open the video in Chrome while logged in, "
                        "make sure it plays, then re-export your cookies.",
                        file=sys.stderr,
                    )
                tried = [winner] if winner else []
                for client in [c for c in self._YT_CLIENT_FALLBACKS if c not in tried]:
                    print(f"[jackthesolo] age gate detected, trying client {client}...")
                    try:
                        _run(
                            {"extractor_args": {"youtube": {"player_client": [client]}}}
                        )
                        break
                    except Exception as e2:  # noqa: BLE001
                        if not self._is_age_gate_error(e2):
                            raise
                        print(f"[jackthesolo] client {client} failed, continuing...")
                else:
                    self._run_resolvers(urls, downloaded)
            else:
                raise
        return downloaded

    def _run_resolvers(self, urls: list[str], downloaded: list[str]) -> None:
        from .filedownloader import download_file, load_session_with_cookies
        from .resolvers import resolve_any

        session = load_session_with_cookies(
            None,
            user_agent=self.user_agent,
            random_ua=False,
            proxy=self.proxy,
        )
        last: str | None = None
        for u in urls:
            direct, via = resolve_any(u, session)
            if not direct:
                last = "resolver returned no URL"
                continue
            print(f"[jackthesolo] resolver {via} dapat stream, download...")
            dest = download_file(
                direct,
                output_dir=self.output_dir,
                output_file=f"{self._page_id(u)}.mp4",
                user_agent=self.user_agent,
                random_ua=False,
                proxy=self.proxy,
            )
            downloaded.append(str(dest))
            return
        raise ValueError(
            f"all resolvers failed. last: {last}. "
            + (
                "Your cookies hold no login session; re-export while logged into Google. "
                if self.cookies_file
                and not self._cookies_look_logged_in(self.cookies_file)
                else "Public instances are down/blocked, retry later, "
                "or use --cookies (an age-verified account)."
            )
        )

    @staticmethod
    def _page_id(url: str) -> str:
        from .resolvers import extract_youtube_id

        return extract_youtube_id(url) or "video"

    @staticmethod
    def check_ffmpeg() -> bool:
        import shutil

        return shutil.which("ffmpeg") is not None
