"""16x2 LCD with I2C PCF8574 module abstraction.

On a real Pi this uses RPLCD.
On other platforms a mock stub prints to stdout.
"""

from __future__ import annotations

from reader import logger
from reader.models import AppConfig


def center(text: str, width: int = 16) -> str:
    """Center text within *width* columns, truncating if necessary."""
    text = text[:width]
    return text.center(width)


class LCD:
    """Controls a 16x2 I2C LCD via RPLCD."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lcd = None
        self._available = False
        self._backlight_on = False

        try:
            from RPLCD.i2c import CharLCD  # type: ignore[import]

            self._lcd = CharLCD(
                i2c_expander="PCF8574",
                address=config.hardware.lcd_i2c_addr,
                port=1,
                cols=16,
                rows=2,
                dotsize=8,
            )
            self._available = True
            logger.info("lcd_init", f"LCD initialised at {hex(config.hardware.lcd_i2c_addr)}")
        except Exception as exc:  # noqa: BLE001
            logger.warn("lcd_init_mock", f"LCD not available, using mock: {exc}")

    def display(self, line1: str, line2: str, backlight: bool = True) -> None:
        l1 = center(line1)
        l2 = center(line2)
        if self._available and self._lcd is not None:
            try:
                self._lcd.backlight_enabled = backlight
                self._lcd.clear()
                self._lcd.write_string(l1)
                self._lcd.crlf()
                self._lcd.write_string(l2)
            except Exception as exc:  # noqa: BLE001
                logger.error("lcd_write_error", str(exc))
        else:
            bl = "ON" if backlight else "OFF"
            print(f"[LCD BL={bl}] |{l1}|")
            print(f"              |{l2}|")

    def off(self) -> None:
        if self._available and self._lcd is not None:
            try:
                self._lcd.backlight_enabled = False
                self._lcd.clear()
            except Exception as exc:  # noqa: BLE001
                logger.error("lcd_off_error", str(exc))
        else:
            print("[LCD OFF]")
