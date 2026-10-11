from jackthesolo.resolvers import (
    extract_youtube_id,
    resolve_any,
    resolve_cobalt,
    resolve_invidious,
)


class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, posts=None, gets=None):
        self._posts = posts or []
        self._gets = gets or []

    def post(self, *a, **k):
        r = self._posts.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def get(self, *a, **k):
        r = self._gets.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class TestExtractYoutubeId:
    def test_watch(self):
        assert (
            extract_youtube_id("https://www.youtube.com/watch?v=AbCdEfGhIjK")
            == "AbCdEfGhIjK"
        )

    def test_short(self):
        assert extract_youtube_id("https://youtu.be/AbCdEfGhIjK") == "AbCdEfGhIjK"

    def test_none(self):
        assert extract_youtube_id("https://example.com/") is None


class TestResolveCobalt:
    def test_tunnel(self):
        s = FakeSession(
            posts=[FakeResp(200, {"status": "tunnel", "url": "https://cdn/x.mp4"})]
        )
        assert (
            resolve_cobalt("https://www.youtube.com/watch?v=x", s)
            == "https://cdn/x.mp4"
        )

    def test_skips_dead_instances(self):
        s = FakeSession(
            posts=[
                FakeResp(500, {}),
                FakeResp(200, {"status": "redirect", "url": "https://cdn/y.mp4"}),
            ]
        )
        assert (
            resolve_cobalt("https://www.youtube.com/watch?v=x", s)
            == "https://cdn/y.mp4"
        )

    def test_all_fail(self):
        s = FakeSession(posts=[OSError("down"), OSError("down")])
        assert resolve_cobalt("https://www.youtube.com/watch?v=x", s) is None


class TestResolveInvidious:
    def test_best_quality(self):
        payload = {
            "formatStreams": [
                {"url": "https://g/360.mp4", "quality": "360p"},
                {"url": "https://g/720.mp4", "quality": "720p"},
            ]
        }
        s = FakeSession(gets=[FakeResp(200, payload)])
        assert resolve_invidious("abc123", s) == "https://g/720.mp4"

    def test_no_streams(self):
        s = FakeSession(gets=[FakeResp(200, {})] * 3)
        assert resolve_invidious("abc123", s) is None


class TestResolveAny:
    def test_cobalt_first(self):
        s = FakeSession(
            posts=[FakeResp(200, {"status": "tunnel", "url": "https://cdn/x.mp4"})]
        )
        url, via = resolve_any("https://www.youtube.com/watch?v=x", s)
        assert (url, via) == ("https://cdn/x.mp4", "cobalt")

    def test_falls_to_invidious(self):
        s = FakeSession(
            posts=[OSError("down"), OSError("down")],
            gets=[
                FakeResp(
                    200,
                    {
                        "formatStreams": [
                            {"url": "https://g/360.mp4", "quality": "360p"}
                        ]
                    },
                )
            ],
        )
        url, via = resolve_any("https://www.youtube.com/watch?v=abcdef", s)
        assert (url, via) == ("https://g/360.mp4", "invidious")
