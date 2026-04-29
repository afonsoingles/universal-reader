"""FastAPI dependency helpers for the dashboard.

All shared objects (state manager, hardware, handlers) are stored on
``app.state`` by the factory in ``dashboard/app.py`` and retrieved here
via ``Request``.  This keeps routers free of global mutable state while
still providing easy access to every shared resource.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from reader.dashboard.auth import is_valid_session
from reader.state import StateManager


def get_sm(request: Request) -> StateManager:
    """Return the shared :class:`StateManager` instance."""
    return request.app.state.sm


def is_authenticated(request: Request) -> bool:
    """Return True if the request carries a valid session cookie."""
    token = request.cookies.get("session")
    return is_valid_session(token)


def require_auth(request: Request) -> None:
    """Raise HTTP 401 if the request is not authenticated.

    Use as a FastAPI dependency on JSON API endpoints.
    """
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_auth_redirect(request: Request) -> None:
    """Raise HTTP 303 redirect to ``/login`` if not authenticated.

    Use as a FastAPI dependency on HTML page endpoints.
    """
    if not is_authenticated(request):
        raise HTTPException(status_code=303, headers={"Location": "/login"})
