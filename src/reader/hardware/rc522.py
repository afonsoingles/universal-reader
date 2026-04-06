"""RC522 RFID reader abstraction.

On a real Pi this uses the mfrc522 library.
On other platforms a mock stub is used so the rest of the application can
run for development / testing.
"""

from __future__ import annotations

import io
import sys
import threading
from typing import Callable

from reader import logger


class _StderrFilter(io.TextIOWrapper):
    """Filter that suppresses RC522 AUTH ERROR lines on stderr."""

    def __init__(self, wrapped: io.TextIOBase) -> None:
        # Don't call super().__init__() — we delegate everything manually
        self._wrapped = wrapped

    def write(self, s: str) -> int:
        if "AUTH ERROR" in s or "No tag" in s:
            return len(s)
        return self._wrapped.write(s)

    def flush(self) -> None:
        self._wrapped.flush()

    # Forward everything else so normal error output isn't lost
    def __getattr__(self, item):
        return getattr(self._wrapped, item)


def _install_stderr_filter() -> None:
    if not isinstance(sys.stderr, _StderrFilter):
        sys.stderr = _StderrFilter(sys.stderr)  # type: ignore[assignment]


class RC522Reader:
    """Wraps SimpleMFRC522 for non-blocking RFID reads in a daemon thread."""

    def __init__(self, on_scan: Callable[[str], None]) -> None:
        self._on_scan = on_scan
        self._running = False
        self._thread: threading.Thread | None = None
        self._reader = None
        self._available = False

        _install_stderr_filter()

        try:
            from mfrc522 import SimpleMFRC522  # type: ignore[import]

            self._reader = SimpleMFRC522()
            self._available = True
            logger.info("rc522_init", "RC522 reader initialised")
        except Exception as exc:  # noqa: BLE001
            logger.warn("rc522_init_mock", f"RC522 not available, using mock: {exc}")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True, name="rc522-reader")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def read_once(self) -> str | None:
        """Read a single tag UID synchronously (for debug mode). Returns UID or None."""
        if not self._available or self._reader is None:
            return None
        try:
            uid, _ = self._reader.read_no_block()
            if uid is not None:
                return format(uid, "X")
        except Exception as exc:  # noqa: BLE001
            logger.error("rc522_read_error", str(exc))
        return None

    def _read_loop(self) -> None:
        import time

        while self._running:
            if self._available and self._reader is not None:
                try:
                    uid, _ = self._reader.read_no_block()
                    if uid is not None:
                        uid_str = format(uid, "X")
                        self._on_scan(uid_str)
                except Exception as exc:  # noqa: BLE001
                    logger.error("rc522_loop_error", str(exc))
            time.sleep(0.1)
