# WebSocket Protocol

Universal Reader connects to an **Inventory server** over a persistent WebSocket
connection.  This document describes every message exchanged over that connection.

---

## Connection lifecycle

```
Reader                          Inventory Server
  │── connect ──────────────────────────────────▶│
  │◀─ HTTP 101 Switching Protocols ──────────────│
  │                                              │
  │── {"type":"register","api_key":"..."} ──────▶│
  │◀─ {"type":"registered","reader_number":1} ───│
  │                                              │
  │   … normal operation …                       │
  │                                              │
  │◀─ {"type":"ping"} ───────────────────────────│
  │── {"type":"pong"} ──────────────────────────▶│
  │                                              │
  │── (disconnect / reconnect) ─────────────────▶│
```

On every (re)connect the reader sends `register` immediately.  
The server responds with `registered` to confirm the connection and assign a
reader number.

---

## Messages — Inventory → Reader

### `activate`

Instructs the reader to enter **ACTIVE** state and start an activation timer.

```json
{
  "type": "activate",
  "timeout_seconds": 30
}
```

| Field | Type | Description |
|-------|------|-------------|
| `timeout_seconds` | int | How long to stay active.  `0` = no automatic hibernation. |

---

### `deactivate`

Returns the reader to **HIBERNATED** state.

```json
{ "type": "deactivate" }
```

---

### `read`

Requests the reader to scan a tag (enters **READING** state).

```json
{ "type": "read" }
```

---

### `result`

Delivers the lookup result after a tag was scanned.  Transitions back to **ACTIVE**.

```json
{
  "type": "result",
  "status": "success",
  "item_id": "R-0042"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `success`, `not_found`, `network_error`, or `retry` |
| `item_id` | string \| null | Item identifier (only present when `status` is `success`) |

---

### `ping`

Keep-alive probe.  The reader must reply with `pong` immediately.

```json
{ "type": "ping" }
```

---

## Messages — Reader → Inventory

### `register`

Sent immediately after connecting to authenticate and register the reader.

```json
{
  "type": "register",
  "api_key": "your-secret-key"
}
```

---

### `uid_scanned`

Sent when the RC522 reads a tag while in **READING** state.

```json
{
  "type": "uid_scanned",
  "uid": "A3F201CC"
}
```

---

### `pong`

Reply to a `ping` keep-alive.

```json
{ "type": "pong" }
```

---

### `error`

Sent when the reader rejects a command (e.g. a `read` arrives while a scan
is already in progress).

```json
{
  "type": "error",
  "reason": "scan_in_progress"
}
```

---

### `status`

Sent proactively to report state changes (optional — used for server-side
monitoring).

```json
{
  "type": "status",
  "state": "READING"
}
```

---

## Reader states

```
         ┌──────────────────────────────────────────────┐
         │                                              │
         ▼                                              │
    HIBERNATED ──── activate ────▶ ACTIVE ──── read ────▶ READING
         ▲                         │    ▲                    │
         │                         │    │                    │
         └──── deactivate ──────────┘    │             tag scanned
         │                               │                    │
         │                               │                    ▼
         │                               └────── result ── AWAITING_RESULT
         │
    SYSTEM_FAILURE  (auto-recovers when WS reconnects)
    LOCALLY_DISABLED  (dashboard disable; ignores all Inventory messages)
```

| State | Description |
|-------|-------------|
| `HIBERNATED` | Idle; LCD off; waiting for `activate` |
| `ACTIVE` | Ready to scan; waiting for `read` |
| `READING` | RC522 is scanning; waiting for a tag |
| `AWAITING_RESULT` | Tag scanned; UID sent; waiting for `result` |
| `SYSTEM_FAILURE` | WebSocket disconnected; reconnecting |
| `LOCALLY_DISABLED` | Manually disabled via dashboard; ignores WS |

---

## Reconnection behaviour

When the WebSocket drops:

1. The reader transitions to `SYSTEM_FAILURE`.
2. The reconnect loop retries with a short delay for the first 3 attempts
   (10 s each), then falls back to a 60-second interval.
3. On successful re-registration, the reader restores its previous state
   (e.g. `ACTIVE` with the default 30-second timeout).

You can reset the retry counter and force an immediate reconnect via
`POST /api/v1/reader/reconnect`.

---

## Implementing a compatible Inventory server

A minimal Python example using FastAPI + websockets:

```python
from fastapi import FastAPI, WebSocket

app = FastAPI()

@app.websocket("/ws/reader")
async def reader_ws(ws: WebSocket):
    await ws.accept()

    # Expect register message
    msg = await ws.receive_json()
    assert msg["type"] == "register"
    assert msg["api_key"] == "your-secret-key"

    # Assign a reader number
    await ws.send_json({"type": "registered", "reader_number": 1})

    # Activate the reader for 60 seconds
    await ws.send_json({"type": "activate", "timeout_seconds": 60})

    # Request a scan
    await ws.send_json({"type": "read"})

    # Wait for the UID
    scan = await ws.receive_json()
    assert scan["type"] == "uid_scanned"
    uid = scan["uid"]
    print(f"Scanned: {uid}")

    # Return a result
    await ws.send_json({"type": "result", "status": "success", "item_id": "R-0001"})
```
