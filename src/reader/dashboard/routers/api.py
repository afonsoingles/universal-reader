"""REST API router — all endpoints are served under the ``/api/v1`` prefix.

Endpoint map
------------
GET    /api/v1/status                  Reader status (public)

GET    /api/v1/logs                    Structured log entries (auth)
DELETE /api/v1/logs                    Clear log entries (auth)

POST   /api/v1/reader/disable          Locally disable the reader (auth)
POST   /api/v1/reader/enable           Re-enable after local disable (auth)
POST   /api/v1/reader/reconnect        Force WebSocket reconnect (auth)

GET    /api/v1/hardware                Hardware availability status (auth)
POST   /api/v1/hardware/buzzer/test    Run buzzer self-test sequence (auth)
POST   /api/v1/hardware/lcd/test       Run LCD self-test (auth)

GET    /api/v1/debug/state             Verbose internal state dump (auth)
POST   /api/v1/debug/uid               Read one UID from RC522 (auth)
POST   /api/v1/debug/simulate          Simulate an Inventory message (auth)
POST   /api/v1/debug/buzzer/tone       Play a custom buzzer tone (auth)
POST   /api/v1/debug/buzzer/pattern    Play a named buzzer pattern (auth)
POST   /api/v1/debug/lcd               Write custom text to the LCD (auth)
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from reader import logger
from reader.dashboard.deps import require_auth
from reader.models import (
    ActivateMessage,
    DeactivateMessage,
    ReadMessage,
    ReaderState,
    ReaderStatus,
    ResultMessage,
    UidScannedMessage,
)

router = APIRouter(prefix="/api/v1")

# ---------------------------------------------------------------------------
# Status — public
# ---------------------------------------------------------------------------


@router.get("/status", response_model=ReaderStatus)
async def status_endpoint(request: Request):
    """Return current reader status (no authentication required)."""
    sm = request.app.state.sm
    return ReaderStatus(
        state=sm.state.value,
        reader_number=sm.reader_number,
        ws_connected=sm.ws_connected,
        uptime_seconds=sm.uptime_seconds,
        last_scan=sm.last_scan,
        locally_disabled=sm.locally_disabled,
    )


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


@router.get("/logs", dependencies=[Depends(require_auth)])
async def get_logs(
    request: Request,
    level: list[str] | None = Query(default=None),
):
    """Return structured log entries, optionally filtered by level."""
    allowed = {lv.upper() for lv in level} if level else None
    entries = logger.get_entries(levels=allowed)
    return [e.model_dump(mode="json") for e in entries]


@router.delete("/logs", dependencies=[Depends(require_auth)])
async def clear_logs(request: Request):
    """Clear all log entries."""
    logger.clear()
    logger.info("dashboard_logs_cleared")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Reader actions
# ---------------------------------------------------------------------------


@router.post("/reader/disable", dependencies=[Depends(require_auth)])
async def reader_disable(request: Request):
    """Locally disable the reader — it will ignore all Inventory messages."""
    sm = request.app.state.sm
    await sm.async_transition(ReaderState.LOCALLY_DISABLED, "dashboard disable")
    logger.info("dashboard_disable")
    return {"ok": True}


@router.post("/reader/enable", dependencies=[Depends(require_auth)])
async def reader_enable(request: Request):
    """Re-enable a locally disabled reader."""
    sm = request.app.state.sm
    if sm.state != ReaderState.LOCALLY_DISABLED:
        raise HTTPException(status_code=400, detail="Not locally disabled")
    await sm.async_transition(ReaderState.ACTIVE, "dashboard re-enable")
    logger.info("dashboard_enable")
    return {"ok": True}


@router.post("/reader/reconnect", dependencies=[Depends(require_auth)])
async def reader_reconnect(request: Request):
    """Force a WebSocket reconnect by transitioning to SYSTEM_FAILURE."""
    sm = request.app.state.sm
    logger.info("dashboard_force_reconnect")
    sm.reconnect_attempts = 0
    if sm.state != ReaderState.LOCALLY_DISABLED:
        await sm.async_transition(ReaderState.SYSTEM_FAILURE, "dashboard force reconnect")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------


@router.get("/hardware", dependencies=[Depends(require_auth)])
async def hardware_status(request: Request):
    """Return hardware availability for LCD, buzzer, and RC522."""
    lcd = request.app.state.lcd
    buzzer = request.app.state.buzzer
    rc522 = request.app.state.rc522
    return {
        "lcd": {"available": lcd._available},
        "buzzer": {"available": buzzer._available},
        "rc522": {"available": rc522._available},
    }


@router.post("/hardware/buzzer/test", dependencies=[Depends(require_auth)])
async def hardware_buzzer_test(request: Request):
    """Run the full buzzer self-test sequence (reading_start → success → error)."""
    buzzer = request.app.state.buzzer
    logger.info("dashboard_test_buzzer")

    async def _run():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, buzzer.reading_start)
        await asyncio.sleep(0.5)
        await loop.run_in_executor(None, buzzer.result_success)
        await asyncio.sleep(1.0)
        await loop.run_in_executor(None, buzzer.result_error)

    asyncio.create_task(_run())
    return {"ok": True}


@router.post("/hardware/lcd/test", dependencies=[Depends(require_auth)])
async def hardware_lcd_test(request: Request):
    """Display a test pattern on the LCD then restore the current state."""
    sm = request.app.state.sm
    lcd = request.app.state.lcd
    logger.info("dashboard_test_lcd")

    async def _run():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lcd.display, "  LCD Test  ", "  Pattern   ", True)
        await asyncio.sleep(3)
        await _refresh_lcd(sm, lcd)

    asyncio.create_task(_run())
    return {"ok": True}


# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------


@router.get("/debug/state", dependencies=[Depends(require_auth)])
async def debug_state(request: Request):
    """Return a verbose internal state snapshot."""
    sm = request.app.state.sm
    return {
        "state": sm.state.value,
        "reader_number": sm.reader_number,
        "ws_connected": sm.ws_connected,
        "last_uid": sm.last_uid,
        "reconnect_attempts": sm.reconnect_attempts,
        "uptime_seconds": round(sm.uptime_seconds, 1),
        "locally_disabled": sm.locally_disabled,
    }


@router.post("/debug/uid", dependencies=[Depends(require_auth)])
async def debug_read_uid(request: Request):
    """Read one UID directly from the RC522 (bypasses state machine)."""
    sm = request.app.state.sm
    rc522 = request.app.state.rc522
    if sm.state in (ReaderState.READING, ReaderState.AWAITING_RESULT):
        raise HTTPException(status_code=409, detail="Scan in progress — cannot use debug read")
    loop = asyncio.get_event_loop()
    uid = await loop.run_in_executor(None, rc522.read_once)
    logger.info("debug_read_uid", f"uid={uid}")
    return {"uid": uid}


@router.post("/debug/simulate", dependencies=[Depends(require_auth)])
async def debug_simulate(request: Request, body: dict[str, Any] = None):
    """Simulate an Inventory WebSocket message for testing purposes."""
    sm = request.app.state.sm
    ws_client = request.app.state.ws_client
    on_activate = request.app.state.on_activate
    on_deactivate = request.app.state.on_deactivate
    on_read = request.app.state.on_read
    on_result = request.app.state.on_result

    if body is None:
        body = await request.json()
    msg_type = body.get("type")
    logger.info("debug_simulate", str(body))

    if msg_type == "activate":
        timeout = int(body.get("timeout_seconds", 30))
        await on_activate(ActivateMessage(type="activate", timeout_seconds=timeout))
    elif msg_type == "deactivate":
        await on_deactivate(DeactivateMessage(type="deactivate"))
    elif msg_type == "read":
        if sm.state in (ReaderState.READING, ReaderState.AWAITING_RESULT):
            raise HTTPException(status_code=409, detail="Scan in progress")
        await on_read(ReadMessage(type="read"))
    elif msg_type == "result":
        status = body.get("status", "success")
        item_id = body.get("item_id")
        await on_result(ResultMessage(type="result", status=status, item_id=item_id))
    elif msg_type == "uid_scanned":
        uid = str(body.get("uid", "DEADBEEF"))
        if sm.state != ReaderState.READING:
            raise HTTPException(status_code=409, detail="Must be in READING state")
        sm.record_scan(uid)
        logger.info("debug_uid_scanned", uid)
        await sm.async_transition(ReaderState.AWAITING_RESULT, "debug uid scan")
        if ws_client is not None and ws_client._ws is not None:
            await ws_client.send_model(UidScannedMessage(uid=uid))
    elif msg_type == "system_failure":
        await sm.async_transition(ReaderState.SYSTEM_FAILURE, "debug simulate")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown simulate type: {msg_type}")

    return {"ok": True}


@router.post("/debug/buzzer/tone", dependencies=[Depends(require_auth)])
async def debug_buzzer_tone(request: Request):
    """Play a custom buzzer tone at the specified frequency and duration."""
    buzzer = request.app.state.buzzer
    body = await request.json()
    freq = int(body.get("freq", 1000))
    duration = float(body.get("duration", 0.3))
    logger.info("debug_buzzer_tone", f"freq={freq} duration={duration}")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, buzzer.beep, freq, duration)
    return {"ok": True}


@router.post("/debug/buzzer/pattern", dependencies=[Depends(require_auth)])
async def debug_buzzer_pattern(request: Request):
    """Play a named buzzer pattern (reading_start, result_success, result_error)."""
    buzzer = request.app.state.buzzer
    body = await request.json()
    pattern = str(body.get("pattern", "reading_start"))
    logger.info("debug_buzzer_pattern", pattern)
    loop = asyncio.get_event_loop()
    if pattern == "reading_start":
        await loop.run_in_executor(None, buzzer.reading_start)
    elif pattern == "result_success":
        await loop.run_in_executor(None, buzzer.result_success)
    elif pattern == "result_error":
        await loop.run_in_executor(None, buzzer.result_error)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown pattern: {pattern!r}")
    return {"ok": True}


@router.post("/debug/lcd", dependencies=[Depends(require_auth)])
async def debug_lcd_custom(request: Request):
    """Write custom text to both LCD lines."""
    lcd = request.app.state.lcd
    body = await request.json()
    line1 = str(body.get("line1", ""))
    line2 = str(body.get("line2", ""))
    logger.info("debug_lcd_custom", f"line1={line1!r} line2={line2!r}")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lcd.display, line1, line2, True)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _refresh_lcd(sm, lcd) -> None:
    """Re-render the LCD to reflect the current reader state."""
    loop = asyncio.get_event_loop()
    rn = sm.reader_number or "?"
    state = sm.state
    if state == ReaderState.HIBERNATED:
        await loop.run_in_executor(None, lcd.off)
    elif state == ReaderState.ACTIVE:
        await loop.run_in_executor(None, lcd.display, "Universal Reader", f"Reader {rn}", True)
    elif state == ReaderState.READING:
        await loop.run_in_executor(None, lcd.display, "Universal Reader", "Scan item...", True)
    elif state == ReaderState.AWAITING_RESULT:
        await loop.run_in_executor(None, lcd.display, "Universal Reader", "Processing...", True)
    elif state == ReaderState.SYSTEM_FAILURE:
        await loop.run_in_executor(None, lcd.display, "Sorry!", "System Failure", True)
    elif state == ReaderState.LOCALLY_DISABLED:
        await loop.run_in_executor(None, lcd.display, "Sorry!", "Reader Disabled", True)
