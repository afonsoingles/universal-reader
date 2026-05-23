"""Session management for the dashboard.

Stores active sessions in an in-memory cache with a configurable TTL so
that multiple browser tabs / devices can be logged in simultaneously and
sessions expire automatically without requiring a server restart.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

# PBKDF2 iterations — computationally expensive to deter brute-force
_PBKDF2_ITERATIONS = 260_000
# Per-process salt generated at startup (not persisted across restarts)
_PBKDF2_SALT: bytes = os.urandom(16)


def hash_password(password: str) -> str:
    """Hash *password* with PBKDF2-HMAC-SHA256 using the module-level salt."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        _PBKDF2_SALT,
        _PBKDF2_ITERATIONS,
    ).hex()


# ---------------------------------------------------------------------------
# Session cache
# ---------------------------------------------------------------------------

# Default session lifetime: 8 hours
SESSION_TTL_SECONDS: int = 8 * 3600

# {token: expires_at (Unix timestamp)}
_sessions: dict[str, float] = {}


def create_session() -> str:
    """Generate a new session token, cache it, and return the token string."""
    token = secrets.token_hex(32)
    _sessions[token] = time.time() + SESSION_TTL_SECONDS
    return token


def is_valid_session(token: str | None) -> bool:
    """Return True if *token* is present in the cache and has not expired."""
    if not token:
        return False
    expires_at = _sessions.get(token)
    if expires_at is None:
        return False
    if time.time() > expires_at:
        _sessions.pop(token, None)
        return False
    return True


def invalidate_session(token: str | None) -> None:
    """Remove *token* from the session cache (logout)."""
    if token:
        _sessions.pop(token, None)
