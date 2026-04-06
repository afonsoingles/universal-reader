"""Application startup and initialization."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

from reader import logger
from reader.config import get_config
from reader.hardware.buzzer import Buzzer
from reader.hardware.lcd import LCD
from reader.hardware.rc522 import RC522Reader
from reader.models import ReaderState
from reader.state import get_state_manager

if TYPE_CHECKING:
    pass


async def initialize_hardware() -> tuple[LCD, Buzzer, RC522Reader]:
    """Initialize all hardware components."""
    config = get_config()
    
    lcd = LCD(config)
    buzzer = Buzzer(config)
    rc522 = RC522Reader(on_scan=None)  # Callback set later
    
    # Store refs globally for cleanup on exit
    sys.lcd = lcd  # type: ignore[attr-defined]
    sys.buzzer = buzzer  # type: ignore[attr-defined]
    sys.rc522_reader = None  # type: ignore[attr-defined]
    
    logger.info("hardware_init", "Hardware components initialized")
    return lcd, buzzer, rc522


async def perform_hardware_checkup(lcd: LCD, buzzer: Buzzer, rc522: RC522Reader) -> bool:
    """Check that all hardware is available."""
    hw_failures = []
    if not lcd._available:
        hw_failures.append("LCD")
    if not buzzer._available:
        hw_failures.append("Buzzer")
    if not rc522._available:
        hw_failures.append("RC522")

    if hw_failures:
        logger.error("checkup_failed", f"Hardware unavailable: {', '.join(hw_failures)}")
        return False
    
    logger.info("checkup_ok", "All hardware components available")
    return True


async def transition_to_failure_on_hardware_issues(sm, lcd: LCD, buzzer: Buzzer, rc522: RC522Reader) -> None:
    """Transition to SYSTEM_FAILURE if hardware is not available."""
    if not await perform_hardware_checkup(lcd, buzzer, rc522):
        await sm.async_transition(ReaderState.SYSTEM_FAILURE, "hardware checkup failed")


def cleanup_on_exit() -> None:
    """Clean up hardware on application exit."""
    logger.info("shutdown", "KeyboardInterrupt received, cleaning up...")
    
    # Clean up LCD
    try:
        if hasattr(sys, "lcd"):
            lcd = sys.lcd  # type: ignore[attr-defined]
            lcd.off()
            logger.info("shutdown_lcd_off", "LCD turned off")
    except Exception as exc:  # noqa: BLE001
        logger.warn("shutdown_lcd_error", str(exc))
    
    # Clean up RC522
    try:
        if hasattr(sys, "rc522_reader"):
            rc522 = sys.rc522_reader  # type: ignore[attr-defined]
            if rc522:
                rc522.stop()
                logger.info("shutdown_rc522_stop", "RC522 stopped")
    except Exception as exc:  # noqa: BLE001
        logger.warn("shutdown_rc522_error", str(exc))
    
    # Clean up GPIO
    try:
        import RPi.GPIO as GPIO  # type: ignore[import]
        GPIO.cleanup()
        logger.info("shutdown_gpio_cleanup", "GPIO cleaned up")
    except Exception as exc:  # noqa: BLE001
        logger.warn("shutdown_gpio_cleanup_error", str(exc))
    
    print("\n[SHUTDOWN] Display cleared, GPIO cleaned, exiting...")
