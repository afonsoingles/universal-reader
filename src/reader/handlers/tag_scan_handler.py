"""RC522 tag scan handler with timeout management."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from reader import logger
from reader.models import ReaderState, UidScannedMessage

if TYPE_CHECKING:
    from reader.hardware.buzzer import Buzzer
    from reader.hardware.lcd import LCD
    from reader.state import StateManager
    from reader.ws_client import WSClient


class TagScanHandler:
    """Handles RC522 tag scans and server response timeouts."""

    def __init__(
        self,
        sm: StateManager,
        lcd: LCD,
        buzzer: Buzzer,
        loop: asyncio.AbstractEventLoop,
    ):
        self._sm = sm
        self._lcd = lcd
        self._buzzer = buzzer
        self._loop = loop
        self._ws_client: WSClient | None = None

    def set_ws_client(self, ws_client: WSClient) -> None:
        """Set the WebSocket client reference."""
        self._ws_client = ws_client

    def on_uid_scanned_from_thread(self, uid: str) -> None:
        """Called from RC522 daemon thread when a tag is scanned."""
        logger.info("on_uid_scanned_callback", f"uid={uid}, state={self._sm.state}")
        if self._sm.state != ReaderState.READING:
            logger.warn(
                "on_uid_scanned_rejected", f"Not in READING state, rejecting scan (state={self._sm.state})"
            )
            return
        
        self._sm.record_scan(uid)
        logger.info("uid_scanned", uid)
        
        # Schedule async work from thread
        asyncio.run_coroutine_threadsafe(self._handle_uid_scanned_async(uid), self._loop)

    async def _handle_uid_scanned_async(self, uid: str) -> None:
        """Async handler for scanned UID."""
        await self._sm.async_transition(ReaderState.AWAITING_RESULT, "tag scanned")
        
        # Play processing beep
        logger.verbose("buzzer_processing", "Playing processing beep before sending to server")
        await self._loop.run_in_executor(None, self._buzzer.result_processing)
        
        # Send UID to server
        if self._ws_client and self._ws_client._ws is not None:
            await self._ws_client.send_model(UidScannedMessage(uid=uid))

        # Set up server response timeout
        remaining = self._sm.remaining_timeout_seconds
        if remaining is not None and remaining > 0:
            asyncio.create_task(self._handle_server_timeout(remaining))

    async def _handle_server_timeout(self, remaining: int) -> None:
        """Handle timeout waiting for server response."""
        logger.verbose("server_timeout_wait_start", f"Waiting {remaining}s for server response in AWAITING_RESULT")
        await asyncio.sleep(remaining)
        logger.verbose("server_timeout_wait_complete", f"Timeout period ({remaining}s) elapsed")
        
        if self._sm.state == ReaderState.AWAITING_RESULT:
            logger.warn("server_timeout", f"No result within {remaining}s, state is still AWAITING_RESULT")
            
            # Show timeout message
            logger.verbose("server_timeout_show_message", "Displaying timeout message on LCD")
            await self._loop.run_in_executor(None, self._lcd.display, "Sorry!", "Timed Out", True)
            logger.verbose("server_timeout_show_message_complete", "Timeout message displayed")
            
            # Play error beep
            logger.verbose("server_timeout_error_beep", "Playing error beep")
            await self._loop.run_in_executor(None, self._buzzer.result_error)
            logger.verbose("server_timeout_error_beep_complete", "Error beep finished")
            
            # Show message for 2 seconds
            logger.verbose("server_timeout_display_sleep", "Showing message for 2s before hibernating")
            await asyncio.sleep(2)
            logger.verbose("server_timeout_display_sleep_complete", "Transitioning to HIBERNATED")
            
            # Transition to hibernated
            logger.info("server_timeout_transitioning", "Transitioning to HIBERNATED...")
            result = await self._sm.async_transition(ReaderState.HIBERNATED, "server timeout")
            logger.verbose("server_timeout_transition_result", f"Transition result: {result}")
            logger.info("server_timeout_hibernated", "Ready for new commands")
        else:
            logger.info("server_timeout_cancelled", f"State changed to {self._sm.state}, not transitioning")
