import pytest

from jackthesolo.tiktok import (
    clean_url,
    collect_images,
    collect_urls,
    extract_video_id,
    get_item_struct,
    is_tiktok_detail_url,
    load_netscape_cookies,
    unique_path,
)


class TestCleanURL:
    def test_quote_wrapped(self):
        assert (
            clean_url("\"'https://www.tiktok.com/@u/video/1'\"")
            == "https://www.tiktok.com/@u/video/1"
        )

    def test_stray_quote(self):
        assert clean_url("'https://x ") == "https://x"

    def test_plain_kept(self):
        assert clean_url("  https://x  ") == "https://x"


class TestExtractVideoId:
    def test_video(self):
        assert extract_video_id("https://www.tiktok.com/@u/video/123456") == "123456"

    def test_photo(self):
        assert extract_video_id("https://www.tiktok.com/@u/photo/789") == "789"

    def test_no_id(self):
        with pytest.raises(ValueError):
            extract_video_id("https://www.tiktok.com/@u")


class TestIsDetailURL:
    def test_detail(self):
        assert is_tiktok_detail_url("https://www.tiktok.com/@u/video/1")

    def test_short_link_not_detail(self):
        assert not is_tiktok_detail_url("https://vt.tiktok.com/abc/")

    def test_non_tiktok(self):
        assert not is_tiktok_detail_url("https://example.com/video/1")


class TestCollectURLs:
    def _item(self):
        return {
            "video": {
                "bitrateInfo": [
                    {
                        "PlayAddr": {
                            "UrlList": [
                                "https://v19-cdn/x.mp4",
                                "https://aweme/v1/play/?t=tt_chain_token",
                            ]
                        }
                    },
                ],
                "playAddr": "https://v16-cdn/y.mp4",
            }
        }

    def test_aweme_first_and_token_fixed(self):
        out = collect_urls(self._item(), "TOK")
        assert out[0].startswith("https://aweme/v1/play/")
        assert "tt_chain_token" not in out[0] and "TOK" in out[0]

    def test_dedup(self):
        item = {"video": {"playAddr": "https://v/x.mp4"}}
        assert collect_urls(item, "") == ["https://v/x.mp4"]

    def test_empty(self):
        assert collect_urls({}, "") == []


class TestCollectImages:
    def test_priority_and_dedup(self):
        item = {
            "imagePost": {
                "images": [
                    {
                        "thumbnail": {"urlList": ["https://t1"]},
                        "imageURL": {"urlList": ["https://o1", "https://o1"]},
                    },
                    {"displayImage": {"urlList": ["https://d2"]}},
                ]
            }
        }
        assert collect_images(item) == ["https://o1", "https://d2"]

    def test_empty(self):
        assert collect_images({}) == []


class TestGetItemStruct:
    def test_found(self):
        data = {
            "__DEFAULT_SCOPE__": {
                "webapp.video-detail": {"itemInfo": {"itemStruct": {"id": "1"}}}
            }
        }
        assert get_item_struct(data, "1") == {"id": "1"}

    def test_id_mismatch_warns_but_returns(self, capsys):
        data = {
            "__DEFAULT_SCOPE__": {
                "webapp.video-detail": {"itemInfo": {"itemStruct": {"id": "2"}}}
            }
        }
        assert get_item_struct(data, "1") == {"id": "2"}
        assert "not 1" in capsys.readouterr().err

    def test_missing(self):
        with pytest.raises(ValueError):
            get_item_struct({"__DEFAULT_SCOPE__": {}}, "1")


class TestCookiesFile:
    def test_valid(self, tmp_path):
        f = tmp_path / "c.txt"
        f.write_text("# Netscape\n.example.com\tTRUE\t/\tFALSE\t1\ts\tabc\n")
        assert load_netscape_cookies(str(f)) == {"s": "abc"}

    def test_empty_rejected(self, tmp_path):
        f = tmp_path / "c.txt"
        f.write_text("# empty\n")
        with pytest.raises(ValueError):
            load_netscape_cookies(str(f))


class TestUniquePath:
    def test_no_clash(self, tmp_path):
        assert unique_path(tmp_path / "a.mp4") == tmp_path / "a.mp4"

    def test_clash_numbered(self, tmp_path):
        (tmp_path / "a.mp4").write_text("x")
        assert unique_path(tmp_path / "a.mp4") == tmp_path / "a_001.mp4"


class TestProfileURL:
    def test_profile(self):
        from jackthesolo.tiktok import is_tiktok_profile_url

        assert is_tiktok_profile_url("https://www.tiktok.com/@someuser")
        assert is_tiktok_profile_url("https://www.tiktok.com/@u?lang=en")

    def test_detail_not_profile(self):
        from jackthesolo.tiktok import is_tiktok_profile_url

        assert not is_tiktok_profile_url("https://www.tiktok.com/@u/video/123")
        assert not is_tiktok_profile_url("https://example.com/@u")
