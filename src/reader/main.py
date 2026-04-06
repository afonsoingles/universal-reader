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
import time

import uvicorn

from reader import logger
from reader.config import get_config
from reader.hardware.buzzer import Buzzer
from reader.hardware.lcd import LCD
from reader.hardware.rc522 import RC522Reader
from reader.models import (
    ActivateMessage,
    DeactivateMessage,
    ReadMessage,
    ReaderState,
    ResultMessage,
)
from reader.state import get_state_manager
from reader.ws_client import WSClient


async def run(config=None) -> None:
    if config is None:
        config = get_config()

    sm = get_state_manager()
    lcd = LCD(config)
    buzzer = Buzzer(config)
    loop = asyncio.get_event_loop()

    logger.info("startup", f"Universal Reader starting — dashboard port {config.dashboard_port}")

    # Store hardware refs globally for cleanup on exit
    import sys
    sys.lcd = lcd  # type: ignore[attr-defined]
    sys.buzzer = buzzer  # type: ignore[attr-defined]
    sys.rc522_reader = None  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # LCD update on state change
    # ------------------------------------------------------------------

    async def update_lcd(old_state: ReaderState, new_state: ReaderState) -> None:
        logger.verbose("update_lcd_callback", f"Callback invoked: {old_state} → {new_state}")
        rn = sm.reader_number or "?"
        if new_state == ReaderState.HIBERNATED:
            logger.verbose("update_lcd_hibernated", "Turning off LCD (HIBERNATED state)")
            await loop.run_in_executor(None, lcd.off)
            logger.verbose("update_lcd_hibernated_complete", "LCD off completed")
        elif new_state == ReaderState.ACTIVE:
            # Start with backlight ON
            logger.verbose("update_lcd_active", "Displaying ACTIVE screen")
            await loop.run_in_executor(None, lcd.display, "Universal Reader", f"Reader {rn}", True)
        elif new_state == ReaderState.READING:
            logger.verbose("update_lcd_reading", "Displaying READING screen")
            await loop.run_in_executor(None, lcd.display, "Universal Reader", "Scan item...", True)
        elif new_state == ReaderState.AWAITING_RESULT:
            logger.verbose("update_lcd_awaiting", "Displaying AWAITING_RESULT screen")
            await loop.run_in_executor(
                None, lcd.display, "Universal Reader", "Processing...", True
            )
        elif new_state == ReaderState.SYSTEM_FAILURE:
            logger.verbose("update_lcd_failure", "Displaying SYSTEM_FAILURE screen")
            await loop.run_in_executor(None, lcd.display, "\u26a0\ufe0f", "System Failure", True)
        elif new_state == ReaderState.LOCALLY_DISABLED:
            # Quietly disable: turn off backlight and clear display
            logger.verbose("update_lcd_disabled", "Turning off LCD (LOCALLY_DISABLED state)")
            await loop.run_in_executor(None, lcd.off)

    sm.register_state_change_callback(update_lcd)

    # ------------------------------------------------------------------
    # Buzzer update on state change
    # ------------------------------------------------------------------

    async def update_buzzer(old_state: ReaderState, new_state: ReaderState) -> None:
        if new_state == ReaderState.READING:
            await loop.run_in_executor(None, buzzer.reading_start)
        # Play a success beep when recovering from SYSTEM_FAILURE back to ACTIVE
        elif old_state == ReaderState.SYSTEM_FAILURE and new_state == ReaderState.ACTIVE:
            logger.info("system_recovered", "Transitioned from SYSTEM_FAILURE to ACTIVE")
            await loop.run_in_executor(None, buzzer.result_success)

    sm.register_state_change_callback(update_buzzer)

    # ------------------------------------------------------------------
    # Activate timeout handle
    # ------------------------------------------------------------------

    _activate_timeout_task: asyncio.Task | None = None

    async def _activate_timeout_cb(timeout: int) -> None:
        await asyncio.sleep(timeout)
        if sm.state == ReaderState.ACTIVE:
            await sm.async_transition(ReaderState.HIBERNATED, "activate timeout")
            logger.info("activate_timeout_expired")

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def on_activate(msg: ActivateMessage) -> None:
        nonlocal _activate_timeout_task
        if _activate_timeout_task and not _activate_timeout_task.done():
            _activate_timeout_task.cancel()
        await sm.async_transition(ReaderState.ACTIVE, "activate")
        logger.info("ws_activate", f"timeout={msg.timeout_seconds}s")
        # Track the global activation timeout
        sm.set_activation_timeout(msg.timeout_seconds)
        # Only create a timeout task if timeout > 0
        if msg.timeout_seconds > 0:
            _activate_timeout_task = asyncio.create_task(_activate_timeout_cb(msg.timeout_seconds))

    async def on_deactivate(msg: DeactivateMessage) -> None:
        nonlocal _activate_timeout_task
        if _activate_timeout_task and not _activate_timeout_task.done():
            _activate_timeout_task.cancel()
        sm.clear_activation_timeout()
        current = sm.state
        if current in (ReaderState.ACTIVE, ReaderState.READING, ReaderState.AWAITING_RESULT):
            await sm.async_transition(ReaderState.HIBERNATED, "deactivate")
        logger.info("ws_deactivate")

    async def on_read(msg: ReadMessage) -> None:
        await sm.async_transition(ReaderState.READING, "read command")
        logger.info("ws_read", "entering READING state")

        # Start timeout for READING state — if user doesn't scan within remaining activation time, timeout
        remaining = sm.remaining_timeout_seconds
        if remaining is not None and remaining > 0:
            async def _handle_reading_timeout():
                await asyncio.sleep(remaining)
                if sm.state == ReaderState.READING:
                    logger.warn("reading_timeout", f"No scan within {remaining}s")
                    # Show timeout message
                    await loop.run_in_executor(
                        None, lcd.display, "", "Timed Out", True
                    )
                    await loop.run_in_executor(None, buzzer.result_error)
                    await asyncio.sleep(2)
                    # Go back to hibernated
                    await sm.async_transition(ReaderState.HIBERNATED, "reading timeout")

            asyncio.create_task(_handle_reading_timeout())

    async def on_result(msg: ResultMessage) -> None:
        await sm.async_transition(ReaderState.ACTIVE, "result received")
        logger.info("ws_result", f"status={msg.status} item_id={msg.item_id}")

        # Buzzer feedback
        if msg.status == "success":
            await loop.run_in_executor(None, buzzer.result_success)
        else:
            await loop.run_in_executor(None, buzzer.result_error)

        # LCD result display — then restore after 30s
        rn = sm.reader_number or "?"
        if msg.status == "success":
            await loop.run_in_executor(
                None, lcd.display, "Item Found", msg.item_id or "", True
            )
        elif msg.status == "not_found":
            await loop.run_in_executor(None, lcd.display, "\u26a0\ufe0f", "Item Not Found", True)
        elif msg.status == "network_error":
            await loop.run_in_executor(None, lcd.display, "\u26a0\ufe0f", "Network Error", True)
        elif msg.status == "retry":
            await loop.run_in_executor(None, lcd.display, "\u26a0\ufe0f", "Read Error", True)

        async def _restore_lcd():
            # Shorter restore: go back to ACTIVE display after 5s
            await asyncio.sleep(5)
            if sm.state == ReaderState.ACTIVE:
                # Restore ACTIVE screen with backlight ON
                await loop.run_in_executor(
                    None, lcd.display, "Universal Reader", f"Reader {rn}", True
                )

                async def _hibernate_if_idle():
                    # If nothing else happens in ACTIVE for another 5s, hibernate.
                    await asyncio.sleep(5)
                    # Do not hibernate if an explicit activate timeout task is running
                    if sm.state == ReaderState.ACTIVE and (
                        _activate_timeout_task is None or _activate_timeout_task.done()
                    ):
                        await sm.async_transition(ReaderState.HIBERNATED, "idle timeout")

                asyncio.create_task(_hibernate_if_idle())

        asyncio.create_task(_restore_lcd())

    # ------------------------------------------------------------------
    # RC522 — tag scan callback
    # ------------------------------------------------------------------

    def on_uid_scanned(uid: str) -> None:
        """Called from the RC522 daemon thread when a tag is scanned."""
        logger.info("on_uid_scanned_callback", f"uid={uid}, state={sm.state}")
        if sm.state != ReaderState.READING:
            logger.warn("on_uid_scanned_rejected", f"Not in READING state, rejecting scan (state={sm.state})")
            return
        sm.record_scan(uid)
        logger.info("uid_scanned", uid)
        # Schedule async work from thread
        asyncio.run_coroutine_threadsafe(_handle_uid_scanned(uid), loop)

    async def _handle_uid_scanned(uid: str) -> None:
        await sm.async_transition(ReaderState.AWAITING_RESULT, "tag scanned")
        # Play a processing beep to indicate the tag is being processed
        await loop.run_in_executor(None, buzzer.result_processing)
        if ws_client._ws is not None:
            from reader.models import UidScannedMessage

            await ws_client.send_model(UidScannedMessage(uid=uid))

        # Wait for server response within remaining activation timeout.
        # If timeout expires, show "Timed Out" and hibernate.
        remaining = sm.remaining_timeout_seconds
        if remaining is not None and remaining > 0:
            # Schedule a timeout handler
            async def _handle_server_timeout():
                logger.verbose("server_timeout_wait_start", f"Waiting {remaining}s for server response in AWAITING_RESULT")
                await asyncio.sleep(remaining)
                logger.verbose("server_timeout_wait_complete", f"Timeout period ({remaining}s) elapsed")
                if sm.state == ReaderState.AWAITING_RESULT:
                    logger.warn("server_timeout", f"No result within {remaining}s, state is still AWAITING_RESULT")
                    # Show timeout message
                    logger.verbose("server_timeout_show_message", "Displaying 'Timed Out' on LCD")
                    await loop.run_in_executor(
                        None, lcd.display, "Timed Out", "No response", True
                    )
                    logger.verbose("server_timeout_show_message_complete", "Message displayed")
                    logger.verbose("server_timeout_error_beep", "Playing error beep")
                    await loop.run_in_executor(None, buzzer.result_error)
                    logger.verbose("server_timeout_error_beep_complete", "Error beep finished")
                    logger.verbose("server_timeout_display_sleep", "Sleeping 2s to show timeout message")
                    await asyncio.sleep(2)
                    logger.verbose("server_timeout_display_sleep_complete", "Sleep complete, now transitioning to HIBERNATED")
                    logger.info("server_timeout_transitioning", "Transitioning to HIBERNATED...")
                    # Go back to hibernated (this triggers update_lcd callback)
                    result = await sm.async_transition(ReaderState.HIBERNATED, "server timeout")
                    logger.verbose("server_timeout_transition_result", f"Transition result: {result}")
                    logger.info("server_timeout_hibernated", "Now in HIBERNATED, ready for new commands")
                else:
                    logger.info("server_timeout_cancelled", f"State changed to {sm.state} during timeout, not transitioning")

            asyncio.create_task(_handle_server_timeout())

    rc522 = RC522Reader(on_scan=on_uid_scanned)
    rc522.start()

    # Store RC522 ref for cleanup
    import sys
    sys.rc522_reader = rc522  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Startup hardware checkup
    # ------------------------------------------------------------------

    hw_failures = []
    if not lcd._available:
        hw_failures.append("LCD")
    if not buzzer._available:
        hw_failures.append("Buzzer")
    if not rc522._available:
        hw_failures.append("RC522")

    if hw_failures:
        logger.error("checkup_failed", f"Hardware unavailable: {', '.join(hw_failures)}")
        await sm.async_transition(ReaderState.SYSTEM_FAILURE, "hardware checkup failed")
    else:
        logger.info("checkup_ok", "All hardware components available")

    # ------------------------------------------------------------------
    # WebSocket client
    # ------------------------------------------------------------------

    ws_client = WSClient(
        url=config.inventory_ws_url,
        api_key=config.inventory_api_key,
        state_manager=sm,
        on_activate=on_activate,
        on_deactivate=on_deactivate,
        on_read=on_read,
        on_result=on_result,
    )

    # ------------------------------------------------------------------
    # FastAPI dashboard
    # ------------------------------------------------------------------

    from reader.dashboard.app import create_app

    dashboard_app = create_app(
        state_manager=sm,
        config=config,
        ws_client=ws_client,
        on_activate=on_activate,
        on_deactivate=on_deactivate,
        on_read=on_read,
        on_result=on_result,
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
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("shutdown", "KeyboardInterrupt received, cleaning up...")
        
        # Clean up hardware
        import sys
        try:
            if hasattr(sys, "lcd"):
                lcd = sys.lcd  # type: ignore[attr-defined]
                lcd.off()
                logger.info("shutdown_lcd_off", "LCD turned off")
        except Exception as exc:  # noqa: BLE001
            logger.warn("shutdown_lcd_error", str(exc))
        
        try:
            if hasattr(sys, "rc522_reader"):
                rc522 = sys.rc522_reader  # type: ignore[attr-defined]
                if rc522:
                    rc522.stop()
                    logger.info("shutdown_rc522_stop", "RC522 stopped")
        except Exception as exc:  # noqa: BLE001
            logger.warn("shutdown_rc522_error", str(exc))
        
        try:
            import RPi.GPIO as GPIO  # type: ignore[import]
            GPIO.cleanup()
            logger.info("shutdown_gpio_cleanup", "GPIO cleaned up")
        except Exception as exc:  # noqa: BLE001
            logger.warn("shutdown_gpio_cleanup_error", str(exc))
        
        print("\n[SHUTDOWN] Display cleared, GPIO cleaned, exiting...")


if __name__ == "__main__":
    main()
