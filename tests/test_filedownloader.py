import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jackthesolo.filedownloader import (
    download_file,
    guess_filename,
    load_session_with_cookies,
)


class TestGuessFilename:
    def test_from_path(self):
        assert guess_filename("https://x.com/a/b/file.pdf") == "file.pdf"

    def test_fallback(self):
        assert guess_filename("https://x.com/") == "download.bin"

    def test_content_disposition(self):
        class R:
            headers = {"content-disposition": 'attachment; filename="laporan.pdf"'}

        assert guess_filename("https://x.com/dl", R()) == "laporan.pdf"


class TestLoadSession:
    def test_no_cookies_no_proxy(self):
        s = load_session_with_cookies(None, no_proxy=True)
        assert s.proxies == {} and s.trust_env is True

    def test_cookies_loaded(self, dummy_cookies):
        s = load_session_with_cookies(dummy_cookies, no_proxy=True)
        assert any(c.name == "session" for c in s.cookies)


class _Handler(BaseHTTPRequestHandler):
    seen = {}

    def do_GET(self):
        type(self).seen[self.path] = self.headers.get("Cookie")
        if self.path == "/private" and not self.headers.get("Cookie"):
            self.send_response(401)
            self.end_headers()
            return
        body = b"HELLO"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def srv():
    _Handler.seen = {}
    s = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


class TestDownloadFile:
    def test_public_no_cookies_sent(self, srv, tmp_path, dummy_cookies):
        p = download_file(
            f"{srv}/public",
            output_dir=tmp_path,
            output_file="a.bin",
            cookies_file=dummy_cookies,
            no_proxy=True,
        )
        assert p.read_bytes() == b"HELLO"
        assert _Handler.seen["/public"] is None  # cookies tidak dipakai bila tak perlu

    def test_private_uses_cookies_on_retry(self, srv, tmp_path, dummy_cookies):
        p = download_file(
            f"{srv}/private",
            output_dir=tmp_path,
            output_file="b.bin",
            cookies_file=dummy_cookies,
            no_proxy=True,
        )
        assert p.read_bytes() == b"HELLO"
        assert _Handler.seen["/private"]  # cookie terkirim setelah 401

    def test_private_without_cookies_rejected_with_hint(self, srv, tmp_path):
        with pytest.raises(PermissionError, match="--cookies"):
            download_file(
                f"{srv}/private",
                output_dir=tmp_path,
                output_file="c.bin",
                no_proxy=True,
            )

    def test_part_file_cleaned(self, srv, tmp_path, dummy_cookies):
        download_file(
            f"{srv}/public",
            output_dir=tmp_path,
            output_file="d.bin",
            cookies_file=dummy_cookies,
            no_proxy=True,
        )
        assert not list(tmp_path.glob("*.part"))


class TestRetryResume:
    def test_transient_retried_then_ok(self, tmp_path, monkeypatch):
        import requests

        from jackthesolo import filedownloader as fd

        calls = {"n": 0}

        class Resp:
            status_code = 200
            headers = {"content-length": "3", "content-type": "text/plain"}

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=1):
                yield b"abc"

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class S:
            def get(self, *a, **k):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise requests.ConnectionError("boom")
                return Resp()

        monkeypatch.setattr(fd, "load_session_with_cookies", lambda *a, **k: S())
        monkeypatch.setattr("time.sleep", lambda s: None)
        p = fd.download_file(
            "http://x/f.bin", output_dir=tmp_path, output_file="f.bin",
            no_proxy=True, retries=3,
        )
        assert p.read_bytes() == b"abc" and calls["n"] == 2

    def test_fatal_not_retried(self, tmp_path, monkeypatch):
        from jackthesolo import filedownloader as fd

        calls = {"n": 0}

        class Resp:
            status_code = 404
            headers = {"content-type": "text/plain"}

            def raise_for_status(self):
                import requests

                raise requests.HTTPError(response=self)

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class S:
            def get(self, *a, **k):
                calls["n"] += 1
                return Resp()

        monkeypatch.setattr(fd, "load_session_with_cookies", lambda *a, **k: S())
        import pytest as _pytest

        with _pytest.raises(Exception):
            fd.download_file(
                "http://x/f.bin", output_dir=tmp_path, output_file="f.bin",
                no_proxy=True, retries=3,
            )
        assert calls["n"] == 1

    def test_resume_append(self, tmp_path, monkeypatch):
        from jackthesolo import filedownloader as fd

        seen = {}

        class Resp:
            status_code = 206
            headers = {"content-range": "bytes 3-5/6", "content-type": "text/plain"}

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=1):
                yield b"def"

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class S:
            def get(self, url, headers=None, **k):
                seen["range"] = (headers or {}).get("Range")
                return Resp()

        (tmp_path / "f.bin.part").write_bytes(b"abc")
        monkeypatch.setattr(fd, "load_session_with_cookies", lambda *a, **k: S())
        p = fd.download_file(
            "http://x/f.bin", output_dir=tmp_path, output_file="f.bin",
            no_proxy=True,
        )
        assert p.read_bytes() == b"abcdef"
        assert seen["range"] == "bytes=3-"

    def test_total_from_range(self):
        from jackthesolo.filedownloader import _total_from_range

        assert _total_from_range("bytes 3-5/6") == 6
        assert _total_from_range(None) == 0
        assert _total_from_range("garbage") == 0
