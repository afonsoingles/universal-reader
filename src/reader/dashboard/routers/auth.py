"""Authentication routes — /login and /logout."""

from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from reader import logger
from reader.dashboard.auth import (
    create_session,
    hash_password,
    invalidate_session,
)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login_post(request: Request, password: str = Form(...)):
    pw_hash = request.app.state.pw_hash
    if hmac.compare_digest(hash_password(password), pw_hash):
        token = create_session()
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie("session", token, httponly=True, samesite="strict")
        logger.info("dashboard_login", request.client.host if request.client else "unknown")
        return response
    return templates.TemplateResponse(
        request, "login.html", {"error": "Invalid password"}, status_code=401
    )


@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session")
    invalidate_session(token)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session")
    return response
