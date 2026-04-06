# Universal Reader

A Raspberry Pi Zero W 2 application that bridges an RC522 RFID/NFC reader to an Inventory management server over WebSocket, with a 16×2 I²C LCD display, passive buzzer feedback, and a local web dashboard.

---

## Table of Contents

- [Hardware Requirements](#hardware-requirements)
- [Hardware Wiring](#hardware-wiring)
- [Raspberry Pi OS Setup](#raspberry-pi-os-setup)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running](#running)
  - [Manual start](#manual-start)
  - [Run as a systemd service](#run-as-a-systemd-service)
- [Web Dashboard](#web-dashboard)
- [WebSocket Integration](#websocket-integration)
- [Development](#development)

---

## Hardware Requirements

| Component | Notes |
|-----------|-------|
| Raspberry Pi Zero W 2 | Any Pi with SPI + I²C will work |
| RC522 RFID module | Connected via SPI (hardware SPI0) |
| 16×2 I²C LCD | PCF8574 I²C expander (default address `0x27`) |
| Passive buzzer | Connected to a GPIO pin that supports hardware PWM |
| Micro-SD card | 8 GB+ recommended; Raspberry Pi OS Lite 64-bit |

---

## Hardware Wiring

### RC522 → Raspberry Pi (SPI0)

| RC522 Pin | Pi GPIO (BCM) | Pi physical pin |
|-----------|---------------|-----------------|
| SDA (CS)  | GPIO 8        | Pin 24          |
| SCK       | GPIO 11       | Pin 23          |
| MOSI      | GPIO 10       | Pin 19          |
| MISO      | GPIO 9        | Pin 21          |
| RST       | GPIO 25       | Pin 22          |
| 3.3V      | 3V3           | Pin 17          |
| GND       | GND           | Pin 20          |

All GPIO numbers above are the defaults; every pin is overridable via `.env` (see [Configuration](#configuration)).

### 16×2 I²C LCD → Raspberry Pi (I²C1)

| LCD Pin | Pi physical pin |
|---------|-----------------|
| VCC     | Pin 2 (5V)      |
| GND     | Pin 6 (GND)     |
| SDA     | Pin 3 (GPIO 2)  |
| SCL     | Pin 5 (GPIO 3)  |

### Passive Buzzer

Connect the positive leg to **GPIO 18** (default) and the negative leg to GND. GPIO 18 supports hardware PWM on all Raspberry Pi models. The pin is configurable via `BUZZER_PIN` in `.env`.

---

## Raspberry Pi OS Setup

1. **Flash** Raspberry Pi OS Lite (64-bit) to your SD card with the Raspberry Pi Imager.  
   Enable SSH and configure Wi-Fi in the imager's advanced settings.

2. **Enable SPI and I²C** via `raspi-config`:

   ```bash
   sudo raspi-config
   # → Interface Options → SPI  → Enable
   # → Interface Options → I2C → Enable
   ```

   Or add these lines to `/boot/firmware/config.txt` (path may be `/boot/config.txt` on older images):

   ```
   dtparam=spi=on
   dtparam=i2c_arm=on
   ```

3. **Install pigpiod** (required for hardware PWM buzzer):

   ```bash
   sudo apt update && sudo apt install -y pigpio
   sudo systemctl enable pigpiod
   sudo systemctl start pigpiod
   ```

4. **Install Python 3.12+**. Raspberry Pi OS Bookworm ships with Python 3.11; install a newer version from deadsnakes or use `uv` (which manages its own Python):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   source $HOME/.local/bin/env   # or restart your shell
   ```

---

## Installation

```bash
# Clone the repository
git clone https://github.com/afonsoingles/universal-reader.git
cd universal-reader

# Install dependencies (uv will download Python 3.12 automatically if needed)
uv sync
```

---

## Configuration

Copy the example environment file and edit it:

```bash
cp .env.example .env
nano .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `INVENTORY_WS_URL` | `ws://192.168.1.100:8000/ws/reader` | WebSocket endpoint of the Inventory server |
| `INVENTORY_API_KEY` | *(empty)* | API key sent during the `register` handshake |
| `DASHBOARD_PASSWORD` | `changeme` | Password for the local web dashboard |
| `DASHBOARD_PORT` | `5050` | TCP port the dashboard listens on |
| `LCD_I2C_ADDR` | `0x27` | I²C address of the LCD's PCF8574 expander |
| `BUZZER_PIN` | `18` | BCM GPIO pin for the passive buzzer |
| `RC522_MISO` | `9` | BCM GPIO — RC522 MISO |
| `RC522_MOSI` | `10` | BCM GPIO — RC522 MOSI |
| `RC522_SCK` | `11` | BCM GPIO — RC522 SCK |
| `RC522_SDA` | `8` | BCM GPIO — RC522 SDA (chip-select) |
| `RC522_RST` | `25` | BCM GPIO — RC522 RST |

---

## Running

### Manual start

```bash
uv run universal-reader
```

The application will:
1. Start the RC522 reader daemon thread.
2. Connect to the Inventory server via WebSocket (with automatic reconnection).
3. Serve the web dashboard on `http://<pi-ip>:<DASHBOARD_PORT>`.

### Run as a systemd service

Create `/etc/systemd/system/universal-reader.service`:

```ini
[Unit]
Description=Universal RFID Reader
After=network-online.target pigpiod.service
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/universal-reader
EnvironmentFile=/home/pi/universal-reader/.env
ExecStart=/home/pi/.local/bin/uv run universal-reader
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> Adjust `WorkingDirectory`, `EnvironmentFile`, and `ExecStart` paths if you cloned the repo elsewhere.

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable universal-reader
sudo systemctl start universal-reader

# View logs
sudo journalctl -u universal-reader -f
```

---

## Web Dashboard

Open `http://<pi-ip>:5050` (or the port set in `DASHBOARD_PORT`) in any browser.

| Page | Path | Description |
|------|------|-------------|
| Dashboard | `/` | Reader state, WebSocket status, uptime, last scan |
| Login | `/login` | Password authentication (cookie-based session) |
| Debug | `/debug` | Simulate WS messages, test LCD/buzzer, read a raw UID |
| Status API | `/status` | JSON reader status (unauthenticated) |
| Logs API | `/logs` | JSON structured log entries (authenticated) |

---

## WebSocket Integration

On startup the reader connects to `INVENTORY_WS_URL` and sends a **register** message:

```json
{ "type": "register", "api_key": "<INVENTORY_API_KEY>" }
```

The Inventory server replies with:

```json
{ "type": "registered", "reader_number": 1 }
```

### Messages from Inventory → Reader

| Type | Fields | Effect |
|------|--------|--------|
| `activate` | `timeout_seconds: int` | Moves reader to ACTIVE; starts activation timer |
| `deactivate` | — | Returns reader to HIBERNATED |
| `read` | — | Moves reader to READING; waits for a tag scan |
| `result` | `status: "success"\|"not_found"\|"network_error"\|"retry"`, `item_id?: str` | Shows result on LCD/buzzer; returns to ACTIVE |
| `ping` | — | Reader replies with `{"type":"pong"}` |

### Messages from Reader → Inventory

| Type | Fields | Sent when |
|------|--------|-----------|
| `register` | `api_key` | On connection |
| `uid_scanned` | `uid: str` | Tag scanned while in READING state |
| `pong` | — | In response to a `ping` |
| `status` | `state: str` | On state change |
| `error` | `reason: str` | Rejected command (e.g. scan already in progress) |

### Reader States

```
HIBERNATED ──activate──▶ ACTIVE ──read──▶ READING ──tag scanned──▶ AWAITING_RESULT
    ▲                       │                                              │
    └───────deactivate/timeout                   result received ──────────┘
SYSTEM_FAILURE  (ws disconnected — auto-recovers on reconnect)
LOCALLY_DISABLED (dashboard disable — ignores all WS messages)
```

---

## Development

```bash
# Install dev dependencies
uv sync --group dev

# Run tests
uv run pytest tests/

# Start without real hardware (mocks are used automatically on non-Pi platforms)
uv run universal-reader
```

Hardware drivers (RC522 via `mfrc522`, LCD via `RPLCD`, buzzer via `pigpio`) fall back to mock stubs automatically when the libraries are not importable, so the full application — including the dashboard — can be developed and tested on any machine.
