"""Dependency-free terminal loading animation.

Spinning indicator for indeterminate phases (connecting, rendering), bars for
measurable ones. Silent when output is not a tty (logs/pipes stay clean).
"""

from __future__ import annotations

import os
import sys
import threading

FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def ansi_ok() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.name == "nt" and not os.getenv("WT_SESSION") and not os.getenv("TERM"):
        return False  # legacy Windows console cannot render ANSI escapes
    return True


def bar(done: int, total: int, width: int = 24) -> str:
    pct = 0 if total <= 0 else min(100, done * 100 // total)
    filled = 0 if total <= 0 else min(width, done * width // total)
    return f"[{'█' * filled}{'░' * (width - filled)}] {pct}%"


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class Rate:
    """Download speed (EMA) + ETA. Clock is injectable for tests."""

    def __init__(self, clock=None) -> None:
        import time as _time

        self._clock = clock or _time.monotonic
        self._t0 = self._clock()
        self._last_t = self._t0
        self._last_done = 0
        self.speed = 0.0

    def update(self, done: int) -> float:
        now = self._clock()
        dt = now - self._last_t
        if dt > 0:
            inst = (done - self._last_done) / dt
            self.speed = inst if self.speed == 0 else 0.3 * inst + 0.7 * self.speed
            self._last_t, self._last_done = now, done
        return self.speed

    def eta(self, done: int, total: int) -> str:
        if self.speed <= 0 or total <= 0 or done >= total:
            return "--:--"
        s = int((total - done) / self.speed)
        return f"{s // 60:02d}:{s % 60:02d}"

    def avg(self, done: int) -> float:
        dt = self._clock() - self._t0
        return done / dt if dt > 0 else 0.0

    def line(self, done: int, total: int) -> str:
        self.update(done)
        speed = f"{fmt_bytes(self.speed)}/s"
        if total:
            return (
                f"{bar(done, total)} {fmt_bytes(done)}/{fmt_bytes(total)} "
                f"@ {speed} ETA {self.eta(done, total)}"
            )
        return f"{fmt_bytes(done)} @ {speed}"


class Spinner:
    def __init__(self, enabled: bool | None = None) -> None:
        self.enabled = ansi_ok() if enabled is None else enabled
        self._msg = ""
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self, msg: str = "") -> "Spinner":
        self._msg = msg
        if not self.enabled:
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def update(self, msg: str) -> None:
        with self._lock:
            self._msg = msg

    def _spin(self) -> None:
        i = 0
        while not self._stop.wait(0.08):
            with self._lock:
                msg = self._msg
            sys.stdout.write(f"\r{FRAMES[i % len(FRAMES)]} {msg}")
            sys.stdout.flush()
            i += 1

    def stop(self, final: str = "") -> None:
        if not self.enabled:
            if final:
                print(final)
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        sys.stdout.write("\r" + " " * 79 + "\r")
        if final:
            print(final)
        sys.stdout.flush()


class BatchView:
    """Pacman-style batch list: one live row per item.

    On a tty, rows redraw in place with cursor control. Any outside print
    (engine logs, errors) breaks cursor math, so call freeze() before such
    output; the next set() redraws the block fresh below. Non-tty prints
    plain status lines instead.
    """

    def __init__(self, enabled: bool | None = None) -> None:
        import shutil

        self.enabled = ansi_ok() if enabled is None else enabled
        self.rows: list[str] = []
        self._drawn = 0
        try:
            self.width = shutil.get_terminal_width((80, 20)).columns
        except Exception:  # noqa: BLE001
            self.width = 80

    def _render(self) -> None:
        if self._drawn:
            sys.stdout.write(f"\033[{self._drawn}A")
        for row in self.rows:
            sys.stdout.write("\r\033[K" + row[: max(10, self.width - 1)] + "\n")
        self._drawn = len(self.rows)
        sys.stdout.flush()

    def add(self, text: str) -> int:
        self.rows.append(text)
        if self.enabled:
            self._render()
        else:
            print(text)
        return len(self.rows) - 1

    def set(self, idx: int, text: str) -> None:
        self.rows[idx] = text
        if self.enabled:
            self._render()
        else:
            print(text)

    def freeze(self) -> None:
        """Forget cursor position; next set() redraws the block fresh."""
        self._drawn = 0


def is_transient_http(status: int | None) -> bool:
    return (
        status is None
        or status == 408
        or status == 429
        or (status is not None and 500 <= status <= 599)
    )


def backoff_delay(attempt: int, base: float = 2.0, cap: float = 30.0) -> float:
    """Exponential backoff with jitter. Attempt counts from 1."""
    import random

    delay = min(cap, base * (2.0 ** (attempt - 1)))
    return delay / 2.0 + random.uniform(0, delay / 2.0)
