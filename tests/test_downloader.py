import pytest

from jackthesolo.downloader import JackDownloader


class TestFormatSelector:
    @pytest.mark.parametrize(
        ("q", "expected"),
        [
            ("best", "bestvideo+bestaudio/best"),
            ("720", "bestvideo[height<=720]+bestaudio/best[height<=720]/best"),
            ("720p", "bestvideo[height<=720]+bestaudio/best[height<=720]/best"),
            ("1080", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"),
        ],
    )
    def test_quality_map(self, q, expected):
        assert JackDownloader(quality=q)._format_selector() == expected

    def test_default_is_highest(self):
        d = JackDownloader()
        assert d.quality == "best"
        assert d._format_selector() == "bestvideo+bestaudio/best"
        assert d._ydl_opts()["format"] == "bestvideo+bestaudio/best"

    def test_audio_only(self):
        assert JackDownloader(audio_only=True)._format_selector() == "bestaudio/best"


class TestOptions:
    def test_tor_isolates_circuit(self, monkeypatch):
        monkeypatch.setattr("jackthesolo.privacy.tor_available", lambda: True)
        dl = JackDownloader(use_tor=True)
        assert dl.proxy and dl.proxy.endswith("@127.0.0.1:9050")

    def test_no_proxy(self):
        assert JackDownloader(no_proxy=True).proxy is None

    def test_audio_postprocessor(self):
        d = JackDownloader(audio_only=True)
        pp = d._ydl_opts()["postprocessors"][0]
        assert pp["preferredcodec"] == "mp3"

    def test_cookies_wired(self):
        d = JackDownloader(cookies_file="/tmp/c.txt")
        assert d._ydl_opts()["cookiefile"] == "/tmp/c.txt"

    def test_check_ffmpeg(self):
        assert isinstance(JackDownloader.check_ffmpeg(), bool)

    def test_cookies_login_detection(self, tmp_path):
        logged = tmp_path / "in.txt"
        logged.write_text(
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tFALSE\t9999999999\tSID\tabc\n"
        )
        anon = tmp_path / "anon.txt"
        anon.write_text(
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tFALSE\t9999999999\tVISITOR_INFO1_LIVE\tabc\n"
        )
        assert JackDownloader._cookies_look_logged_in(str(logged)) is True
        assert JackDownloader._cookies_look_logged_in(str(anon)) is False
        assert JackDownloader._cookies_look_logged_in(None) is False
        assert JackDownloader._cookies_look_logged_in("/tmp/nope-xyz") is True


class TestAgeGateFallback:
    def test_android_retry_on_age_gate(self, monkeypatch, tmp_path):
        import yt_dlp

        calls = []

        class FakeYDL:
            def __init__(self, opts):
                calls.append(opts)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def download(self, urls):
                if len(calls) == 1:
                    raise yt_dlp.utils.DownloadError("Sign in to confirm your age")
                calls.append("ok")

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
        dl = JackDownloader(output_dir=tmp_path, no_proxy=True)
        assert dl.download("https://www.youtube.com/watch?v=x") == []
        assert calls[1]["extractor_args"] == {"youtube": {"player_client": ["android"]}}

    def test_non_age_error_propagates(self, monkeypatch, tmp_path):
        import yt_dlp

        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def download(self, urls):
                raise yt_dlp.utils.DownloadError("HTTP 500 Server Error")

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
        with pytest.raises(yt_dlp.utils.DownloadError):
            JackDownloader(output_dir=tmp_path, no_proxy=True).download(
                "https://www.youtube.com/watch?v=x"
            )

    def test_non_youtube_no_retry(self, monkeypatch, tmp_path):
        import yt_dlp

        n = {"c": 0}

        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def download(self, urls):
                n["c"] += 1
                raise yt_dlp.utils.DownloadError("Sign in to confirm your age")

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
        with pytest.raises(yt_dlp.utils.DownloadError):
            JackDownloader(output_dir=tmp_path, no_proxy=True).download(
                "https://example.com/f.mp4"
            )
        assert n["c"] == 1


class TestPickClient:
    def test_winner_max_height(self, monkeypatch, tmp_path):
        import yt_dlp

        heights = {"default": 360, "android": 720, "ios": 480, "tv": 1080}

        class FakeYDL:
            def __init__(self, opts):
                client = (
                    opts.get("extractor_args", {})
                    .get("youtube", {})
                    .get("player_client", [None])
                )[0]
                self._h = heights["default" if client is None else client]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, url, download=False):
                return {"formats": [{"height": self._h}, {"height": 144}]}

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
        dl = JackDownloader(output_dir=tmp_path, no_proxy=True)
        assert dl._pick_client(["https://www.youtube.com/watch?v=x"], {}) == "tv"

    def test_non_youtube_none(self, tmp_path):
        dl = JackDownloader(output_dir=tmp_path, no_proxy=True)
        assert dl._pick_client(["https://example.com/f.mp4"], {}) is None


class TestBatch:
    def test_max_downloads_wired(self, tmp_path):
        d = JackDownloader(output_dir=tmp_path, no_proxy=True, max_downloads=5)
        assert d._ydl_opts()["max_downloads"] == 5

    def test_max_downloads_default_absent(self, tmp_path):
        assert (
            "max_downloads"
            not in JackDownloader(output_dir=tmp_path, no_proxy=True)._ydl_opts()
        )


class TestMaxReached:
    def test_max_downloads_clean_exit(self, monkeypatch, tmp_path, capsys):
        import yt_dlp

        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def download(self, urls):
                raise yt_dlp.utils.MaxDownloadsReached()

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
        dl = JackDownloader(output_dir=tmp_path, no_proxy=True, max_downloads=2)
        assert dl.download("https://www.tiktok.com/@u") == []
        assert "--max reached" in capsys.readouterr().out
