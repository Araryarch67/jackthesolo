import os


class TestCloudSecurity:
    def test_browser_context_hides_timezone(self):
        src = open(
            os.path.join(os.path.dirname(__file__), "..", "jackthesolo", "cloud.py")
        ).read()
        assert 'timezone_id="UTC"' in src
        assert 'locale="en-US"' in src

    def test_default_cookies_domain_not_hardcoded(self):
        src = open(
            os.path.join(os.path.dirname(__file__), "..", "jackthesolo", "cloud.py")
        ).read()
        assert "itits" not in src
