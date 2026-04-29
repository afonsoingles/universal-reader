"""Reader state machine enum."""

from __future__ import annotations

from enum import Enum


class ReaderState(str, Enum):
    HIBERNATED = "HIBERNATED"
    ACTIVE = "ACTIVE"
    READING = "READING"
    AWAITING_RESULT = "AWAITING_RESULT"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"
    LOCALLY_DISABLED = "LOCALLY_DISABLED"
