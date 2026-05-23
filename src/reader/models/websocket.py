"""WebSocket message models — both inbound (Inventory → Reader) and outbound (Reader → Inventory)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Inbound — Inventory → Reader
# ---------------------------------------------------------------------------


class ActivateMessage(BaseModel):
    type: Literal["activate"]
    timeout_seconds: int


class DeactivateMessage(BaseModel):
    type: Literal["deactivate"]


class ReadMessage(BaseModel):
    type: Literal["read"]


class ResultMessage(BaseModel):
    type: Literal["result"]
    status: Literal["success", "not_found", "network_error", "retry"]
    item_id: str | None = None  # only on success


class PingMessage(BaseModel):
    type: Literal["ping"]


class RegisteredMessage(BaseModel):
    type: Literal["registered"]
    reader_number: int


# ---------------------------------------------------------------------------
# Outbound — Reader → Inventory
# ---------------------------------------------------------------------------


class RegisterMessage(BaseModel):
    type: Literal["register"] = "register"
    api_key: str


class UidScannedMessage(BaseModel):
    type: Literal["uid_scanned"] = "uid_scanned"
    uid: str


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    reason: str


class StatusMessage(BaseModel):
    type: Literal["status"] = "status"
    state: str


class PongMessage(BaseModel):
    type: Literal["pong"] = "pong"


# ---------------------------------------------------------------------------
# Inbound message union (for dispatching)
# ---------------------------------------------------------------------------

InboundMessage = Annotated[
    ActivateMessage
    | DeactivateMessage
    | ReadMessage
    | ResultMessage
    | PingMessage
    | RegisteredMessage,
    Field(discriminator="type"),
]
