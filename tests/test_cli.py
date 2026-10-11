import pytest

from jackthesolo.cli import (
    DEFAULT_OUTPUT,
    _enforce_paranoid,
    _read_url,
    build_parser,
    collect_wizard_argv,
    main,
    run_wizard,
)


class TestParser:
    def test_cloud_and_sharepoint_alias(self):
        a = build_parser().parse_args(["http://x", "--sharepoint"])
        assert a.cloud is True

    def test_paranoid_flag(self):
        assert build_parser().parse_args(["http://x", "--paranoid"]).paranoid

    def test_no_banner_flag(self):
        assert build_parser().parse_args(["http://x", "--no-banner"]).no_banner


class TestReadURL:
    def test_url_arg(self):
        a = build_parser().parse_args(["https://x"])
        assert _read_url(a) == "https://x"

    def test_url_file(self, tmp_path):
        f = tmp_path / "u.txt"
        f.write_text("# komentar\n\nhttps://x/f.pdf\n")
        a = build_parser().parse_args(["--url-file", str(f)])
        assert _read_url(a) == "https://x/f.pdf"

    def test_both_url_and_file_conflict(self, tmp_path, capsys):
        f = tmp_path / "u.txt"
        f.write_text("https://x\n")
        a = build_parser().parse_args(["https://y", "--url-file", str(f)])
        assert _read_url(a) is None
        assert "choose one" in capsys.readouterr().err

    def test_missing_file(self):
        a = build_parser().parse_args(["--url-file", "/tmp/nope-xyz"])
        assert _read_url(a) is None


class TestParanoid:
    def _args(self, extra=None, cookies=None):
        argv = ["https://x/f.pdf", "--paranoid"] + (extra or [])
        a = build_parser().parse_args(argv)
        a.cookies = cookies
        return a

    def test_rejects_cookies(self, capsys):
        assert _enforce_paranoid(self._args(cookies="c.txt"), "direct") == 2
        assert "refuses --cookies" in capsys.readouterr().err

    def test_rejects_cloud_mode(self, capsys):
        assert _enforce_paranoid(self._args(), "cloud") == 2
        assert "refuses cloud mode" in capsys.readouterr().err

    def test_rejects_no_anon_route(self, capsys):
        a = self._args(extra=["--no-proxy"])
        assert _enforce_paranoid(a, "direct") == 2
        assert "no anonymous route" in capsys.readouterr().err

    def test_fails_closed_when_egress_down(self, monkeypatch, capsys):
        a = self._args(extra=["--proxy", "socks5h://127.0.0.1:9050"])
        monkeypatch.setattr("jackthesolo.privacy.egress_ip", lambda proxy=None: None)
        assert _enforce_paranoid(a, "direct") == 2
        assert "failed" in capsys.readouterr().err

    def test_leak_when_same_ip(self, monkeypatch, capsys):
        a = self._args(extra=["--proxy", "socks5h://127.0.0.1:9050"])
        monkeypatch.setattr(
            "jackthesolo.privacy.egress_ip", lambda proxy=None: "1.2.3.4"
        )
        assert _enforce_paranoid(a, "direct") == 2
        assert "Leaking" in capsys.readouterr().err

    def test_passes_when_hidden(self, monkeypatch, capsys):
        a = self._args(extra=["--proxy", "socks5h://127.0.0.1:9050"])

        def fake_egress(proxy=None):
            return "5.6.7.8" if proxy else "1.2.3.4"

        monkeypatch.setattr("jackthesolo.privacy.egress_ip", fake_egress)
        assert _enforce_paranoid(a, "direct") == 0
        assert "[pass]" in capsys.readouterr().out


class TestMainGuards:
    def test_cloud_without_cookies_rejects(self, capsys):
        rc = main(["https://x.sharepoint.com/shared?x=1", "--no-banner"])
        assert rc == 2
        assert "needs login" in capsys.readouterr().err

    def test_no_url_prints_help(self, capsys):
        rc = main(["--no-banner"])
        assert rc == 2
        assert "usage:" in capsys.readouterr().out


class TestWizard:
    def _ask(self, answers):
        it = iter(answers)
        return lambda *a, **k: next(it)

    def test_direct_defaults(self):
        argv = collect_wizard_argv(
            self._ask(["https://e.com/f.pdf", "", "", "", "", ""]), "x"
        )
        assert argv is not None
        assert argv[0] == "https://e.com/f.pdf"
        assert "--no-banner" in argv
        assert argv[argv.index("-o") + 1] == DEFAULT_OUTPUT
        assert "--output-file" not in argv and "--paranoid" not in argv

    def test_media_audio(self):
        argv = collect_wizard_argv(
            self._ask(["https://www.tiktok.com/@u/video/1", "", "", "y", "", "", ""]),
            "x",
        )
        assert "-a" in argv and "-q" not in argv

    def test_media_quality_and_name(self):
        argv = collect_wizard_argv(
            self._ask(
                [
                    "https://www.tiktok.com/@u/video/1",
                    "",
                    "",
                    "n",
                    "720",
                    "v.mp4",
                    "",
                    "",
                ]
            ),
            "x",
        )
        assert argv[argv.index("-q") + 1] == "720"
        assert argv[argv.index("--output-file") + 1] == "v.mp4"

    def test_cloud_cookies_no_paranoid_step(self):
        argv = collect_wizard_argv(
            self._ask(
                ["https://x.sharepoint.com/shared?x=1", "c.txt", "", "f.pdf", ""]
            ),
            "x",
        )
        assert argv is not None and argv[argv.index("--cookies") + 1] == "c.txt"

    def test_cancel_at_confirm(self):
        assert (
            collect_wizard_argv(
                self._ask(["https://e.com/f.pdf", "", "", "", "", "n"]), "x"
            )
            is None
        )

    def test_empty_url_aborts(self):
        assert collect_wizard_argv(self._ask(["", ""]), None) is None

    def test_run_wizard_eof(self):
        def boom(*a, **k):
            raise EOFError

        import jackthesolo.cli as cli_mod

        orig = cli_mod.collect_wizard_argv
        cli_mod.collect_wizard_argv = boom
        try:
            assert run_wizard() == 2
        finally:
            cli_mod.collect_wizard_argv = orig
