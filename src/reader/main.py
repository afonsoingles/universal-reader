"""Universal Reader — main entry point.

Starts:
  1. RC522 reader daemon thread
  2. WebSocket client async task (with reconnect)
  3. FastAPI dashboard async task

The WebSocket client and dashboard share a single StateManager and
communicate via async callbacks.
"""

from __future__ import annotations

import asyncio
import sys

import uvicorn

from reader import logger
from reader.config import get_config
from reader.handlers.buzzer_handler import create_buzzer_update_callback
from reader.handlers.lcd_handler import create_lcd_update_callback
from reader.handlers.message_handlers import MessageHandlers
from reader.handlers.tag_scan_handler import TagScanHandler
from reader.startup import cleanup_on_exit, initialize_hardware, transition_to_failure_on_hardware_issues
from reader.state import get_state_manager
from reader.ws_client import WSClient


async def run(config=None) -> None:
    """Main application entry point."""
    if config is None:
        config = get_config()

    sm = get_state_manager()
    loop = asyncio.get_event_loop()

    logger.info("startup", f"Universal Reader starting — dashboard port {config.dashboard_port}")

    # ------------------------------------------------------------------
    # Initialize hardware
    # ------------------------------------------------------------------
    lcd, buzzer, rc522 = await initialize_hardware()
    sys.rc522_reader = None  # type: ignore[attr-defined]

    # Check hardware availability
    await transition_to_failure_on_hardware_issues(sm, lcd, buzzer, rc522)

    # ------------------------------------------------------------------
    # Register state change callbacks
    # ------------------------------------------------------------------
    update_lcd = await create_lcd_update_callback(sm, lcd, loop)
    sm.register_state_change_callback(update_lcd)

    update_buzzer = await create_buzzer_update_callback(sm, buzzer, loop)
    sm.register_state_change_callback(update_buzzer)

    # ------------------------------------------------------------------
    # Initialize message handlers
    # ------------------------------------------------------------------
    message_handlers = MessageHandlers(sm, lcd, buzzer, loop)

    # ------------------------------------------------------------------
    # Initialize tag scan handler
    # ------------------------------------------------------------------
    tag_scan_handler = TagScanHandler(sm, lcd, buzzer, loop)
    rc522_callback = tag_scan_handler.on_uid_scanned_from_thread
    
    # Recreate RC522 with callback
    from reader.hardware.rc522 import RC522Reader
    rc522 = RC522Reader(on_scan=rc522_callback)
    sys.rc522_reader = rc522  # type: ignore[attr-defined]
    rc522.start()

    # ------------------------------------------------------------------
    # WebSocket client
    # ------------------------------------------------------------------
    ws_client = WSClient(
        url=config.inventory_ws_url,
        api_key=config.inventory_api_key,
        state_manager=sm,
        on_activate=message_handlers.on_activate,
        on_deactivate=message_handlers.on_deactivate,
        on_read=message_handlers.on_read,
        on_result=message_handlers.on_result,
    )

    # Update handler references after WS client creation
    await message_handlers.set_ws_client(ws_client)
    tag_scan_handler.set_ws_client(ws_client)

    # ------------------------------------------------------------------
    # FastAPI dashboard
    # ------------------------------------------------------------------
    from reader.dashboard.app import create_app

    dashboard_app = create_app(
        state_manager=sm,
        config=config,
        ws_client=ws_client,
        on_activate=message_handlers.on_activate,
        on_deactivate=message_handlers.on_deactivate,
        on_read=message_handlers.on_read,
        on_result=message_handlers.on_result,
        buzzer=buzzer,
        lcd=lcd,
        rc522=rc522,
    )

    server_config = uvicorn.Config(
        app=dashboard_app,
        host="0.0.0.0",
        port=config.dashboard_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(server_config)

    logger.info("startup_complete", f"Dashboard on :{config.dashboard_port}")

    # Run WS client and dashboard concurrently
    await asyncio.gather(
        ws_client.run(),
        server.serve(),
    )

def main() -> None:
    """Entry point."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        cleanup_on_exit()


if __name__ == "__main__":
    main()

