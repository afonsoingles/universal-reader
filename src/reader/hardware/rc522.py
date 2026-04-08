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
        self._last_uid: str | None = None
        self._last_uid_time: float = 0

        _install_stderr_filter()

        try:
            import RPi.GPIO as GPIO  # type: ignore[import]

            GPIO.setwarnings(False)
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
        logger.info("rc522_start", f"Starting RC522 reader daemon (available={self._available})")
        self._thread = threading.Thread(target=self._read_loop, daemon=True, name="rc522-reader")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def reset(self) -> None:
        """Reset the reader state and clear debounce cache."""
        self._last_uid = None
        self._last_uid_time = 0
        logger.info("rc522_reset", "RC522 debounce state cleared")
    
    def restart(self) -> None:
        """Restart the reader by reinitializing the mfrc522 library."""
        logger.info("rc522_restart_start", "Restarting RC522 reader")
        
        # Stop current thread
        self.stop()
        
        # Wait a bit for thread to exit
        import time
        time.sleep(0.2)
        
        # Reinitialize the reader library
        try:
            if self._reader is not None:
                # Try to clean up old reader if possible
                try:
                    if hasattr(self._reader, 'READER'):
                        self._reader.READER = None
                except:
                    pass
                self._reader = None
            
            from mfrc522 import SimpleMFRC522  # type: ignore[import]
            self._reader = SimpleMFRC522()
            self._available = True
            logger.info("rc522_restart_success", "RC522 reader reinitialized")
        except Exception as exc:  # noqa: BLE001
            logger.error("rc522_restart_failed", f"Failed to reinitialize: {exc}")
            self._reader = None
            self._available = False
        
        # Clear debounce state
        self._last_uid = None
        self._last_uid_time = 0
        
        # Restart the read loop
        self.start()
        logger.info("rc522_restart_complete", "RC522 reader restarted successfully")
    
    def is_running(self) -> bool:
        """Check if the read loop is running."""
        return self._running and self._thread is not None and self._thread.is_alive()

    def read_once(self) -> str | None:
        """Read a single tag UID synchronously (for debug mode). Returns UID or None."""
        if not self._available or self._reader is None:
            logger.warn("rc522_read_once_unavailable", "RC522 not available")
            return None
        try:
            logger.verbose("rc522_read_once_attempt", "Attempting to read")
            uid, _ = self._reader.read_no_block()
            if uid is not None:
                uid_str = format(uid, "X")
                logger.info("rc522_read_once_success", uid_str)
                return uid_str
            else:
                logger.verbose("rc522_read_once_no_tag", "No tag detected")
                return None
        except Exception as exc:  # noqa: BLE001
            logger.error("rc522_read_error", f"{type(exc).__name__}: {exc}")
        return None

    def _read_loop(self) -> None:
        import time

        logger.info("rc522_loop_started", f"Read loop running (available={self._available})")
        loop_count = 0
        last_error_logged = None
        while self._running:
            if self._available and self._reader is not None:
                try:
                    uid, _ = self._reader.read_no_block()
                    if uid is not None:
                        uid_str = format(uid, "X")
                        current_time = time.time()
                        
                        # Debounce: ignore same UID within 0.5 seconds
                        if uid_str != self._last_uid or (current_time - self._last_uid_time) > 0.5:
                            logger.info("rc522_tag_detected", uid_str)
                            self._on_scan(uid_str)
                            self._last_uid = uid_str
                            self._last_uid_time = current_time
                    # Log periodically to confirm loop is running
                    loop_count += 1
                    if loop_count % 50 == 0:  # Every 5 seconds (50 * 0.1s)
                        logger.verbose("rc522_loop_alive", f"Read loop running, no tags detected yet (count={loop_count})")
                except Exception as exc:  # noqa: BLE001
                    exc_str = f"{type(exc).__name__}: {exc}"
                    # Only log unique errors to avoid spam
                    if exc_str != last_error_logged:
                        logger.error("rc522_loop_error", exc_str)
                        last_error_logged = exc_str
            else:
                # Log if reader became unavailable
                if loop_count > 0:
                    logger.warn("rc522_loop_unavailable", f"Reader no longer available (available={self._available}, reader={self._reader is not None})")
                    loop_count = 0  # Reset to avoid repeated logging
            time.sleep(0.1)
