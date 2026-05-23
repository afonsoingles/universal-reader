# Configuration Reference

Universal Reader is configured entirely through environment variables.  
Create a `.env` file in the project root (copy `.env.example` as a starting point):

```bash
cp .env.example .env
nano .env
```

---

## Connection

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `INVENTORY_WS_URL` | `ws://192.168.1.100:8000/ws/reader` | ✅ | WebSocket endpoint of the Inventory server |
| `INVENTORY_API_KEY` | *(empty)* | ✅ | API key sent in the `register` handshake |

---

## Dashboard

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DASHBOARD_PASSWORD` | `changeme` | ✅ | Password for the local web dashboard |
| `DASHBOARD_PORT` | `5050` | — | TCP port the dashboard listens on |

> **Security**: Change `DASHBOARD_PASSWORD` before deploying.  The default value
> is intentionally weak and must not be used in production.

---

## Hardware GPIO

All GPIO pin numbers are BCM (Broadcom) pin numbers.

| Variable | Default | Description |
|----------|---------|-------------|
| `LCD_I2C_ADDR` | `0x27` | I²C address of the LCD's PCF8574 expander |
| `BUZZER_PIN` | `18` | BCM GPIO for the passive buzzer (must support hardware PWM) |
| `RC522_MISO` | `9` | BCM GPIO — RC522 MISO (SPI0) |
| `RC522_MOSI` | `10` | BCM GPIO — RC522 MOSI (SPI0) |
| `RC522_SCK` | `11` | BCM GPIO — RC522 SCK (SPI0) |
| `RC522_SDA` | `8` | BCM GPIO — RC522 SDA / chip-select (SPI0 CE0) |
| `RC522_RST` | `25` | BCM GPIO — RC522 RST |
| `RC522_IRQ_PIN` | `17` | BCM GPIO — RC522 IRQ (interrupt-driven scan detection) |

---

## Example `.env`

```dotenv
# Inventory server
INVENTORY_WS_URL=ws://192.168.1.100:8000/ws/reader
INVENTORY_API_KEY=my-super-secret-key

# Dashboard
DASHBOARD_PASSWORD=correct-horse-battery-staple
DASHBOARD_PORT=5050

# Hardware (defaults work for the standard wiring)
LCD_I2C_ADDR=0x27
BUZZER_PIN=18
RC522_MISO=9
RC522_MOSI=10
RC522_SCK=11
RC522_SDA=8
RC522_RST=25
RC522_IRQ_PIN=17
```

---

## Notes

- **`LCD_I2C_ADDR`** accepts both hex (`0x27`) and decimal (`39`) notation.
- The application automatically falls back to mock hardware when running on
  a non-Pi platform, so all settings are safe to leave at their defaults
  during development.
- All hardware defaults assume the standard wiring shown in the
  [Hardware Wiring guide](hardware.md).
