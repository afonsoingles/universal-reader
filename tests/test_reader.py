"""Tests for the Universal Reader."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from reader.models import (
    ActivateMessage,
    AppConfig,
    DeactivateMessage,
    ErrorMessage,
    HardwareConfig,
    LogEntry,
    PingMessage,
    PongMessage,
    ReadMessage,
    ReaderState,
    ReaderStatus,
    RegisteredMessage,
    RegisterMessage,
    ResultMessage,
    StatusMessage,
    UidScannedMessage,
)
from reader.state import StateManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(**kwargs) -> AppConfig:
    defaults = dict(
        inventory_ws_url="ws://localhost:9999/ws",
        inventory_api_key="test-key",
        dashboard_password="testpass",
    )
    defaults.update(kwargs)
    return AppConfig(**defaults)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_reader_state_enum(self):
        assert ReaderState.HIBERNATED == "HIBERNATED"
        assert ReaderState.ACTIVE == "ACTIVE"
        assert ReaderState.READING == "READING"
        assert ReaderState.AWAITING_RESULT == "AWAITING_RESULT"
        assert ReaderState.SYSTEM_FAILURE == "SYSTEM_FAILURE"
        assert ReaderState.LOCALLY_DISABLED == "LOCALLY_DISABLED"

    def test_activate_message(self):
        msg = ActivateMessage(type="activate", timeout_seconds=30)
        assert msg.type == "activate"
        assert msg.timeout_seconds == 30

    def test_result_message_success(self):
        msg = ResultMessage(type="result", status="success", item_id="R-0042")
        assert msg.status == "success"
        assert msg.item_id == "R-0042"

    def test_result_message_not_found(self):
        msg = ResultMessage(type="result", status="not_found")
        assert msg.item_id is None

    def test_register_message_default_type(self):
        msg = RegisterMessage(api_key="key123")
        assert msg.type == "register"
        assert msg.api_key == "key123"

    def test_uid_scanned_message(self):
        msg = UidScannedMessage(uid="A3F201CC")
        assert msg.uid == "A3F201CC"
        assert msg.type == "uid_scanned"

    def test_error_message(self):
        msg = ErrorMessage(reason="scan_in_progress")
        assert msg.type == "error"
        assert msg.reason == "scan_in_progress"

    def test_pong_message(self):
        msg = PongMessage()
        assert msg.type == "pong"

    def test_log_entry(self):
        ts = datetime.now(tz=timezone.utc)
        entry = LogEntry(timestamp=ts, level="INFO", event="test_event", detail="some detail")
        assert entry.level == "INFO"
        assert entry.event == "test_event"

    def test_hardware_config_defaults(self):
        hw = HardwareConfig()
        assert hw.lcd_i2c_addr == 0x27
        assert hw.buzzer_pin == 18
        assert hw.rc522_sda == 8
        assert hw.rc522_rst == 25

    def test_reader_status(self):
        status = ReaderStatus(
            state="ACTIVE",
            reader_number=2,
            ws_connected=True,
            uptime_seconds=100.0,
            last_scan=None,
            locally_disabled=False,
        )
        assert status.state == "ACTIVE"
        assert status.reader_number == 2

    def test_app_config(self):
        cfg = make_config()
        assert cfg.dashboard_port == 5050
        assert isinstance(cfg.hardware, HardwareConfig)


# ---------------------------------------------------------------------------
# State machine tests
# ---------------------------------------------------------------------------


class TestStateMachine:
    def test_initial_state(self):
        sm = StateManager()
        assert sm.state == ReaderState.HIBERNATED

    def test_hibernated_to_active(self):
        sm = StateManager()
        assert sm.transition(ReaderState.ACTIVE)
        assert sm.state == ReaderState.ACTIVE

    def test_full_happy_path(self):
        sm = StateManager()
        sm.transition(ReaderState.ACTIVE)
        sm.transition(ReaderState.READING)
        sm.transition(ReaderState.AWAITING_RESULT)
        sm.transition(ReaderState.ACTIVE)
        assert sm.state == ReaderState.ACTIVE

    def test_deactivate_from_active(self):
        sm = StateManager()
        sm.transition(ReaderState.ACTIVE)
        assert sm.transition(ReaderState.HIBERNATED)
        assert sm.state == ReaderState.HIBERNATED

    def test_invalid_transition_blocked(self):
        sm = StateManager()
        # HIBERNATED cannot go directly to READING
        assert not sm.transition(ReaderState.READING)
        assert sm.state == ReaderState.HIBERNATED

    def test_system_failure_from_hibernated(self):
        sm = StateManager()
        assert sm.transition(ReaderState.SYSTEM_FAILURE)

    def test_system_failure_from_active(self):
        sm = StateManager()
        sm.transition(ReaderState.ACTIVE)
        assert sm.transition(ReaderState.SYSTEM_FAILURE)

    def test_system_failure_from_locally_disabled(self):
        sm = StateManager()
        sm.transition(ReaderState.ACTIVE)
        sm.transition(ReaderState.LOCALLY_DISABLED)
        assert sm.transition(ReaderState.SYSTEM_FAILURE)

    def test_locally_disabled_ignores_state(self):
        sm = StateManager()
        sm.transition(ReaderState.ACTIVE)
        sm.transition(ReaderState.LOCALLY_DISABLED)
        assert sm.state == ReaderState.LOCALLY_DISABLED
        # Only ACTIVE can re-enable
        assert sm.transition(ReaderState.ACTIVE)
        assert sm.state == ReaderState.ACTIVE

    def test_locally_disabled_cannot_go_to_reading(self):
        sm = StateManager()
        sm.transition(ReaderState.ACTIVE)
        sm.transition(ReaderState.LOCALLY_DISABLED)
        # Cannot go LOCALLY_DISABLED → READING
        assert not sm.transition(ReaderState.READING)

    def test_invalid_active_to_awaiting_result(self):
        sm = StateManager()
        sm.transition(ReaderState.ACTIVE)
        # ACTIVE → AWAITING_RESULT is invalid
        assert not sm.transition(ReaderState.AWAITING_RESULT)

    def test_pre_failure_state_saved(self):
        sm = StateManager()
        sm.transition(ReaderState.ACTIVE)
        assert sm.pre_failure_state == ReaderState.HIBERNATED  # default
        sm.transition(ReaderState.SYSTEM_FAILURE)
        assert sm.pre_failure_state == ReaderState.ACTIVE

    def test_record_scan(self):
        sm = StateManager()
        assert sm.last_scan is None
        sm.record_scan("AABBCCDD")
        assert sm.last_scan is not None
        assert sm.last_uid == "AABBCCDD"

    def test_locally_disabled_property(self):
        sm = StateManager()
        assert not sm.locally_disabled
        sm.transition(ReaderState.ACTIVE)
        sm.transition(ReaderState.LOCALLY_DISABLED)
        assert sm.locally_disabled

    def test_uptime_positive(self):
        sm = StateManager()
        assert sm.uptime_seconds >= 0

    @pytest.mark.asyncio
    async def test_async_transition(self):
        sm = StateManager()
        result = await sm.async_transition(ReaderState.ACTIVE)
        assert result is True
        assert sm.state == ReaderState.ACTIVE

    @pytest.mark.asyncio
    async def test_async_transition_callback(self):
        sm = StateManager()
        events = []

        async def cb(old, new):
            events.append((old, new))

        sm.register_state_change_callback(cb)
        await sm.async_transition(ReaderState.ACTIVE)
        assert len(events) == 1
        assert events[0] == (ReaderState.HIBERNATED, ReaderState.ACTIVE)


# ---------------------------------------------------------------------------
# Logger tests
# ---------------------------------------------------------------------------


class TestLogger:
    def setup_method(self):
        import reader.logger as log

        log.clear()
        self.log = log

    def test_info_log(self):
        self.log.info("test_event", "some detail")
        entries = self.log.get_entries()
        assert len(entries) == 1
        assert entries[0].level == "INFO"
        assert entries[0].event == "test_event"
        assert entries[0].detail == "some detail"

    def test_warn_log(self):
        self.log.warn("warn_event")
        entries = self.log.get_entries()
        assert entries[0].level == "WARN"

    def test_error_log(self):
        self.log.error("error_event")
        entries = self.log.get_entries()
        assert entries[0].level == "ERROR"

    def test_clear(self):
        self.log.info("x")
        self.log.clear()
        assert len(self.log.get_entries()) == 0

    def test_max_500_entries(self):
        for i in range(600):
            self.log.info(f"event_{i}")
        entries = self.log.get_entries()
        assert len(entries) == 500
        # Should contain the last 500 (FIFO)
        assert entries[-1].event == "event_599"

    def test_log_entry_has_timestamp(self):
        self.log.info("ts_test")
        e = self.log.get_entries()[0]
        assert isinstance(e.timestamp, datetime)
        assert e.timestamp.tzinfo is not None


# ---------------------------------------------------------------------------
# LCD helper tests
# ---------------------------------------------------------------------------


class TestLCDHelper:
    def test_center_short(self):
        from reader.hardware.lcd import center

        result = center("Hi")
        assert len(result) == 16
        assert result.strip() == "Hi"

    def test_center_exact(self):
        from reader.hardware.lcd import center

        result = center("Universal Reader")
        assert result == "Universal Reader"

    def test_center_truncates_long(self):
        from reader.hardware.lcd import center

        result = center("This is way too long for 16 cols")
        assert len(result) == 16

    def test_center_empty(self):
        from reader.hardware.lcd import center

        result = center("")
        assert len(result) == 16
        assert result.strip() == ""


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfig:
    def test_default_hardware_config(self):
        cfg = make_config()
        assert cfg.hardware.lcd_i2c_addr == 0x27
        assert cfg.hardware.buzzer_pin == 18

    def test_custom_hardware_config(self):
        AppConfig(
            inventory_ws_url="ws://test",
            inventory_api_key="k",
            dashboard_password="p",
            hardware=HardwareConfig(buzzer_pin=22, lcd_i2c_addr=0x3F),
        )
        cfg2 = AppConfig(
            inventory_ws_url="ws://test",
            inventory_api_key="k",
            dashboard_password="p",
            hardware=HardwareConfig(buzzer_pin=22, lcd_i2c_addr=0x3F),
        )
        assert cfg2.hardware.buzzer_pin == 22
        assert cfg2.hardware.lcd_i2c_addr == 0x3F


# ---------------------------------------------------------------------------
# Dashboard / API tests
# ---------------------------------------------------------------------------


class MockBuzzer:
    def beep(self, *a):
        pass

    def reading_start(self):
        pass

    def result_success(self):
        pass

    def result_error(self):
        pass

    def beep_sequence(self, *a):
        pass


class MockLCD:
    def display(self, *a):
        pass

    def off(self):
        pass


class MockRC522:
    def read_once(self):
        return "AABBCCDD"


async def _noop(*a, **kw):
    pass


@pytest.fixture
def app_and_sm():
    from reader.dashboard.app import create_app

    import reader.logger as log

    log.clear()

    sm = StateManager()
    cfg = make_config()

    async def _on_activate(msg):
        await sm.async_transition(ReaderState.ACTIVE, "activate")

    async def _on_deactivate(msg):
        await sm.async_transition(ReaderState.HIBERNATED, "deactivate")

    async def _on_read(msg):
        await sm.async_transition(ReaderState.READING, "read")

    async def _on_result(msg):
        await sm.async_transition(ReaderState.ACTIVE, "result")

    app = create_app(
        sm,
        cfg,
        None,
        _on_activate,
        _on_deactivate,
        _on_read,
        _on_result,
        MockBuzzer(),
        MockLCD(),
        MockRC522(),
    )
    return app, sm


@pytest.fixture
def client(app_and_sm):
    app, sm = app_and_sm
    return TestClient(app, raise_server_exceptions=True), sm


class TestDashboardAPI:
    def test_status_endpoint(self, client):
        c, sm = client
        r = c.get("/status")
        assert r.status_code == 200
        data = r.json()
        assert data["state"] == "HIBERNATED"
        assert data["ws_connected"] is False
        assert data["locally_disabled"] is False

    def test_login_page_accessible(self, client):
        c, _ = client
        r = c.get("/login")
        assert r.status_code == 200
        assert "password" in r.text.lower()

    def test_login_wrong_password(self, client):
        c, _ = client
        r = c.post("/login", data={"password": "wrong"})
        assert r.status_code == 401

    def test_login_correct_password(self, client):
        c, _ = client
        r = c.post("/login", data={"password": "testpass"}, follow_redirects=False)
        assert r.status_code == 303
        assert "session" in r.cookies

    def test_dashboard_requires_auth(self, client):
        c, _ = client
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

    def test_logs_requires_auth(self, client):
        c, _ = client
        r = c.get("/logs")
        assert r.status_code == 401

    def test_logs_with_auth(self, client):
        c, _ = client
        # Login
        c.post("/login", data={"password": "testpass"})
        r = c.get("/logs")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_action_disable_requires_auth(self, client):
        c, _ = client
        r = c.post("/action/disable")
        assert r.status_code == 401

    def test_action_disable_with_auth(self, client):
        c, sm = client
        sm.transition(ReaderState.ACTIVE)
        c.post("/login", data={"password": "testpass"})
        r = c.post("/action/disable")
        assert r.status_code == 200
        assert sm.state == ReaderState.LOCALLY_DISABLED

    def test_action_enable_only_when_disabled(self, client):
        c, sm = client
        sm.transition(ReaderState.ACTIVE)
        c.post("/login", data={"password": "testpass"})
        # Can't enable when not disabled
        r = c.post("/action/enable")
        assert r.status_code == 400

    def test_action_enable_from_disabled(self, client):
        c, sm = client
        sm.transition(ReaderState.ACTIVE)
        sm.transition(ReaderState.LOCALLY_DISABLED)
        c.post("/login", data={"password": "testpass"})
        r = c.post("/action/enable")
        assert r.status_code == 200
        assert sm.state == ReaderState.ACTIVE

    def test_debug_state_endpoint(self, client):
        c, sm = client
        c.post("/login", data={"password": "testpass"})
        r = c.get("/debug/state")
        assert r.status_code == 200
        data = r.json()
        assert "state" in data
        assert "ws_connected" in data
        assert "uptime_seconds" in data

    def test_simulate_endpoint_activate(self, client):
        c, sm = client
        c.post("/login", data={"password": "testpass"})
        r = c.post(
            "/debug/simulate",
            json={"type": "activate", "timeout_seconds": 60},
        )
        assert r.status_code == 200
        assert sm.state == ReaderState.ACTIVE

    def test_simulate_endpoint_deactivate(self, client):
        c, sm = client
        sm.transition(ReaderState.ACTIVE)
        c.post("/login", data={"password": "testpass"})
        r = c.post("/debug/simulate", json={"type": "deactivate"})
        assert r.status_code == 200

    def test_simulate_unknown_type(self, client):
        c, _ = client
        c.post("/login", data={"password": "testpass"})
        r = c.post("/debug/simulate", json={"type": "unknown_xyz"})
        assert r.status_code == 400

    def test_clear_logs(self, client):
        c, _ = client
        import reader.logger as log

        log.info("test")
        c.post("/login", data={"password": "testpass"})
        r = c.post("/logs/clear")
        assert r.status_code == 200
        # After clearing, there should only be the "dashboard_logs_cleared" entry
        entries = log.get_entries()
        assert all(e.event == "dashboard_logs_cleared" for e in entries)

    def test_debug_read_uid(self, client):
        c, sm = client
        sm.transition(ReaderState.ACTIVE)
        c.post("/login", data={"password": "testpass"})
        r = c.post("/debug/read-uid")
        assert r.status_code == 200
        data = r.json()
        assert "uid" in data

    def test_debug_read_uid_blocked_during_scan(self, client):
        c, sm = client
        sm.transition(ReaderState.ACTIVE)
        sm.transition(ReaderState.READING)
        c.post("/login", data={"password": "testpass"})
        r = c.post("/debug/read-uid")
        assert r.status_code == 409
