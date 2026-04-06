"""Passive buzzer control via pigpio hardware PWM.

On a real Pi pigpiod must be running.
On other platforms a mock stub prints the tone parameters.
"""

from __future__ import annotations

import time

from reader import logger
from reader.models import AppConfig


class Buzzer:
    """Hardware PWM buzzer via pigpio."""

    def __init__(self, config: AppConfig) -> None:
        self._pin = config.hardware.buzzer_pin
        self._pi = None
        self._available = False

        try:
            import pigpio  # type: ignore[import]

            pi = pigpio.pi()
            if not pi.connected:
                raise RuntimeError("pigpiod is not running")
            self._pi = pi
            self._available = True
            logger.info("buzzer_init", f"Buzzer initialised on GPIO {self._pin}")
        except Exception as exc:  # noqa: BLE001
            logger.warn("buzzer_init_mock", f"Buzzer not available, using mock: {exc}")

    def _beep(self, freq: int, duration: float) -> None:
        if self._available and self._pi is not None:
            try:
                self._pi.hardware_PWM(self._pin, freq, 500_000)
                time.sleep(duration)
                self._pi.hardware_PWM(self._pin, 0, 0)
            except Exception as exc:  # noqa: BLE001
                logger.error("buzzer_beep_error", str(exc))
        else:
            print(f"[BUZZER] {freq}Hz for {duration}s")

    def beep(self, freq: int, duration: float) -> None:
        """Play a single tone (blocking)."""
        self._beep(freq, duration)

    def beep_sequence(self, freq: int, duration: float, count: int, gap: float) -> None:
        """Play *count* beeps of *freq* Hz separated by *gap* seconds."""
        for i in range(count):
            self._beep(freq, duration)
            if i < count - 1:
                time.sleep(gap)

    # ------------------------------------------------------------------
    # Named patterns
    # ------------------------------------------------------------------

    def reading_start(self) -> None:
        """1 short low beep on entering READING."""
        self.beep(520, 0.25)

    def result_processing(self) -> None:
        """1 long high beep (indicates processing)."""
        self.beep(1400, 0.75)

    def result_success(self) -> None:
        """2 short high beeps (success feedback)."""
        # Use short durations for the two-tone success indication.
        # (previously 0.9s which was too long / likely a typo)
        self.beep_sequence(1400, 0.08, 2, 0.06)

    def result_error(self) -> None:
        """3 short high beeps (not_found / network_error / retry)."""
        self.beep_sequence(1600, 0.08, 3, 0.06)
