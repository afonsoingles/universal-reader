"""
COMPONENT INTERACTION DIAGRAM
==============================

APPLICATION INITIALIZATION
==========================

main.py:run()
│
├─→ startup.initialize_hardware()
│   └─→ Creates: LCD, Buzzer, RC522
│       └─→ Stores in sys globals for cleanup
│
├─→ startup.transition_to_failure_on_hardware_issues()
│   └─→ If any hardware unavailable → SYSTEM_FAILURE
│
├─→ create_lcd_update_callback()
│   └─→ Returns: async update_lcd(old_state, new_state)
│       └─→ Registered with StateManager
│
├─→ create_buzzer_update_callback()
│   └─→ Returns: async update_buzzer(old_state, new_state)
│       └─→ Registered with StateManager
│
├─→ MessageHandlers(sm, lcd, buzzer, loop)
│   └─→ Stores references for on_activate, on_deactivate, on_read, on_result
│
├─→ TagScanHandler(sm, lcd, buzzer, loop)
│   └─→ Provides on_uid_scanned_from_thread callback for RC522
│
├─→ RC522Reader(on_scan=tag_scan_handler.on_uid_scanned_from_thread)
│   └─→ Starts daemon thread for scanning
│
├─→ WSClient(on_activate, on_deactivate, on_read, on_result)
│   └─→ Connects to Inventory server
│       └─→ Dispatches messages to MessageHandlers
│
└─→ Create FastAPI dashboard with handlers


MESSAGE FLOW — SERVER ACTIVATE
==============================

Server sends: {"type": "activate", "timeout_seconds": 30}
                        ↓
    WSClient receives and parses
                        ↓
    ws_client._handle_raw(ActivateMessage)
                        ↓
    Calls: message_handlers.on_activate(msg)
                        ↓
    MessageHandlers:
    ├─ Cancel previous timeout task
    ├─ StateManager.async_transition(ACTIVE, "activate")
    │   └─→ LCD callback fires: display "Universal Reader"
    │   └─→ Buzzer callback: (no sound for ACTIVE)
    ├─ Set activation timeout (30s)
    └─ Create _activate_timeout_cb task
        └─→ If still ACTIVE after 30s → HIBERNATED


MESSAGE FLOW — USER SCANS TAG
=============================

RC522 daemon thread detects tag with UID "DEADBEEF"
                        ↓
    Calls: on_uid_scanned_from_thread("DEADBEEF")  [from RC522Reader]
    (This is tag_scan_handler.on_uid_scanned_from_thread)
                        ↓
    Schedules: asyncio.run_coroutine_threadsafe(
                    _handle_uid_scanned_async(uid), loop)
                        ↓
    TagScanHandler._handle_uid_scanned_async("DEADBEEF"):
    ├─ StateManager.async_transition(AWAITING_RESULT, "tag scanned")
    │   └─→ LCD callback: display "Processing..."
    ├─ Buzzer: result_processing (1400Hz, 0.75s)
    ├─ WSClient: send UidScannedMessage("DEADBEEF")
    └─ Create _handle_server_timeout(remaining_seconds) task
        └─→ Sleep for remaining seconds
        └─→ If still AWAITING_RESULT:
            ├─ LCD: "No Response" / "Retrying..."
            ├─ Buzzer: result_error (1600Hz ×3)
            ├─ Sleep 2s
            └─ StateManager.async_transition(HIBERNATED)
                └─→ LCD callback: turn off LCD


MESSAGE FLOW — SERVER RESPONSE (SUCCESS)
========================================

Server sends: {"type": "result", "status": "success", "item_id": "R-0042"}
                        ↓
    WSClient receives and parses
                        ↓
    ws_client._handle_raw(ResultMessage)
                        ↓
    Calls: message_handlers.on_result(msg)
                        ↓
    MessageHandlers:
    ├─ StateManager.async_transition(ACTIVE, "result received")
    ├─ Buzzer: result_success (1200Hz ×2)
    ├─ LCD: display "Item Found" / "R-0042"
    └─ Create _restore_lcd_after_result() task
        └─→ Sleep 5s
        └─→ If ACTIVE: restore "Universal Reader" display
        └─→ Create _hibernate_if_idle() task
            └─→ Sleep 5s
            └─→ If still ACTIVE and no timeout running: HIBERNATED


STATE CHANGE FLOW
================

StateManager.async_transition(new_state)
                        ↓
    Acquire async lock
                        ↓
    Change state
                        ↓
    Notify all registered callbacks:
    ├─→ await update_lcd(old_state, new_state)
    │   └─→ LCD displays appropriate content for new_state
    └─→ await update_buzzer(old_state, new_state)
        └─→ Buzzer plays appropriate sound for transition


TIMEOUT CASCADE DIAGRAM
======================

ACTIVE state begins (received ActivateMessage with timeout_seconds=30)
    │
    ├─ _activate_timeout_cb scheduled for 30s
    │  └─ If state==ACTIVE at 30s: HIBERNATED
    │
    └─ User sends READ message → READING state
       │
       ├─ reading_timeout scheduled for remaining_seconds (e.g., 25s)
       │  └─ If state==READING at 25s: show "Timed Out", HIBERNATED
       │
       └─ User scans tag → AWAITING_RESULT state
          │
          └─ server_timeout scheduled for remaining_seconds (e.g., 23s)
             └─ If state==AWAITING_RESULT at 23s: 
                show "No Response"/"Retrying...", HIBERNATED


HIBERNATED STATE RECOVERY
========================

Device in HIBERNATED → LCD off, no activity
                        ↓
    Server sends: {"type": "activate", ...}
                        ↓
    WSClient checks: is state in (HIBERNATED, ACTIVE)?
    ├─ YES: Calls message_handlers.on_activate()
    │       └─ HIBERNATED → ACTIVE (allowed by state machine)
    │       └─ LCD callback: turn on LCD
    └─ NO: Rejects with error


DEPENDENCY GRAPH
================

main.py
├─→ startup.py
│   └─→ hardware/ (LCD, Buzzer, RC522Reader)
│
├─→ handlers/lcd_handler.py
│   ├─→ StateManager
│   └─→ hardware/lcd.py
│
├─→ handlers/buzzer_handler.py
│   ├─→ StateManager
│   └─→ hardware/buzzer.py
│
├─→ handlers/message_handlers.py
│   ├─→ StateManager
│   ├─→ hardware/lcd.py
│   └─→ hardware/buzzer.py
│
├─→ handlers/tag_scan_handler.py
│   ├─→ StateManager
│   ├─→ hardware/lcd.py
│   ├─→ hardware/buzzer.py
│   └─→ ws_client.py (for sending UidScannedMessage)
│
├─→ ws_client.py
│   ├─→ StateManager
│   └─→ models.py
│
└─→ dashboard/app.py
    ├─→ StateManager
    ├─→ handlers/* (via message_handlers references)
    └─→ hardware/*


THREAD/ASYNC MODEL
==================

Main async event loop (asyncio):
├─ WSClient.run()
│  └─ Listens for WebSocket messages
│     └─ Dispatches to MessageHandlers async methods
│
├─ Dashboard server (uvicorn)
│  └─ Listens for HTTP requests
│
└─ Various async tasks:
   ├─ _activate_timeout_cb
   ├─ _handle_reading_timeout
   ├─ _handle_server_timeout
   ├─ _restore_lcd_after_result
   └─ _hibernate_if_idle

Separate daemon thread (RC522):
├─ RC522Reader._read_loop()
│  └─ Polls for RFID tags continuously
│     └─ Calls tag_scan_handler.on_uid_scanned_from_thread() (from thread)
│        └─ Schedules async work on main event loop via
│           asyncio.run_coroutine_threadsafe()

Thread synchronization:
└─ StateManager uses asyncio.Lock for async contexts
                          and threading.Lock for sync contexts
"""
