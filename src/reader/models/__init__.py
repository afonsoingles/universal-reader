"""Models package — re-exports all models for backward compatibility."""

from __future__ import annotations

from reader.models.api import LogEntry, ReaderStatus
from reader.models.config import AppConfig, HardwareConfig
from reader.models.state import ReaderState
from reader.models.websocket import (
    ActivateMessage,
    DeactivateMessage,
    ErrorMessage,
    InboundMessage,
    PingMessage,
    PongMessage,
    ReadMessage,
    RegisteredMessage,
    RegisterMessage,
    ResultMessage,
    StatusMessage,
    UidScannedMessage,
)

__all__ = [
    # state
    "ReaderState",
    # websocket
    "ActivateMessage",
    "DeactivateMessage",
    "ReadMessage",
    "ResultMessage",
    "PingMessage",
    "RegisteredMessage",
    "RegisterMessage",
    "UidScannedMessage",
    "ErrorMessage",
    "StatusMessage",
    "PongMessage",
    "InboundMessage",
    # config
    "HardwareConfig",
    "AppConfig",
    # api
    "LogEntry",
    "ReaderStatus",
]
