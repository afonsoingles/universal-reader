"""
QUICK REFERENCE — Refactored Code Structure
=============================================

When you need to make a change, find it here:

ADDING A NEW MESSAGE FROM SERVER
================================
You received a new message type from the Inventory server.

Steps:
1. Add message class to src/reader/models.py
   class MyCustomMessage(BaseModel):
       type: Literal["my_custom"]
       field1: str

2. Add to InboundMessage union at bottom of models.py
   InboundMessage = Annotated[
       ... | MyCustomMessage,  # Add here
       Field(discriminator="type"),
   ]

3. Add handler to src/reader/handlers/message_handlers.py
   class MessageHandlers:
       async def on_my_custom(self, msg: MyCustomMessage) -> None:
           logger.info("ws_my_custom", f"field1={msg.field1}")
           # Your logic here

4. Dispatch in src/reader/ws_client.py
   In _handle_raw():
       elif isinstance(msg, MyCustomMessage):
           await self._on_my_custom(msg)  # Add this

5. Wire in src/reader/main.py
   message_handlers = MessageHandlers(...)
   # Add method reference:
   message_handlers.on_my_custom = message_handlers.on_my_custom

Done! Server message → dispatch → handler


CHANGING LCD TIMEOUT MESSAGE
===========================
The timeout display text is in tag_scan_handler.py

File: src/reader/handlers/tag_scan_handler.py
In method: _handle_server_timeout()

Before:
  await self._loop.run_in_executor(
      None, self._lcd.display, "Timed Out", "No response", True
  )

After:
  await self._loop.run_in_executor(
      None, self._lcd.display, "YOUR TEXT", "YOUR TEXT 2", True
  )


ADDING A NEW HARDWARE COMPONENT
===============================
You're adding e.g., an LED indicator.

Steps:
1. Create hardware driver: src/reader/hardware/led.py
   class LED:
       def __init__(self, config):
           self._pin = config.hardware.led_pin
       
       def on(self) -> None:
           # turn on
       
       def off(self) -> None:
           # turn off

2. Add pin config to src/reader/models.py
   class HardwareConfig(BaseModel):
       led_pin: int = 17  # Add this

3. Add to .env.example
   LED_PIN=17

4. Initialize in src/reader/startup.py
   async def initialize_hardware():
       # ... existing code ...
       led = LED(config)  # Add
       sys.led = led  # Store for cleanup
       return lcd, buzzer, rc522, led  # Return

5. Create handler: src/reader/handlers/led_handler.py
   async def create_led_update_callback(sm, led, loop):
       async def update_led(old_state, new_state):
           if new_state == ReaderState.ACTIVE:
               await loop.run_in_executor(None, led.on)
           elif new_state == ReaderState.HIBERNATED:
               await loop.run_in_executor(None, led.off)
       return update_led

6. Register in src/reader/main.py
   update_led = await create_led_update_callback(sm, led, loop)
   sm.register_state_change_callback(update_led)


ADDING A NEW STATE
==================
You want to add a MAINTENANCE state.

Steps:
1. Add to models.py ReaderState enum:
   class ReaderState(str, Enum):
       MAINTENANCE = "MAINTENANCE"
       # ... rest of states

2. Add valid transitions to state.py VALID_TRANSITIONS:
   ReaderState.ACTIVE: {ReaderState.MAINTENANCE, ...},
   ReaderState.MAINTENANCE: {ReaderState.ACTIVE, ...},

3. Add LCD display in handlers/lcd_handler.py
   elif new_state == ReaderState.MAINTENANCE:
       await loop.run_in_executor(None, lcd.display, "Maintenance", "Mode", True)

4. Add buzzer feedback in handlers/buzzer_handler.py (if needed)
   elif new_state == ReaderState.MAINTENANCE:
       # Optional: play sound

5. Trigger from message handler (handlers/message_handlers.py)
   async def on_maintenance_start(self, msg: MaintenanceStartMessage) -> None:
       await self._sm.async_transition(ReaderState.MAINTENANCE, "server request")


MODIFYING TIMEOUT BEHAVIOR
===========================
You want to change how timeouts work.

Server response timeout:
→ src/reader/handlers/tag_scan_handler.py
  Method: _handle_server_timeout()

Reading timeout:
→ src/reader/handlers/message_handlers.py
  Method: _handle_reading_timeout()

Activation timeout:
→ src/reader/handlers/message_handlers.py
  Method: _activate_timeout_cb()


ADDING LOGGING
==============
Use the logger module from reader/logger.py

Methods available:
- logger.verbose(event, detail)  # Detailed debug info
- logger.info(event, detail)      # Normal operation
- logger.warn(event, detail)      # Warning
- logger.error(event, detail)     # Error

Example:
from reader import logger
logger.info("my_event", f"my_detail={value}")


TESTING A HANDLER
=================
You want to unit test MessageHandlers.

Example test file:
# tests/test_handlers.py

import asyncio
from reader.state import StateManager
from reader.models import ActivateMessage
from reader.handlers.message_handlers import MessageHandlers

async def test_on_activate():
    sm = StateManager()
    handlers = MessageHandlers(sm, mock_lcd, mock_buzzer, asyncio.get_event_loop())
    
    msg = ActivateMessage(type="activate", timeout_seconds=30)
    await handlers.on_activate(msg)
    
    assert sm.state == ReaderState.ACTIVE
    assert sm.reader_number is None  # (not set by activate)


MAIN.PY FLOW
============
What happens when the app starts:

main.py:run()
  → initialize_hardware()           [startup.py]
  → perform_hardware_checkup()      [startup.py]
  → create_lcd_update_callback()    [handlers/lcd_handler.py]
  → create_buzzer_update_callback() [handlers/buzzer_handler.py]
  → MessageHandlers()               [handlers/message_handlers.py]
  → TagScanHandler()                [handlers/tag_scan_handler.py]
  → RC522Reader(on_scan=...)        [hardware/rc522.py]
  → WSClient(on_activate=...)       [ws_client.py]
  → create_app()                    [dashboard/app.py]
  → asyncio.gather(ws_client.run(), server.serve())

Result: Two async tasks running
  1. WebSocket client listening for server messages
  2. HTTP server for dashboard


DEBUGGING TIPS
==============

If timeouts aren't working:
→ Check logs for "server_timeout_wait_start"
→ Check sm.remaining_timeout_seconds property
→ Verify state transitions in logs

If LCD not updating:
→ Check logs for "update_lcd_callback"
→ Check logs for "lcd_display_complete" or "lcd_off_complete"
→ Verify LCD is available (check startup logs)

If RC522 not scanning:
→ Check logs for "rc522_tag_detected"
→ Check rc522._available flag
→ Verify RC522 hardware connection

If server messages not received:
→ Check "ws_connected" in dashboard /status
→ Check logs for "ws_parse_error"
→ Verify INVENTORY_WS_URL in .env

For full logs:
→ Dashboard: http://localhost:5050 → Logs tab
→ Filter by VERBOSE, INFO, WARN, ERROR as needed
"""
