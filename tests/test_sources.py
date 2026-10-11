from jackthesolo.sources import CLOUD_HOSTS, detect_source


class TestDetectSource:
    def test_sharepoint_cloud(self):
        assert detect_source("https://contoh.sharepoint.com/shared?x=1") == "cloud"

    def test_onedrive_cloud(self):
        assert detect_source("https://contoso-my.sharepoint.com/:b:/g/x") == "cloud"

    def test_one_drv_cloud(self):
        assert detect_source("https://1drv.ms/b/s!Abc") == "cloud"

    def test_direct_extensions(self):
        for ext in ("pdf", "zip", "mp4", "mkv"):
            assert detect_source(f"https://e.com/file.{ext}") == "direct"

    def test_media_fallback(self):
        assert detect_source("https://www.tiktok.com/@u/video/1") == "media"
        assert detect_source("https://www.youtube.com/watch?v=x") == "media"

    def test_cloud_hosts_covers_sharepoint(self):
        assert "sharepoint.com" in CLOUD_HOSTS
