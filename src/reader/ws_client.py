"""WebSocket client — manages the connection to the Inventory server."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import websockets
from pydantic import TypeAdapter, ValidationError

from reader import logger
from reader.models import (
    ActivateMessage,
    DeactivateMessage,
    ErrorMessage,
    InboundMessage,
    PingMessage,
    PongMessage,
    ReadMessage,
    RegisterMessage,
    RegisteredMessage,
    ReaderState,
    ResultMessage,
    StatusMessage,
    UidScannedMessage,
)
from reader.state import StateManager

if TYPE_CHECKING:
    pass

_inbound_adapter: TypeAdapter = TypeAdapter(InboundMessage)  # type: ignore[type-arg]

# Reconnection delays
_FAST_RETRIES = 3
_FAST_DELAY = 10
_SLOW_DELAY = 60


class WSClient:
    """Manages the WebSocket connection to the Inventory server."""

    def __init__(
        self,
        url: str,
        api_key: str,
        state_manager: StateManager,
        on_activate,
        on_deactivate,
        on_read,
        on_result,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._sm = state_manager
        self._on_activate = on_activate
        self._on_deactivate = on_deactivate
        self._on_read = on_read
        self._on_result = on_result
        self._ws = None
        self._running = False

    async def send(self, msg: dict) -> None:
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps(msg))
            except Exception as exc:  # noqa: BLE001
                logger.error("ws_send_error", str(exc))

    async def send_model(self, model) -> None:
        await self.send(model.model_dump())

    async def run(self) -> None:
        """Main loop — connect, handle messages, reconnect on failure."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_handle()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("ws_unexpected_error", str(exc))

            if not self._running:
                break

            # Reconnection delay
            attempts = self._sm.reconnect_attempts
            delay = _FAST_DELAY if attempts < _FAST_RETRIES else _SLOW_DELAY
            self._sm.reconnect_attempts = attempts + 1
            logger.info(
                "ws_reconnect_wait",
                f"attempt {self._sm.reconnect_attempts}, waiting {delay}s",
            )
            await asyncio.sleep(delay)

    async def _connect_and_handle(self) -> None:
        logger.info("ws_connecting", self._url)
        try:
            async with websockets.connect(self._url) as ws:  # type: ignore[attr-defined]
                self._ws = ws
                self._sm.ws_connected = True
                self._sm.reconnect_attempts = 0
                logger.info("ws_connected", self._url)

                # Register with Inventory
                await self.send_model(RegisterMessage(api_key=self._api_key))
                logger.info("ws_registered_sent")

                async for raw in ws:
                    await self._handle_raw(raw)

        except (websockets.ConnectionClosed, OSError) as exc:
            logger.warn("ws_disconnected", str(exc))
        finally:
            self._ws = None
            self._sm.ws_connected = False
            logger.info("ws_connection_lost", f"Current state before failure transition: {self._sm.state}")
            # Only transition to SYSTEM_FAILURE if not locally disabled and not already in failure
            if self._sm.state not in (ReaderState.LOCALLY_DISABLED, ReaderState.SYSTEM_FAILURE):
                logger.info("ws_entering_failure", "Transitioning to SYSTEM_FAILURE due to WS disconnect")
                await self._sm.async_transition(
                    ReaderState.SYSTEM_FAILURE, "websocket disconnected"
                )

    async def _handle_raw(self, raw: str) -> None:
        # While LOCALLY_DISABLED, ignore all Inventory messages
        if self._sm.state == ReaderState.LOCALLY_DISABLED:
            logger.info("ws_msg_ignored_disabled", raw[:120])
            return

        try:
            data = json.loads(raw)
            msg = _inbound_adapter.validate_python(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warn("ws_parse_error", f"{exc} — raw: {raw[:120]}")
            return

        if isinstance(msg, RegisteredMessage):
            self._sm.reader_number = msg.reader_number
            logger.info("ws_registered", f"reader_number={msg.reader_number}")
            # Restore pre-failure state on successful re-registration
            if self._sm.state == ReaderState.SYSTEM_FAILURE:
                target = self._sm.pre_failure_state
                logger.info("ws_restoring_state", f"Restoring from SYSTEM_FAILURE to {target}")
                await self._sm.async_transition(target, "ws reconnected")
            else:
                # Even if not in SYSTEM_FAILURE, mark that we're connected
                logger.info("ws_connection_alive", f"Current state: {self._sm.state}")

        elif isinstance(msg, PingMessage):
            # Respond immediately to keep-alive pings from the Inventory server.
            # The Inventory uses ping/pong to detect stale connections and may
            # disconnect readers that do not respond.
            await self.send_model(PongMessage())

        elif isinstance(msg, ActivateMessage):
            if self._sm.state in (ReaderState.HIBERNATED, ReaderState.ACTIVE):
                await self._on_activate(msg)
            else:
                logger.info("ws_activate_ignored", f"state={self._sm.state}")

        elif isinstance(msg, DeactivateMessage):
            await self._on_deactivate(msg)

        elif isinstance(msg, ReadMessage):
            if self._sm.state in (ReaderState.READING, ReaderState.AWAITING_RESULT):
                await self.send_model(ErrorMessage(reason="scan_in_progress"))
                logger.warn("ws_read_refused", "scan already in progress")
            elif self._sm.state == ReaderState.ACTIVE:
                await self._on_read(msg)
            else:
                logger.info("ws_read_ignored", f"state={self._sm.state}")

        elif isinstance(msg, ResultMessage):
            await self._on_result(msg)

        else:
            logger.warn("ws_unknown_msg", str(msg))

    def stop(self) -> None:
        self._running = False
