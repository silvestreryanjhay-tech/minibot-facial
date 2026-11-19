"""Buzzer driver. Uses gpiozero on a Raspberry Pi, falls back to a silent mock on a PC."""
import os
import threading
import time


class Buzzer:
    def __init__(self, pin=None):
        self.pin = int(pin or os.environ.get("BUZZER_PIN", 17))
        self.device = None
        self.mock = True
        self.active = False
        self._lock = threading.Lock()
        try:
            from gpiozero import Buzzer as GpioBuzzer  # only works on a Pi
            self.device = GpioBuzzer(self.pin)
            self.mock = False
        except Exception:
            self.device = None

    def _on(self):
        if self.device:
            self.device.on()

    def _off(self):
        if self.device:
            self.device.off()

    def _run(self, pattern):
        # one pattern at a time, so overlapping alerts do not stack up
        if not self._lock.acquire(blocking=False):
            return
        try:
            self.active = True
            for on_s, off_s in pattern:
                self._on()
                time.sleep(on_s)
                self._off()
                time.sleep(off_s)
        finally:
            self._off()
            self.active = False
            self._lock.release()

    def alarm(self):
        """Three quick beeps: face not registered / not recognized."""
        threading.Thread(target=self._run, args=([(0.25, 0.12)] * 3,), daemon=True).start()

    def test(self):
        threading.Thread(target=self._run, args=([(0.15, 0.0)],), daemon=True).start()
