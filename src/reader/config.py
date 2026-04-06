"""Configuration loader — reads .env and builds AppConfig."""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

from reader.models import AppConfig, HardwareConfig

load_dotenv()


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Load and cache application configuration from environment variables."""
    hw = HardwareConfig(
        lcd_i2c_addr=int(os.getenv("LCD_I2C_ADDR", "0x27"), 16)
        if os.getenv("LCD_I2C_ADDR", "0x27").startswith("0x")
        else int(os.getenv("LCD_I2C_ADDR", "39")),
        buzzer_pin=int(os.getenv("BUZZER_PIN", "18")),
        rc522_miso=int(os.getenv("RC522_MISO", "9")),
        rc522_mosi=int(os.getenv("RC522_MOSI", "10")),
        rc522_sck=int(os.getenv("RC522_SCK", "11")),
        rc522_sda=int(os.getenv("RC522_SDA", "8")),
        rc522_rst=int(os.getenv("RC522_RST", "25")),
    )

    return AppConfig(
        inventory_ws_url=os.getenv("INVENTORY_WS_URL", "ws://192.168.1.100:8000/ws/reader"),
        inventory_api_key=os.getenv("INVENTORY_API_KEY", ""),
        dashboard_password=os.getenv("DASHBOARD_PASSWORD", "changeme"),
        dashboard_port=int(os.getenv("DASHBOARD_PORT", "5050")),
        hardware=hw,
    )
