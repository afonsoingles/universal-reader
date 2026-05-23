# REST API Reference

All REST endpoints are served under the `/api/v1/` prefix.

**Authentication**: All endpoints except `GET /api/v1/status` require a
valid session cookie obtained by logging in via `POST /login`.  Unauthenticated
requests receive **HTTP 401 Unauthorized**.

---

## Status

### `GET /api/v1/status`

Returns the current reader status.  **No authentication required.**

**Response** `200 OK`

```json
{
  "state": "ACTIVE",
  "reader_number": 1,
  "ws_connected": true,
  "uptime_seconds": 142.3,
  "last_scan": "2024-11-15T09:42:00Z",
  "locally_disabled": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `state` | string | Current reader state (see [WebSocket docs](websocket.md#reader-states)) |
| `reader_number` | int \| null | Reader number assigned by the Inventory server |
| `ws_connected` | bool | Whether the WebSocket connection is up |
| `uptime_seconds` | float | Seconds since the process started |
| `last_scan` | ISO-8601 \| null | Timestamp of the last successful tag scan |
| `locally_disabled` | bool | True when the reader is in LOCALLY_DISABLED state |

---

## Logs

### `GET /api/v1/logs`

Return structured in-memory log entries.

**Query parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `level` | string (repeatable) | Filter by log level: `VERBOSE`, `INFO`, `WARN`, `ERROR` |

**Example** — fetch only warnings and errors:

```
GET /api/v1/logs?level=WARN&level=ERROR
```

**Response** `200 OK` — array of log entry objects:

```json
[
  {
    "timestamp": "2024-11-15T09:42:00.123Z",
    "level": "INFO",
    "event": "ws_connected",
    "detail": "ws://192.168.1.100:8000/ws/reader"
  }
]
```

---

### `DELETE /api/v1/logs`

Clear all in-memory log entries.

**Response** `200 OK`

```json
{ "ok": true }
```

---

## Reader Actions

### `POST /api/v1/reader/disable`

Locally disable the reader.  While disabled, all Inventory WebSocket messages
are ignored.

**Response** `200 OK` `{ "ok": true }`

---

### `POST /api/v1/reader/enable`

Re-enable a locally disabled reader, transitioning it back to `ACTIVE`.

**Response** `200 OK` `{ "ok": true }`  
**Error** `400 Bad Request` — if the reader is not currently disabled.

---

### `POST /api/v1/reader/reconnect`

Force a WebSocket reconnect by transitioning to `SYSTEM_FAILURE`.  The
reconnect loop will immediately attempt to re-establish the connection.

**Response** `200 OK` `{ "ok": true }`

---

## Hardware

### `GET /api/v1/hardware`

Return hardware availability for each component.

**Response** `200 OK`

```json
{
  "lcd":    { "available": true  },
  "buzzer": { "available": true  },
  "rc522":  { "available": false }
}
```

---

### `POST /api/v1/hardware/buzzer/test`

Run a multi-tone buzzer self-test sequence asynchronously
(`reading_start` → `result_success` → `result_error`).

**Response** `200 OK` `{ "ok": true }`

---

### `POST /api/v1/hardware/lcd/test`

Display a test pattern on the LCD for 3 seconds, then restore the
current state display.

**Response** `200 OK` `{ "ok": true }`

---

## Debug

> **Note**: Debug endpoints are intended for development only. They provide
> direct access to internal state and hardware that bypasses normal safety
> checks.

### `GET /api/v1/debug/state`

Return a verbose snapshot of internal reader state.

**Response** `200 OK`

```json
{
  "state": "HIBERNATED",
  "reader_number": null,
  "ws_connected": false,
  "last_uid": "A3F201CC",
  "reconnect_attempts": 0,
  "uptime_seconds": 12.5,
  "locally_disabled": false
}
```

---

### `POST /api/v1/debug/uid`

Read a single UID directly from the RC522 without going through the state
machine.  Cannot be used while a scan is already in progress.

**Response** `200 OK`

```json
{ "uid": "A3F201CC" }
```

**Error** `409 Conflict` — scan already in progress.

---

### `POST /api/v1/debug/simulate`

Inject a simulated Inventory WebSocket message into the message handler.

**Request body**

```json
{ "type": "activate", "timeout_seconds": 30 }
```

Supported `type` values:

| Type | Extra fields | Effect |
|------|-------------|--------|
| `activate` | `timeout_seconds: int` | Transitions to ACTIVE |
| `deactivate` | — | Transitions to HIBERNATED |
| `read` | — | Transitions to READING |
| `result` | `status`, `item_id?` | Handles scan result |
| `uid_scanned` | `uid: str` | Simulates a tag scan (requires READING state) |
| `system_failure` | — | Forces SYSTEM_FAILURE |

**Response** `200 OK` `{ "ok": true }`

---

### `POST /api/v1/debug/buzzer/tone`

Play a single custom buzzer tone.

**Request body**

```json
{ "freq": 1000, "duration": 0.3 }
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `freq` | int | `1000` | Frequency in Hz |
| `duration` | float | `0.3` | Duration in seconds |

**Response** `200 OK` `{ "ok": true }`

---

### `POST /api/v1/debug/buzzer/pattern`

Play a named buzzer pattern.

**Request body**

```json
{ "pattern": "result_success" }
```

Valid patterns: `reading_start`, `result_success`, `result_error`.

**Response** `200 OK` `{ "ok": true }`  
**Error** `400 Bad Request` — unknown pattern name.

---

### `POST /api/v1/debug/lcd`

Write custom text to both lines of the LCD.

**Request body**

```json
{ "line1": "Universal", "line2": "Reader" }
```

Both values are truncated to 16 characters.

**Response** `200 OK` `{ "ok": true }`

---

## Authentication

### `POST /login`

Authenticate with the dashboard password.

**Form fields**

| Field | Description |
|-------|-------------|
| `password` | The `DASHBOARD_PASSWORD` from `.env` |

**Response** `303 Redirect` to `/` on success (sets `session` cookie).  
**Response** `401 Unauthorized` on failure.

---

### `GET /logout`

Invalidate the current session and redirect to `/login`.

**Response** `303 Redirect` to `/login`.
