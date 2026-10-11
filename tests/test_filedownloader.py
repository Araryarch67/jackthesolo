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
