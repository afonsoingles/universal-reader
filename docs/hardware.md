# Hardware Wiring

This guide covers the physical connections between the Raspberry Pi and each
peripheral.  All GPIO numbers use the BCM (Broadcom) numbering scheme.

---

## RC522 RFID/NFC Module → Raspberry Pi (SPI0)

| RC522 Pin | BCM GPIO | Pi physical pin | Notes |
|-----------|----------|-----------------|-------|
| SDA (CS)  | GPIO 8   | Pin 24          | SPI0 CE0 |
| SCK       | GPIO 11  | Pin 23          | SPI0 SCLK |
| MOSI      | GPIO 10  | Pin 19          | SPI0 MOSI |
| MISO      | GPIO 9   | Pin 21          | SPI0 MISO |
| RST       | GPIO 25  | Pin 22          | Reset |
| IRQ       | GPIO 17  | Pin 11          | Interrupt — IRQ-based scan detection |
| 3.3V      | 3V3      | Pin 17          | Power |
| GND       | GND      | Pin 20          | Ground |

All pins are configurable via environment variables — see [Configuration](configuration.md).

---

## 16×2 I²C LCD → Raspberry Pi (I²C1)

| LCD Pin | Pi physical pin | Notes |
|---------|-----------------|-------|
| VCC     | Pin 2 (5V)      | Power |
| GND     | Pin 6 (GND)     | Ground |
| SDA     | Pin 3 (GPIO 2)  | I²C1 SDA |
| SCL     | Pin 5 (GPIO 3)  | I²C1 SCL |

The PCF8574-based backpack defaults to I²C address `0x27`.  
Some modules use `0x3F` — check with `i2cdetect -y 1` if the LCD is not detected.

---

## Passive Buzzer

| Buzzer Pin | Connection | Notes |
|------------|-----------|-------|
| `+` (positive) | GPIO 18 (Pin 12) | BCM 18 — hardware PWM0 |
| `−` (negative) | GND (Pin 14) | |

GPIO 18 supports hardware PWM on all Raspberry Pi models.  
The pin is configurable via `BUZZER_PIN` in `.env`.

> **Important**: Use a *passive* buzzer, not an active one.  An active buzzer
> produces a fixed tone regardless of frequency, so the tone patterns will not
> work correctly.

---

## Raspberry Pi GPIO reference

```
 3V3  (1) (2)  5V
 SDA  (3) (4)  5V
 SCL  (5) (6)  GND
 GP4  (7) (8)  TX
 GND  (9) (10) RX
  IRQ (11) (12) BUZZER(GPIO18)
 GP13 (13) (14) GND
 ...
 MISO (21) (22) RC522_RST(GPIO25)
 MOSI (19) (23) SCK(GPIO11)
 CS0  (24) (25) GND
```

---

## Verifying connections

```bash
# Check I²C devices (should show 0x27 or 0x3F for LCD)
i2cdetect -y 1

# Check SPI is enabled
ls /dev/spi*

# Check pigpiod (needed for buzzer)
systemctl status pigpiod
```
