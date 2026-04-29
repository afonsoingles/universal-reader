"""Application and hardware configuration models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HardwareConfig(BaseModel):
    lcd_i2c_addr: int = 0x27
    buzzer_pin: int = 18
    rc522_miso: int = 9
    rc522_mosi: int = 10
    rc522_sck: int = 11
    rc522_sda: int = 8
    rc522_rst: int = 25
    rc522_irq_pin: int = 17


class AppConfig(BaseModel):
    inventory_ws_url: str
    inventory_api_key: str
    dashboard_password: str
    dashboard_port: int = 5050
    hardware: HardwareConfig = Field(default_factory=HardwareConfig)
