"""Pydantic models for all structured data in the Universal Reader."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class ReaderState(str, Enum):
    HIBERNATED = "HIBERNATED"
    ACTIVE = "ACTIVE"
    READING = "READING"
    AWAITING_RESULT = "AWAITING_RESULT"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"
    LOCALLY_DISABLED = "LOCALLY_DISABLED"


# ---------------------------------------------------------------------------
# WebSocket messages — Inventory → Reader
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
# WebSocket messages — Reader → Inventory
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
# Configuration
# ---------------------------------------------------------------------------


class HardwareConfig(BaseModel):
    lcd_i2c_addr: int = 0x27
    buzzer_pin: int = 18
    rc522_miso: int = 9
    rc522_mosi: int = 10
    rc522_sck: int = 11
    rc522_sda: int = 8
    rc522_rst: int = 25


class AppConfig(BaseModel):
    inventory_ws_url: str
    inventory_api_key: str
    dashboard_password: str
    dashboard_port: int = 5050
    hardware: HardwareConfig = Field(default_factory=HardwareConfig)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class LogEntry(BaseModel):
    timestamp: datetime
    level: Literal["VERBOSE", "INFO", "WARN", "ERROR"]
    event: str
    detail: str | None = None


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------


class ReaderStatus(BaseModel):
    state: str
    reader_number: int | None
    ws_connected: bool
    uptime_seconds: float
    last_scan: datetime | None
    locally_disabled: bool


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
