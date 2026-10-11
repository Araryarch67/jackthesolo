from jackthesolo.scribd import (
    convert_scribd_link,
    get_filename_from_url,
    is_scribd_url,
    scribd_doc_id,
)


class TestIsScribdURL:
    def test_document(self):
        assert is_scribd_url("https://www.scribd.com/document/123/Judul")

    def test_doc_legacy(self):
        assert is_scribd_url("https://www.scribd.com/doc/123/Judul")

    def test_other(self):
        assert not is_scribd_url("https://example.com/document/123/x")


class TestDocId:
    def test_document(self):
        assert (
            scribd_doc_id("https://www.scribd.com/document/903361807/X") == "903361807"
        )

    def test_embeds(self):
        assert (
            scribd_doc_id("https://www.scribd.com/embeds/903361807/content")
            == "903361807"
        )

    def test_invalid(self):
        import pytest

        with pytest.raises(ValueError):
            scribd_doc_id("https://example.com/f.pdf")


class TestConvert:
    def test_embed(self):
        assert convert_scribd_link("https://www.scribd.com/doc/123/X") == (
            "https://www.scribd.com/embeds/123/content"
        )


class TestFilename:
    def test_from_slug(self):
        assert (
            get_filename_from_url("https://www.scribd.com/document/123/Judul-Keren")
            == "Judul-Keren.pdf"
        )

    def test_fallback(self):
        assert get_filename_from_url("https://www.scribd.com/") == "scribd_document.pdf"


class TestDetect:
    def test_sources(self):
        from jackthesolo.sources import detect_source

        assert detect_source("https://www.scribd.com/document/123/X") == "scribd"
