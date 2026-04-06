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


def _log(level: Literal["INFO", "WARN", "ERROR"], event: str, detail: str | None = None) -> None:
    entry = LogEntry(
        timestamp=datetime.now(tz=timezone.utc),
        level=level,
        event=event,
        detail=detail,
    )
    with _lock:
        _entries.append(entry)


def info(event: str, detail: str | None = None) -> None:
    _log("INFO", event, detail)


def warn(event: str, detail: str | None = None) -> None:
    _log("WARN", event, detail)


def error(event: str, detail: str | None = None) -> None:
    _log("ERROR", event, detail)


def get_entries() -> list[LogEntry]:
    with _lock:
        return list(_entries)


def clear() -> None:
    with _lock:
        _entries.clear()
