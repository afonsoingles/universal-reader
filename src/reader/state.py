"""State machine and thread-safe StateManager."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from reader import logger
from reader.models import ReaderState

if TYPE_CHECKING:
    pass

# Valid state transitions
VALID_TRANSITIONS: dict[ReaderState | None, set[ReaderState]] = {
    ReaderState.HIBERNATED: {
        ReaderState.ACTIVE,
        ReaderState.SYSTEM_FAILURE,
        ReaderState.LOCALLY_DISABLED,
    },
    ReaderState.ACTIVE: {
        ReaderState.HIBERNATED,
        ReaderState.READING,
        ReaderState.SYSTEM_FAILURE,
        ReaderState.LOCALLY_DISABLED,
    },
    ReaderState.READING: {
        ReaderState.AWAITING_RESULT,
        ReaderState.SYSTEM_FAILURE,
        ReaderState.LOCALLY_DISABLED,
    },
    ReaderState.AWAITING_RESULT: {
        ReaderState.ACTIVE,
        ReaderState.HIBERNATED,
        ReaderState.SYSTEM_FAILURE,
        ReaderState.LOCALLY_DISABLED,
    },
    ReaderState.SYSTEM_FAILURE: {
        ReaderState.ACTIVE,
        ReaderState.LOCALLY_DISABLED,
    },
    ReaderState.LOCALLY_DISABLED: {
        ReaderState.ACTIVE,
        ReaderState.SYSTEM_FAILURE,
    },
    None: {ReaderState.HIBERNATED},
}


class StateManager:
    """Thread-safe state manager for the reader state machine."""

    def __init__(self) -> None:
        self._state: ReaderState = ReaderState.HIBERNATED
        self._reader_number: int | None = None
        self._ws_connected: bool = False
        self._start_time: float = time.monotonic()
        self._last_scan: datetime | None = None
        self._last_uid: str | None = None
        self._reconnect_attempts: int = 0
        self._pre_failure_state: ReaderState = ReaderState.HIBERNATED

        # Thread lock for sync contexts (hardware threads)
        self._thread_lock = threading.Lock()
        # Asyncio lock for async contexts (WS client, dashboard)
        self._async_lock: asyncio.Lock | None = None

        # Observers notified on state change (async callables)
        self._on_state_change_callbacks: list = []

    def _get_async_lock(self) -> asyncio.Lock:
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> ReaderState:
        return self._state

    @property
    def reader_number(self) -> int | None:
        return self._reader_number

    @reader_number.setter
    def reader_number(self, value: int | None) -> None:
        self._reader_number = value

    @property
    def ws_connected(self) -> bool:
        return self._ws_connected

    @ws_connected.setter
    def ws_connected(self, value: bool) -> None:
        self._ws_connected = value

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

    @property
    def last_scan(self) -> datetime | None:
        return self._last_scan

    @property
    def last_uid(self) -> str | None:
        return self._last_uid

    @property
    def reconnect_attempts(self) -> int:
        return self._reconnect_attempts

    @reconnect_attempts.setter
    def reconnect_attempts(self, value: int) -> None:
        self._reconnect_attempts = value

    @property
    def locally_disabled(self) -> bool:
        return self._state == ReaderState.LOCALLY_DISABLED

    @property
    def pre_failure_state(self) -> ReaderState:
        return self._pre_failure_state

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def can_transition(self, new_state: ReaderState) -> bool:
        allowed = VALID_TRANSITIONS.get(self._state, set())
        return new_state in allowed

    def transition(self, new_state: ReaderState, reason: str | None = None) -> bool:
        """Attempt a sync state transition. Returns True on success."""
        with self._thread_lock:
            if not self.can_transition(new_state):
                logger.warn(
                    "invalid_transition",
                    f"{self._state} → {new_state}" + (f" ({reason})" if reason else ""),
                )
                return False

            old_state = self._state

            # Remember the last known operational state so we can restore it
            # after a successful reconnect. We skip SYSTEM_FAILURE and
            # LOCALLY_DISABLED because neither represents a stable working state
            # to return to.
            if new_state == ReaderState.SYSTEM_FAILURE:
                if old_state not in (ReaderState.SYSTEM_FAILURE, ReaderState.LOCALLY_DISABLED):
                    self._pre_failure_state = old_state

            self._state = new_state
            logger.info(
                "state_transition",
                f"{old_state} → {new_state}" + (f" ({reason})" if reason else ""),
            )
            return True

    async def async_transition(self, new_state: ReaderState, reason: str | None = None) -> bool:
        """Attempt an async state transition. Returns True on success."""
        async with self._get_async_lock():
            if not self.can_transition(new_state):
                logger.warn(
                    "invalid_transition",
                    f"{self._state} → {new_state}" + (f" ({reason})" if reason else ""),
                )
                return False

            old_state = self._state

            # Remember the last known operational state so we can restore it
            # after a successful reconnect. We skip SYSTEM_FAILURE and
            # LOCALLY_DISABLED because neither represents a stable working state
            # to return to.
            if new_state == ReaderState.SYSTEM_FAILURE:
                if old_state not in (ReaderState.SYSTEM_FAILURE, ReaderState.LOCALLY_DISABLED):
                    self._pre_failure_state = old_state

            self._state = new_state
            logger.info(
                "state_transition",
                f"{old_state} → {new_state}" + (f" ({reason})" if reason else ""),
            )
            # Notify observers
            for cb in self._on_state_change_callbacks:
                if asyncio.iscoroutinefunction(cb):
                    await cb(old_state, new_state)
                else:
                    cb(old_state, new_state)

            return True

    def register_state_change_callback(self, cb) -> None:
        self._on_state_change_callbacks.append(cb)

    def record_scan(self, uid: str) -> None:
        self._last_scan = datetime.now(tz=timezone.utc)
        self._last_uid = uid


_manager: StateManager | None = None


def get_state_manager() -> StateManager:
    global _manager
    if _manager is None:
        _manager = StateManager()
    return _manager
