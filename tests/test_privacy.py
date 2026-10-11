from jackthesolo.privacy import (
    TOR_DEFAULT,
    UA_POOL,
    egress_ip,
    ensure_private,
    isolated_tor_proxy,
    pick_ua,
    requests_proxies,
    resolve_proxy,
    sanitize_text,
    sanitize_url,
    tor_available,
)


class TestPickUA:
    def test_manual_wins(self):
        assert pick_ua("Custom/1.0") == "Custom/1.0"

    def test_fixed_when_not_random(self):
        assert pick_ua(random_ua=False) == UA_POOL[0]

    def test_random_from_pool(self):
        for _ in range(20):
            assert pick_ua() in UA_POOL


class TestIsolatedTorProxy:
    def test_format(self):
        p = isolated_tor_proxy()
        assert p.startswith("socks5h://") and p.endswith("@127.0.0.1:9050")

    def test_credentials_unique(self):
        assert isolated_tor_proxy() != isolated_tor_proxy()


class TestResolveProxy:
    def test_no_proxy_wins(self):
        assert resolve_proxy("http://x", use_tor=True, no_proxy=True) is None

    def test_explicit_proxy(self):
        assert resolve_proxy("http://x") == "http://x"

    def test_use_tor(self):
        assert resolve_proxy(use_tor=True) == TOR_DEFAULT

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("JACKTHESOLO_PROXY", "socks5h://env:9150")
        assert resolve_proxy() == "socks5h://env:9150"

    def test_tor_autodetect(self, monkeypatch):
        monkeypatch.setattr("jackthesolo.privacy.tor_available", lambda: True)
        assert resolve_proxy() == TOR_DEFAULT

    def test_nothing(self, monkeypatch):
        monkeypatch.setattr("jackthesolo.privacy.tor_available", lambda: False)
        assert resolve_proxy() is None


class TestRequestsProxies:
    def test_none(self):
        assert requests_proxies(None) is None

    def test_both_schemes(self):
        p = requests_proxies("http://x")
        assert p == {"http": "http://x", "https": "http://x"}


class TestSanitizeURL:
    def test_sensitive_keys_masked(self):
        u = sanitize_url("https://x.com/f?share=SECRET&ga=1&id=abc")
        assert "SECRET" not in u and "ga=1" not in u and "abc" in u

    def test_no_query_passthrough(self):
        assert sanitize_url("https://x.com/f.pdf") == "https://x.com/f.pdf"

    def test_garbage_safe(self):
        assert isinstance(sanitize_url("::not a url::"), str)


class TestSanitizeText:
    def test_pairs_masked(self):
        out = sanitize_text("GET https://x/f?share=RAHASIA&e=abc token=XYZ")
        assert "RAHASIA" not in out and "XYZ" not in out

    def test_plain_text_kept(self):
        assert sanitize_text("selesai: file.pdf") == "selesai: file.pdf"


class TestEnsurePrivate:
    def test_chmod_600(self, tmp_path):
        f = tmp_path / "c.txt"
        f.write_text("x")
        import os

        os.chmod(f, 0o644)
        ensure_private(str(f))
        assert (os.stat(f).st_mode & 0o777) == 0o600

    def test_missing_file_ok(self):
        ensure_private("/tmp/definitely-not-here-xyz")  # no raise


class TestEgressIP:
    def test_failure_returns_none(self, monkeypatch):
        import requests

        monkeypatch.setattr(
            requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("down"))
        )
        assert egress_ip(None) is None


class TestTorAvailable:
    def test_closed_port(self):
        assert tor_available(port=59999, timeout=0.2) is False
