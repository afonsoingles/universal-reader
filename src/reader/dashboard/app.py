"""FastAPI dashboard application factory for the Universal Reader.

The factory stores all shared objects on ``app.state`` so that routers can
access them through ``request.app.state`` without requiring a global or
closure-based injection.

HTML pages (``/`` and ``/debug``) live here.  All REST API endpoints are
served via the routers in ``dashboard/routers/``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from reader.dashboard.auth import hash_password, is_valid_session
from reader.dashboard.deps import is_authenticated
from reader.dashboard.routers.api import router as api_router
from reader.dashboard.routers.auth import router as auth_router
from reader.models import ReaderState
from reader.state import StateManager

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


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
    """Create and configure the dashboard FastAPI application."""
    app = FastAPI(title="Universal Reader Dashboard", docs_url=None, redoc_url=None)

    # ------------------------------------------------------------------
    # Store shared objects on app.state for use in routers / deps
    # ------------------------------------------------------------------
    app.state.sm = state_manager
    app.state.config = config
    app.state.ws_client = ws_client
    app.state.buzzer = buzzer
    app.state.lcd = lcd
    app.state.rc522 = rc522
    app.state.on_activate = on_activate
    app.state.on_deactivate = on_deactivate
    app.state.on_read = on_read
    app.state.on_result = on_result
    # Pre-compute hashed password once at startup
    app.state.pw_hash = hash_password(config.dashboard_password)

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    app.include_router(auth_router)
    app.include_router(api_router)

    # ------------------------------------------------------------------
    # HTML page routes
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if not is_authenticated(request):
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

    @app.get("/debug", response_class=HTMLResponse)
    async def debug_page(request: Request):
        if not is_authenticated(request):
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

    return app
