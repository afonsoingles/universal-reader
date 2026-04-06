"""Buzzer feedback callback handler."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from reader import logger
from reader.models import ReaderState

if TYPE_CHECKING:
    from reader.hardware.buzzer import Buzzer
    from reader.state import StateManager


async def create_buzzer_update_callback(sm: StateManager, buzzer: Buzzer, loop: asyncio.AbstractEventLoop):
    """Create an async callback for buzzer feedback on state changes."""
    
    async def update_buzzer(old_state: ReaderState, new_state: ReaderState) -> None:
        """Play buzzer feedback based on state transition."""
        if new_state == ReaderState.READING:
            logger.verbose("buzzer_reading_start", "Playing reading start beep")
            await loop.run_in_executor(None, buzzer.reading_start)
    
    return update_buzzer
