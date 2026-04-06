"""In-memory circular log — max 500 entries (FIFO)."""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Literal

from reader.models import LogEntry

_MAX_ENTRIES = 500
_lock = threading.Lock()
_entries: deque[LogEntry] = deque(maxlen=_MAX_ENTRIES)


def _log(level: Literal["VERBOSE", "INFO", "WARN", "ERROR"], event: str, detail: str | None = None) -> None:
    entry = LogEntry(
        timestamp=datetime.now(tz=timezone.utc),
        level=level,
        event=event,
        detail=detail,
    )
    with _lock:
        _entries.append(entry)


def verbose(event: str, detail: str | None = None) -> None:
    _log("VERBOSE", event, detail)


def info(event: str, detail: str | None = None) -> None:
    _log("INFO", event, detail)


def warn(event: str, detail: str | None = None) -> None:
    _log("WARN", event, detail)


def error(event: str, detail: str | None = None) -> None:
    _log("ERROR", event, detail)


def get_entries(levels: set[str] | None = None) -> list[LogEntry]:
    with _lock:
        if levels is None:
            return list(_entries)
        return [e for e in _entries if e.level in levels]


def clear() -> None:
    with _lock:
        _entries.clear()
