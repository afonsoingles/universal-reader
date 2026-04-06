"""
ARCHITECTURE GUIDE — Universal Reader Refactoring
==================================================

This document explains the refactored codebase structure and how the components interact.

PROJECT STRUCTURE
=================

src/reader/
├── main.py                 # Entry point — orchestrates initialization & startup
├── startup.py              # Hardware initialization and cleanup routines
├── config.py               # Configuration loading from environment
├── state.py                # State machine implementation (StateManager)
├── models.py               # Pydantic data models
├── logger.py               # In-memory circular log
├── ws_client.py            # WebSocket client (Inventory server communication)
├── handlers/               # Message and event handlers (NEW)
│   ├── __init__.py
│   ├── lcd_handler.py      # LCD display callback on state changes
│   ├── buzzer_handler.py   # Buzzer feedback callback on state changes
│   ├── message_handlers.py # WebSocket message handlers (activate, read, result, etc.)
│   └── tag_scan_handler.py # RC522 tag scan & timeout handling
├── hardware/
│   ├── __init__.py
│   ├── lcd.py              # 16x2 LCD I2C control (RPLCD wrapper)
│   ├── buzzer.py           # Passive buzzer PWM control (pigpio wrapper)
│   └── rc522.py            # RC522 RFID reader (mfrc522 wrapper with threading)
└── dashboard/
    ├── app.py              # FastAPI application
    └── templates/          # HTML templates

COMPONENT RESPONSIBILITIES
===========================

main.py
-------
Role: Application orchestrator
- Initializes all components in order
- Registers state change callbacks (LCD, buzzer)
- Creates and wires MessageHandlers and TagScanHandler
- Sets up WebSocket client and dashboard
- Manages async event loop

startup.py (NEW)
----------------
Role: Hardware initialization and lifecycle management
Functions:
- initialize_hardware()          → Creates LCD, Buzzer, RC522 instances
- perform_hardware_checkup()     → Verifies all components are available
- transition_to_failure_on_hardware_issues() → Transitions to SYSTEM_FAILURE if needed
- cleanup_on_exit()              → Cleans up LCD, RC522, GPIO on KeyboardInterrupt

handlers/lcd_handler.py (NEW)
-----------------------------
Role: Renders LCD display based on state
- create_lcd_update_callback()   → Factory for state change callback
Updates LCD based on state:
  HIBERNATED       → Turn off LCD (backlight off, clear)
  ACTIVE           → "Universal Reader" + "Reader #N"
  READING          → "Universal Reader" + "Scan item..."
  AWAITING_RESULT  → "Universal Reader" + "Processing..."
  SYSTEM_FAILURE   → "⚠️" + "System Failure"
  LOCALLY_DISABLED → Turn off LCD

handlers/buzzer_handler.py (NEW)
--------------------------------
Role: Provides audio feedback on state transitions
- create_buzzer_update_callback() → Factory for state change callback
Sounds:
  READING state          → reading_start beep (520Hz)
  SYSTEM_FAILURE→ACTIVE  → result_success beeps

handlers/message_handlers.py (NEW)
---------------------------------
Role: Processes WebSocket messages from Inventory server
Class: MessageHandlers
Methods:
  on_activate(msg)    → Transitions to ACTIVE, sets activation timeout
  on_deactivate(msg)  → Transitions to HIBERNATED, cancels timeout
  on_read(msg)        → Transitions to READING, starts read timeout
  on_result(msg)      → Shows result on LCD, restores ACTIVE after 5s
Timeout handling:
  _activate_timeout_cb()      → Global activation timeout (transitions to HIBERNATED)
  _handle_reading_timeout()   → Reading timeout (shows "Timed Out", hibernates)
  _restore_lcd_after_result() → Restores LCD after 5s, hibernates if idle

handlers/tag_scan_handler.py (NEW)
---------------------------------
Role: Handles RC522 tag scans and server response timeouts
Class: TagScanHandler
Methods:
  on_uid_scanned_from_thread(uid)     → Thread callback from RC522 daemon
  _handle_uid_scanned_async(uid)      → Async wrapper, sends to server
  _handle_server_timeout(remaining)   → Handles timeout waiting for server response
Timeout behavior:
  - Displays "No Response" / "Retrying..." for 2s
  - Plays error beep
  - Transitions to HIBERNATED
  - Allows server to regain control via new ACTIVATE/READ messages

state.py (StateManager)
----------------------
Role: Thread-safe state machine
- Tracks current state (ReaderState enum)
- Enforces valid state transitions (VALID_TRANSITIONS dict)
- Tracks activation timeout (remaining_timeout_seconds property)
- Notifies observers on state change (async callbacks)

ws_client.py (WSClient)
-----------------------
Role: WebSocket client for Inventory server
- Connects to INVENTORY_WS_URL
- Sends register message with api_key
- Dispatches incoming messages to handlers
- Auto-reconnects with exponential backoff
- Transitions to SYSTEM_FAILURE on disconnect

KEY IMPROVEMENTS
================

Before Refactoring:
- main.py: 359 lines
- All logic (handlers, timeouts, LCD/buzzer updates) in one file
- Hard to maintain, test, or extend
- Nested functions made reasoning difficult

After Refactoring:
- main.py: 138 lines (62% reduction)
- handlers/: 4 specialized, single-responsibility modules
- startup.py: Cleaner initialization & lifecycle
- Each module is testable and reusable
- Clear data flow: Message → Handler → State Change → Callbacks

MESSAGE FLOW DIAGRAM
====================

1. SERVER ACTIVATION:
   WS receives ActivateMessage
   → MessageHandlers.on_activate()
   → StateManager.async_transition(ACTIVE)
   → LCD callback: display "Universal Reader"
   → Buzzer callback: (no sound)
   → Global timeout task created

2. USER SCANS TAG:
   RC522 daemon thread detects UID
   → TagScanHandler.on_uid_scanned_from_thread()
   → Schedules async work on event loop
   → TagScanHandler._handle_uid_scanned_async()
   → StateManager.async_transition(AWAITING_RESULT)
   → LCD callback: display "Processing..."
   → Buzzer: result_processing beep (1400Hz)
   → Send UidScannedMessage to server
   → _handle_server_timeout() task created

3. SERVER TIMEOUT (no response):
   _handle_server_timeout() fires after remaining seconds
   → LCD displays "No Response" / "Retrying..."
   → Buzzer: result_error beep (1600Hz)
   → Sleep 2s
   → StateManager.async_transition(HIBERNATED)
   → LCD callback: turn off LCD

4. RESULT RECEIVED:
   WS receives ResultMessage
   → MessageHandlers.on_result()
   → StateManager.async_transition(ACTIVE)
   → LCD: displays result (Item Found / Not Found / etc.)
   → Buzzer: result_success or result_error
   → Schedule _restore_lcd_after_result() (5s)

TIMEOUT CASCADE
===============

All timeouts respect the global activation timeout set by server:

ACTIVE state
├─ activation_timeout (global, e.g., 60s)
│
├─ on_read() → READING state
│  └─ reading_timeout = remaining_timeout_seconds
│     └─ If elapsed: show "Timed Out", hibernate
│
└─ tag_scanned → AWAITING_RESULT state
   └─ server_timeout = remaining_timeout_seconds
      └─ If elapsed: show "No Response", hibernate


TESTING & VALIDATION
====================

To test the refactored code:

1. Run the application:
   $ uv run universal-reader

2. Trigger server timeout scenario:
   - Dashboard: send ACTIVATE (e.g., timeout=30s)
   - Dashboard: send READ
   - Dashboard: wait for RC522 scan (or simulate with DEBUG)
   - Let server_timeout fire (or manually wait 30s)
   - Verify logs show:
     * "server_timeout_wait_complete"
     * "server_timeout_show_message_complete"
     * "server_timeout_hibernated"
     * "update_lcd_callback" (state change)
     * "update_lcd_hibernated_complete"

3. Verify recovery:
   - After hibernation, send new ACTIVATE or READ
   - Device should accept (HIBERNATED allows these messages)
   - No "scan_in_progress" error should occur

EXTENDING THE CODEBASE
======================

To add a new feature:

1. New Message Type from Server?
   → Add to models.py (InboundMessage union)
   → Add handler method to MessageHandlers
   → Dispatch in ws_client.py

2. New Hardware Component?
   → Create hardware/<device>.py with init, start, methods
   → Add to startup.py initialization
   → Create handlers/<device>_handler.py for feedback
   → Register callback in main.py

3. New State or Transition?
   → Add to ReaderState enum (models.py)
   → Update VALID_TRANSITIONS (state.py)
   → Add LCD display case (handlers/lcd_handler.py)
   → Add buzzer case (handlers/buzzer_handler.py)

"""
