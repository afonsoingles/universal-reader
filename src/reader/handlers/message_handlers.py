"""WebSocket message handlers (activate, deactivate, read, result)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from reader import logger
from reader.models import ActivateMessage, DeactivateMessage, ReadMessage, ReaderState, ResultMessage

if TYPE_CHECKING:
    from reader.hardware.buzzer import Buzzer
    from reader.hardware.lcd import LCD
    from reader.state import StateManager
    from reader.ws_client import WSClient


class MessageHandlers:
    """Handles incoming WebSocket messages."""

    def __init__(
        self,
        sm: StateManager,
        lcd: LCD,
        buzzer: Buzzer,
        loop: asyncio.AbstractEventLoop,
        ws_client: WSClient | None = None,
    ):
        self._sm = sm
        self._lcd = lcd
        self._buzzer = buzzer
        self._loop = loop
        self._ws_client = ws_client
        self._activate_timeout_task: asyncio.Task | None = None

    async def set_ws_client(self, ws_client: WSClient) -> None:
        """Set the WebSocket client reference (called after initialization)."""
        self._ws_client = ws_client

    async def on_activate(self, msg: ActivateMessage) -> None:
        """Handle activate message from server."""
        if self._activate_timeout_task and not self._activate_timeout_task.done():
            self._activate_timeout_task.cancel()
        
        await self._sm.async_transition(ReaderState.ACTIVE, "activate")
        logger.info("ws_activate", f"timeout={msg.timeout_seconds}s")
        
        # Track the global activation timeout
        self._sm.set_activation_timeout(msg.timeout_seconds)
        
        # Only create a timeout task if timeout > 0
        if msg.timeout_seconds > 0:
            self._activate_timeout_task = asyncio.create_task(
                self._activate_timeout_cb(msg.timeout_seconds)
            )

    async def on_deactivate(self, msg: DeactivateMessage) -> None:
        """Handle deactivate message from server."""
        if self._activate_timeout_task and not self._activate_timeout_task.done():
            self._activate_timeout_task.cancel()
        
        self._sm.clear_activation_timeout()
        current = self._sm.state
        if current in (ReaderState.ACTIVE, ReaderState.READING, ReaderState.AWAITING_RESULT):
            await self._sm.async_transition(ReaderState.HIBERNATED, "deactivate")
        logger.info("ws_deactivate")

    async def on_read(self, msg: ReadMessage) -> None:
        """Handle read message from server."""
        await self._sm.async_transition(ReaderState.READING, "read command")
        logger.info("ws_read", "entering READING state")

        # Start timeout for READING state
        remaining = self._sm.remaining_timeout_seconds
        if remaining is not None and remaining > 0:
            asyncio.create_task(self._handle_reading_timeout(remaining))

    async def on_result(self, msg: ResultMessage) -> None:
        """Handle result message from server."""
        await self._sm.async_transition(ReaderState.ACTIVE, "result received")
        logger.info("ws_result", f"status={msg.status} item_id={msg.item_id}")

        # Buzzer feedback
        if msg.status == "success":
            await self._loop.run_in_executor(None, self._buzzer.result_success)
        else:
            await self._loop.run_in_executor(None, self._buzzer.result_error)

        # LCD result display
        rn = self._sm.reader_number or "?"
        if msg.status == "success":
            await self._loop.run_in_executor(None, self._lcd.display, "Item Found", msg.item_id or "", True)
        elif msg.status == "not_found":
            await self._loop.run_in_executor(None, self._lcd.display, "\u26a0\ufe0f", "Item Not Found", True)
        elif msg.status == "network_error":
            await self._loop.run_in_executor(None, self._lcd.display, "\u26a0\ufe0f", "Network Error", True)
        elif msg.status == "retry":
            await self._loop.run_in_executor(None, self._lcd.display, "\u26a0\ufe0f", "Read Error", True)

        # Schedule restore after 5s
        asyncio.create_task(self._restore_lcd_after_result(rn))

    # ------------------------------------------------------------------
    # Private timeout and helper methods
    # ------------------------------------------------------------------

    async def _activate_timeout_cb(self, timeout: int) -> None:
        """Handle global activation timeout."""
        await asyncio.sleep(timeout)
        if self._sm.state == ReaderState.ACTIVE:
            await self._sm.async_transition(ReaderState.HIBERNATED, "activate timeout")
            logger.info("activate_timeout_expired")

    async def _handle_reading_timeout(self, remaining: int) -> None:
        """Handle timeout while waiting for scan in READING state."""
        await asyncio.sleep(remaining)
        if self._sm.state == ReaderState.READING:
            logger.warn("reading_timeout", f"No scan within {remaining}s")
            await self._loop.run_in_executor(None, self._lcd.display, "", "Timed Out", True)
            await self._loop.run_in_executor(None, self._buzzer.result_error)
            await asyncio.sleep(2)
            # Must transition through AWAITING_RESULT before going to HIBERNATED
            success = await self._sm.async_transition(ReaderState.AWAITING_RESULT, "reading timeout")
            if success:
                await self._sm.async_transition(ReaderState.HIBERNATED, "reading timeout")
            else:
                logger.warn("reading_timeout_transition_failed", f"Could not transition from READING")

    async def _restore_lcd_after_result(self, reader_number: str) -> None:
        """Restore LCD to ACTIVE display after result is shown."""
        await asyncio.sleep(5)
        if self._sm.state == ReaderState.ACTIVE:
            await self._loop.run_in_executor(
                None, self._lcd.display, "Universal Reader", f"Reader {reader_number}", True
            )
            # Schedule hibernation if idle
            asyncio.create_task(self._hibernate_if_idle())

    async def _hibernate_if_idle(self) -> None:
        """Hibernate if still in ACTIVE state and no timeout task is running."""
        await asyncio.sleep(5)
        if self._sm.state == ReaderState.ACTIVE and (
            self._activate_timeout_task is None or self._activate_timeout_task.done()
        ):
            await self._sm.async_transition(ReaderState.HIBERNATED, "idle timeout")
