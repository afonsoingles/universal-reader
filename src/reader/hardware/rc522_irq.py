"""RC522 RFID reader with IRQ (interrupt) based detection instead of polling."""

from __future__ import annotations

import threading
import time
from typing import Callable

from reader import logger


class RC522ReaderIRQ:
    """Wraps SimpleMFRC522 using hardware IRQ for card detection."""

    def __init__(self, on_scan: Callable[[str], None], irq_pin: int = 25) -> None:
        self._on_scan = on_scan
        self._running = False
        self._reader = None
        self._available = False
        self._irq_pin = irq_pin
        self._last_uid: str | None = None
        self._last_uid_time: float = 0
        self._gpio = None

        try:
            import RPi.GPIO as GPIO  # type: ignore[import]

            GPIO.setwarnings(False)
            self._gpio = GPIO
            
            from mfrc522 import SimpleMFRC522  # type: ignore[import]

            self._reader = SimpleMFRC522()
            self._available = True
            logger.info("rc522_irq_init", f"RC522 reader initialised with IRQ on pin {irq_pin}")
        except Exception as exc:  # noqa: BLE001
            logger.warn("rc522_irq_init_mock", f"RC522 not available, using mock: {exc}")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info("rc522_irq_start", f"Starting RC522 with IRQ detection (pin={self._irq_pin})")
        
        if self._available and self._gpio:
            try:
                # Set up GPIO for IRQ
                self._gpio.setmode(self._gpio.BCM)
                self._gpio.setup(self._irq_pin, self._gpio.IN)
                
                # Add event detection (falling edge when card is detected)
                self._gpio.add_event_detect(
                    self._irq_pin,
                    self._gpio.FALLING,
                    callback=self._irq_callback,
                    bouncetime=50
                )
                logger.info("rc522_irq_setup", "IRQ detection enabled")
            except Exception as e:
                logger.error("rc522_irq_setup_failed", f"Failed to setup IRQ: {e}")
                # Fall back to polling
                self._start_polling()
        else:
            self._start_polling()

    def _start_polling(self) -> None:
        """Fall back to polling if IRQ setup fails."""
        logger.info("rc522_irq_fallback_polling", "Falling back to polling mode")
        thread = threading.Thread(target=self._read_loop, daemon=True, name="rc522-reader")
        thread.start()

    def _irq_callback(self, pin) -> None:
        """Called when IRQ fires (card detected)."""
        logger.verbose("rc522_irq_fired", f"IRQ triggered on pin {pin}")
        if self._available and self._reader is not None:
            try:
                uid, _ = self._reader.read_no_block()
                if uid is not None:
                    uid_str = format(uid, "X")
                    current_time = time.time()
                    
                    # Debounce: ignore same UID within 0.5 seconds
                    if uid_str != self._last_uid or (current_time - self._last_uid_time) > 0.5:
                        logger.info("rc522_irq_tag_detected", uid_str)
                        self._on_scan(uid_str)
                        self._last_uid = uid_str
                        self._last_uid_time = current_time
            except Exception as exc:  # noqa: BLE001
                logger.error("rc522_irq_read_error", f"{type(exc).__name__}: {exc}")

    def _read_loop(self) -> None:
        """Fallback polling loop."""
        logger.info("rc522_irq_polling_started", "Polling read loop started")
        loop_count = 0
        last_error_logged = None
        
        while self._running:
            if self._available and self._reader is not None:
                try:
                    uid, _ = self._reader.read_no_block()
                    if uid is not None:
                        uid_str = format(uid, "X")
                        current_time = time.time()
                        
                        # Debounce: ignore same UID within 0.5 seconds
                        if uid_str != self._last_uid or (current_time - self._last_uid_time) > 0.5:
                            logger.info("rc522_polling_tag_detected", uid_str)
                            self._on_scan(uid_str)
                            self._last_uid = uid_str
                            self._last_uid_time = current_time
                    
                    loop_count += 1
                    if loop_count % 50 == 0:
                        logger.verbose("rc522_polling_alive", f"Polling running (count={loop_count})")
                except Exception as exc:  # noqa: BLE001
                    exc_str = f"{type(exc).__name__}: {exc}"
                    if exc_str != last_error_logged:
                        logger.error("rc522_polling_error", exc_str)
                        last_error_logged = exc_str
            time.sleep(0.1)

    def stop(self) -> None:
        self._running = False
        if self._available and self._gpio:
            try:
                self._gpio.remove_event_detect(self._irq_pin)
                logger.info("rc522_irq_stop", "IRQ detection disabled")
            except:
                pass

    def reset(self) -> None:
        """Reset the reader state and clear debounce cache."""
        self._last_uid = None
        self._last_uid_time = 0
        logger.info("rc522_irq_reset", "RC522 debounce state cleared")

    def restart(self) -> None:
        """Restart the reader by reinitializing the mfrc522 library."""
        logger.info("rc522_irq_restart_start", "Restarting RC522 reader with IRQ")
        
        # Stop current
        self.stop()
        
        # Clean up GPIO to reset SPI/GPIO state
        try:
            if self._gpio:
                logger.verbose("rc522_irq_gpio_cleanup", "Cleaning up GPIO before restart")
                self._gpio.cleanup()
                logger.verbose("rc522_irq_gpio_cleanup_done", "GPIO cleanup complete")
        except Exception as e:
            logger.warn("rc522_irq_gpio_cleanup_error", str(e))
        
        # Wait for hardware to settle
        logger.verbose("rc522_irq_settling", "Waiting for hardware to settle")
        time.sleep(1.0)
        
        # Reinitialize the reader library
        try:
            if self._reader is not None:
                try:
                    logger.verbose("rc522_irq_cleanup_old", "Cleaning up old reader instance")
                    if hasattr(self._reader, 'READER') and self._reader.READER:
                        try:
                            self._reader.READER.close()
                        except:
                            pass
                    self._reader = None
                except Exception as e:
                    logger.warn("rc522_irq_cleanup_error", str(e))
                    self._reader = None
            
            logger.verbose("rc522_irq_init_new", "Initializing new reader instance")
            from mfrc522 import SimpleMFRC522  # type: ignore[import]
            self._reader = SimpleMFRC522()
            self._available = True
            logger.info("rc522_irq_restart_success", "RC522 reader reinitialized successfully")
        except Exception as exc:  # noqa: BLE001
            logger.error("rc522_irq_restart_failed", f"Failed to reinitialize: {type(exc).__name__}: {exc}")
            self._reader = None
            self._available = False
            return
        
        # Clear debounce state
        self._last_uid = None
        self._last_uid_time = 0
        
        # Verify callback is set
        if self._on_scan is None:
            logger.error("rc522_irq_restart_no_callback", "No callback set!")
        else:
            logger.verbose("rc522_irq_restart_callback_ok", "Callback is set")
        
        # Restart with IRQ
        self.start()
        logger.info("rc522_irq_restart_complete", "RC522 reader restarted successfully with IRQ")

    def is_running(self) -> bool:
        """Check if the reader is running."""
        return self._running
