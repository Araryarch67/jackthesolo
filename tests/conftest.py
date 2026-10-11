import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAKE_COOKIES = os.path.join(ROOT, "tests", "fixtures", "cookies_dummy.txt")


@pytest.fixture()
def dummy_cookies(tmp_path):
    p = tmp_path / "cookies.txt"
    p.write_text(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tFALSE\t9999999999\tsession\tabc123\n"
    )
    return str(p)


@pytest.fixture(autouse=True)
def _no_proxy_env(monkeypatch):
    for k in (
        "JACKTHESOLO_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "https_proxy",
        "http_proxy",
    ):
        monkeypatch.delenv(k, raising=False)
