"""LCD state change callback handler."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from reader import logger
from reader.models import ReaderState

if TYPE_CHECKING:
    from reader.hardware.lcd import LCD
    from reader.state import StateManager


async def create_lcd_update_callback(sm: StateManager, lcd: LCD, loop: asyncio.AbstractEventLoop):
    """Create an async callback for LCD updates on state changes."""
    
    async def update_lcd(old_state: ReaderState, new_state: ReaderState) -> None:
        """Update LCD display based on new state."""
        logger.verbose("update_lcd_callback", f"Callback invoked: {old_state} → {new_state}")
        rn = sm.reader_number or "?"
        
        if new_state == ReaderState.HIBERNATED:
            logger.verbose("update_lcd_hibernated", "Turning off LCD (HIBERNATED state)")
            await loop.run_in_executor(None, lcd.off)
            logger.verbose("update_lcd_hibernated_complete", "LCD off completed")
        elif new_state == ReaderState.ACTIVE:
            logger.verbose("update_lcd_active", "Displaying ACTIVE screen")
            await loop.run_in_executor(None, lcd.display, "Universal Reader", f"Reader {rn}", True)
        elif new_state == ReaderState.READING:
            logger.verbose("update_lcd_reading", "Displaying READING screen")
            await loop.run_in_executor(None, lcd.display, "Universal Reader", "Scan item...", True)
        elif new_state == ReaderState.AWAITING_RESULT:
            logger.verbose("update_lcd_awaiting", "Displaying AWAITING_RESULT screen")
            await loop.run_in_executor(None, lcd.display, "Universal Reader", "Processing...", True)
        elif new_state == ReaderState.SYSTEM_FAILURE:
            logger.verbose("update_lcd_failure", "Displaying SYSTEM_FAILURE screen")
            await loop.run_in_executor(None, lcd.display, "\u26a0\ufe0f", "System Failure", True)
        elif new_state == ReaderState.LOCALLY_DISABLED:
            logger.verbose("update_lcd_disabled", "Turning off LCD (LOCALLY_DISABLED state)")
            await loop.run_in_executor(None, lcd.off)
    
    return update_lcd
