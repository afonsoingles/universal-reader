# Setup Guide

This guide walks you through installing and running Universal Reader on a
Raspberry Pi Zero W 2 from scratch.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Raspberry Pi Zero W 2 | Any Pi with SPI + I²C will work |
| RC522 RFID/NFC module | Connected via SPI0 |
| 16×2 I²C LCD | PCF8574 expander (default address `0x27`) |
| Passive buzzer | GPIO 18 (hardware PWM) |
| Micro-SD card | 8 GB+, Raspberry Pi OS Lite 64-bit |

---

## 1. Prepare the Raspberry Pi

### Flash the OS

Use the [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to flash
**Raspberry Pi OS Lite (64-bit)** to your SD card.  
Enable SSH and configure Wi-Fi in the imager's *Advanced options* before flashing.

### Enable SPI and I²C

```bash
sudo raspi-config
# → Interface Options → SPI  → Enable
# → Interface Options → I2C → Enable
```

Or append to `/boot/firmware/config.txt` (path may be `/boot/config.txt` on older images):

```
dtparam=spi=on
dtparam=i2c_arm=on
```

Reboot after making changes.

### Install pigpiod (hardware PWM for buzzer)

```bash
sudo apt update && sudo apt install -y pigpio
sudo systemctl enable pigpiod
sudo systemctl start pigpiod
```

---

## 2. Install Universal Reader

### Install uv (Python package manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env   # or restart your shell
```

`uv` will automatically download and manage Python 3.12+ — no need to install it separately.

### Clone and install

```bash
git clone https://github.com/afonsoingles/universal-reader.git
cd universal-reader
uv sync
```

---

## 3. Configure

```bash
cp .env.example .env
nano .env
```

At a minimum, set:

```dotenv
INVENTORY_WS_URL=ws://192.168.1.100:8000/ws/reader
INVENTORY_API_KEY=your-secret-key
DASHBOARD_PASSWORD=a-strong-password
```

See [Configuration Reference](configuration.md) for all available variables.

---

## 4. Run

### Manual start

```bash
uv run universal-reader
```

The application will:
1. Initialize RC522, LCD, and buzzer.
2. Connect to the Inventory server via WebSocket (with automatic reconnection).
3. Serve the web dashboard at `http://<pi-ip>:5050`.

Open the dashboard in a browser, log in, and the reader is ready.

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

# Follow live logs
sudo journalctl -u universal-reader -f
```

---

## 5. Access the dashboard

| URL | Description |
|-----|-------------|
| `http://<pi-ip>:5050/` | Main dashboard |
| `http://<pi-ip>:5050/debug` | Debug & simulation tools |
| `http://<pi-ip>:5050/login` | Login page |

---

## Development (without hardware)

The hardware drivers fall back to mock stubs automatically when the
Raspberry Pi-specific libraries (`mfrc522`, `RPLCD`, `pigpio`) are not
importable.  This means you can develop and test on any machine:

```bash
uv sync --group dev
uv run universal-reader          # runs with mock hardware
uv run pytest tests/             # run the test suite
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Dashboard not reachable | Is `DASHBOARD_PORT` (default 5050) open? Check `sudo ufw status`. |
| LCD shows "System Failure" on start | Verify I²C is enabled and the LCD address is correct (`i2cdetect -y 1`). |
| No buzzer sound | Verify `pigpiod` is running (`systemctl status pigpiod`). |
| RC522 not detected | Check SPI is enabled and wiring matches the [hardware guide](hardware.md). |
| WebSocket stuck reconnecting | Verify `INVENTORY_WS_URL` and that the Inventory server is reachable. |
