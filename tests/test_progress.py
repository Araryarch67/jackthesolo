from jackthesolo.progress import FRAMES, Rate, Spinner, bar, fmt_bytes


class TestBar:
    def test_empty(self):
        assert bar(0, 100) == "[" + "░" * 24 + "] 0%"

    def test_half(self):
        assert bar(50, 100) == "[" + "█" * 12 + "░" * 12 + "] 50%"

    def test_full(self):
        assert bar(100, 100) == "[" + "█" * 24 + "] 100%"

    def test_zero_total(self):
        assert bar(0, 0).endswith("0%")

    def test_clamped(self):
        assert bar(200, 100).endswith("100%")


class TestSpinner:
    def test_disabled_noop(self, capsys):
        s = Spinner(enabled=False).start("x")
        s.update("y")
        s.stop()
        assert s.enabled is False
        assert capsys.readouterr().out == ""

    def test_disabled_stop_final(self, capsys):
        Spinner(enabled=False).stop("done")
        assert "done" in capsys.readouterr().out

    def test_enabled_smoke(self):
        s = Spinner(enabled=True).start("tes")
        s.update("tes2")
        s.stop("done")
        assert s.enabled is True

    def test_frames_exist(self):
        assert len(FRAMES) >= 8


class TestFmtBytes:
    def test_units(self):
        assert fmt_bytes(500) == "500.0 B"
        assert fmt_bytes(2048) == "2.0 KB"
        assert fmt_bytes(5 * 1024 * 1024) == "5.0 MB"


class TestRate:
    def test_speed_and_eta(self):
        t = [0.0]

        r = Rate(clock=lambda: t[0])
        r.update(0)
        t[0] = 2.0
        assert r.update(2048) == 1024.0
        assert r.line(2048, 4096).endswith("ETA 00:02")
        assert "1.0 KB/s" in r.line(2048, 4096)

    def test_no_total(self):
        t = [0.0]

        r = Rate(clock=lambda: t[0])
        t[0] = 1.0
        assert r.line(512, 0) == "512.0 B @ 512.0 B/s"

    def test_avg(self):
        t = [0.0]

        r = Rate(clock=lambda: t[0])
        t[0] = 4.0
        assert r.avg(2048) == 512.0


class TestBatchView:
    def test_disabled_prints(self, capsys):
        from jackthesolo.progress import BatchView

        v = BatchView(enabled=False)
        i = v.add("a ... waiting")
        assert i == 0
        v.set(0, "a done")
        v.freeze()
        out = capsys.readouterr().out
        assert "a ... waiting" in out and "a done" in out

    def test_enabled_cursor(self, capsys):
        from jackthesolo.progress import BatchView

        v = BatchView(enabled=True)
        v.add("row1")
        v.set(0, "row1 done")
        out = capsys.readouterr().out
        assert "row1 done" in out and "\x1b[1A" in out

    def test_truncates_wide(self, capsys):
        from jackthesolo.progress import BatchView

        v = BatchView(enabled=False)
        v.width = 20
        v.add("x" * 100)
        assert len(capsys.readouterr().out.strip()) <= 100
