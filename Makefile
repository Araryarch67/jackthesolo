# jackthesolo — build jadi aplikasi CLI
# Pakai: make install  (butuh: python>=3.9, pipx)

PREFIX   ?= $(HOME)/.local
BINDIR   := $(PREFIX)/bin
MANDIR   := $(PREFIX)/share/man/man1
APP      := jackthesolo

.PHONY: help install dev man browsers check test uninstall clean

help:
	@echo "target:"
	@echo "  install    pasang sebagai aplikasi CLI terisolasi (pipx)"
	@echo "  dev        pasang editable untuk ngoding (pip install -e .)"
	@echo "  man        pasang man page ke $(MANDIR)"
	@echo "  browsers   unduh chromium untuk mode cloud (playwright)"
	@echo "  check      diagnosa: ffmpeg, yt-dlp, Tor, egress IP"
	@echo "  test       smoke test: compile + auto-detect + sanitize"
	@echo "  uninstall  cabut aplikasi CLI"
	@echo "  clean      hapus cache/build lokal"

install:
	pipx install . --force
	@echo "OK: $(BINDIR)/$(APP) — coba: $(APP) --check"

dev:
	pip install -e .
	@echo "OK: mode dev aktif"

man:
	mkdir -p $(MANDIR)
	cp man/jackthesolo.1 $(MANDIR)/jackthesolo.1
	@echo "OK: man $(APP)"

browsers:
	python3 -m playwright install chromium
	@echo "OK: chromium siap untuk mode cloud"

check:
	python3 -m jackthesolo --no-banner --check

test:
	python3 -m compileall -q jackthesolo/
	python3 -m pytest tests/ -q
	python3 -m jackthesolo --no-banner --help > /dev/null
	@echo "test OK"

uninstall:
	pipx uninstall $(APP) || pip uninstall -y $(APP) || true
	@echo "OK: $(APP) dicabut"

clean:
	rm -rf build dist *.egg-info jackthesolo/__pycache__ .ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	@echo "OK: bersih"
