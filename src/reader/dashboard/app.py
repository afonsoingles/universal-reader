"""FastAPI dashboard application for the Universal Reader."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from reader import logger
from reader.models import (
    ActivateMessage,
    DeactivateMessage,
    ReadMessage,
    ReaderState,
    ReaderStatus,
    ResultMessage,
)
from reader.state import StateManager

if TYPE_CHECKING:
    pass

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# PBKDF2 iterations — computationally expensive to deter brute-force
_PBKDF2_ITERATIONS = 260_000
_PBKDF2_SALT = os.urandom(16)


def _hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 (salt stored module-level at startup)."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        _PBKDF2_SALT,
        _PBKDF2_ITERATIONS,
    ).hex()


def _make_session_token(password_hash: str, secret: str) -> str:
    return hmac.new(secret.encode(), password_hash.encode(), hashlib.sha256).hexdigest()


def create_app(
    state_manager: StateManager,
    config,
    ws_client,
    on_activate,
    on_deactivate,
    on_read,
    on_result,
    buzzer,
    lcd,
    rc522,
) -> FastAPI:
    app = FastAPI(title="Universal Reader Dashboard", docs_url=None, redoc_url=None)
    _secret = secrets.token_hex(32)
    _pw_hash = _hash_password(config.dashboard_password)
    _session_token = _make_session_token(_pw_hash, _secret)

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _is_authenticated(request: Request) -> bool:
        token = request.cookies.get("session")
        return token is not None and hmac.compare_digest(token, _session_token)

    def _require_auth(request: Request) -> None:
        if not _is_authenticated(request):
            raise HTTPException(status_code=303, headers={"Location": "/login"})

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------

    @app.get("/status")
    async def status_endpoint() -> ReaderStatus:
        sm = state_manager
        return ReaderStatus(
            state=sm.state.value,
            reader_number=sm.reader_number,
            ws_connected=sm.ws_connected,
            uptime_seconds=sm.uptime_seconds,
            last_scan=sm.last_scan,
            locally_disabled=sm.locally_disabled,
        )

    # ------------------------------------------------------------------
    # Auth endpoints
    # ------------------------------------------------------------------

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login")
    async def login_post(request: Request, password: str = Form(...)):
        if hmac.compare_digest(_hash_password(password), _pw_hash):
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie("session", _session_token, httponly=True, samesite="strict")
            logger.info("dashboard_login", request.client.host if request.client else "unknown")
            return response
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid password"}, status_code=401
        )

    @app.get("/logout")
    async def logout():
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie("session")
        return response

    # ------------------------------------------------------------------
    # Dashboard (main)
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if not _is_authenticated(request):
            return RedirectResponse(url="/login", status_code=303)
        sm = state_manager
        context = {
            "state": sm.state.value,
            "reader_number": sm.reader_number,
            "ws_connected": sm.ws_connected,
            "uptime_seconds": round(sm.uptime_seconds, 1),
            "last_scan": sm.last_scan.isoformat() if sm.last_scan else None,
            "locally_disabled": sm.locally_disabled,
        }
        return templates.TemplateResponse(request, "index.html", context)

    # ------------------------------------------------------------------
    # Log endpoint
    # ------------------------------------------------------------------

    @app.get("/logs")
    async def logs_endpoint(request: Request):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        entries = logger.get_entries()
        return [e.model_dump(mode="json") for e in entries]

    @app.post("/logs/clear")
    async def clear_logs(request: Request):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        logger.clear()
        logger.info("dashboard_logs_cleared")
        return {"ok": True}

    # ------------------------------------------------------------------
    # Action endpoints
    # ------------------------------------------------------------------

    @app.post("/action/disable")
    async def action_disable(request: Request):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        await state_manager.async_transition(ReaderState.LOCALLY_DISABLED, "dashboard disable")
        logger.info("dashboard_disable")
        return {"ok": True}

    @app.post("/action/enable")
    async def action_enable(request: Request):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if state_manager.state != ReaderState.LOCALLY_DISABLED:
            raise HTTPException(status_code=400, detail="Not locally disabled")
        await state_manager.async_transition(ReaderState.ACTIVE, "dashboard re-enable")
        logger.info("dashboard_enable")
        return {"ok": True}

    @app.post("/action/test-buzzer")
    async def action_test_buzzer(request: Request):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
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

    @app.post("/action/test-lcd")
    async def action_test_lcd(request: Request):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        logger.info("dashboard_test_lcd")

        async def _run():
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lcd.display, "  LCD Test  ", "  Pattern   ", True)
            await asyncio.sleep(3)
            # Restore current state display — trigger state callback
            await _refresh_lcd()

        asyncio.create_task(_run())
        return {"ok": True}

    async def _refresh_lcd():
        """Re-render LCD to match current state."""
        sm = state_manager
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
            await loop.run_in_executor(None, lcd.display, "\u26a0\ufe0f", "System Failure", True)
        elif state == ReaderState.LOCALLY_DISABLED:
            await loop.run_in_executor(None, lcd.display, "\u26a0\ufe0f", "Reader Disabled", True)

    @app.post("/action/force-reconnect")
    async def action_force_reconnect(request: Request):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        logger.info("dashboard_force_reconnect")
        state_manager.reconnect_attempts = 0
        if state_manager.state != ReaderState.LOCALLY_DISABLED:
            await state_manager.async_transition(ReaderState.SYSTEM_FAILURE, "dashboard force reconnect")
        return {"ok": True}

    # ------------------------------------------------------------------
    # Debug page
    # ------------------------------------------------------------------

    @app.get("/debug", response_class=HTMLResponse)
    async def debug_page(request: Request):
        if not _is_authenticated(request):
            return RedirectResponse(url="/login", status_code=303)
        sm = state_manager
        context = {
            "state": sm.state.value,
            "reader_number": sm.reader_number,
            "ws_connected": sm.ws_connected,
            "scan_in_progress": sm.state in (ReaderState.READING, ReaderState.AWAITING_RESULT),
            "last_uid": sm.last_uid,
        }
        return templates.TemplateResponse(request, "debug.html", context)

    @app.get("/debug/state")
    async def debug_state(request: Request):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        sm = state_manager
        return {
            "state": sm.state.value,
            "reader_number": sm.reader_number,
            "ws_connected": sm.ws_connected,
            "last_uid": sm.last_uid,
            "reconnect_attempts": sm.reconnect_attempts,
            "uptime_seconds": round(sm.uptime_seconds, 1),
            "locally_disabled": sm.locally_disabled,
        }

    @app.post("/debug/read-uid")
    async def debug_read_uid(request: Request):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if state_manager.state in (ReaderState.READING, ReaderState.AWAITING_RESULT):
            raise HTTPException(status_code=409, detail="Scan in progress — cannot use debug read")
        loop = asyncio.get_event_loop()
        uid = await loop.run_in_executor(None, rc522.read_once)
        logger.info("debug_read_uid", f"uid={uid}")
        return {"uid": uid}

    @app.post("/debug/simulate")
    async def debug_simulate(request: Request, body: dict[str, Any] = None):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
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
            if state_manager.state in (ReaderState.READING, ReaderState.AWAITING_RESULT):
                raise HTTPException(status_code=409, detail="Scan in progress")
            await on_read(ReadMessage(type="read"))
        elif msg_type == "result":
            status = body.get("status", "success")
            item_id = body.get("item_id")
            await on_result(ResultMessage(type="result", status=status, item_id=item_id))
        elif msg_type == "system_failure":
            await state_manager.async_transition(ReaderState.SYSTEM_FAILURE, "debug simulate")
        else:
            raise HTTPException(status_code=400, detail=f"Unknown simulate type: {msg_type}")

        return {"ok": True}

    @app.post("/debug/buzzer-tone")
    async def debug_buzzer_tone(request: Request):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        body = await request.json()
        freq = int(body.get("freq", 1000))
        duration = float(body.get("duration", 0.3))
        logger.info("debug_buzzer_tone", f"freq={freq} duration={duration}")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, buzzer.beep, freq, duration)
        return {"ok": True}

    @app.post("/debug/lcd-custom")
    async def debug_lcd_custom(request: Request):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        body = await request.json()
        line1 = str(body.get("line1", ""))
        line2 = str(body.get("line2", ""))
        logger.info("debug_lcd_custom", f"line1={line1!r} line2={line2!r}")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lcd.display, line1, line2, True)
        return {"ok": True}

    return app
