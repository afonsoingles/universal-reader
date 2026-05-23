"""REST API response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class LogEntry(BaseModel):
    timestamp: datetime
    level: Literal["VERBOSE", "INFO", "WARN", "ERROR"]
    event: str
    detail: str | None = None


class ReaderStatus(BaseModel):
    state: str
    reader_number: int | None
    ws_connected: bool
    uptime_seconds: float
    last_scan: datetime | None
    locally_disabled: bool
