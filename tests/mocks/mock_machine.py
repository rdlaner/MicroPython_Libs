"""Mocks for the micropython's machine module"""
# Standard imports
import threading
import time
from typing import Callable, Optional, Tuple

# Third party imports


class MockRtc():
    def __init__(self, rtc_id: int = 0, datetime: Tuple = ()):
        self._id = rtc_id
        self._datetime = datetime

    def datetime(self) -> Tuple:
        t = time.localtime()
        return t

    def now(self) -> int:
        return int(time.time() * 1_000_000)  # microseconds

    def offset(self, offset: bytes):
        ...


class MockTimer:
    """Mock implementation of MicroPython's Timer class for testing."""

    # Timer modes
    ONE_SHOT = 0
    PERIODIC = 1

    def __init__(self, timer_id: int = -1):
        self._id = timer_id
        self._callback: Optional[Callable] = None
        self._timer: Optional[threading.Timer] = None
        self._mode = None
        self._period_ms = None
        self._active = False

    def init(self, *, mode=ONE_SHOT, period=-1, callback=None):
        """Initialize and start the timer.

        Args:
            mode: ONE_SHOT or PERIODIC
            period: Timer period in milliseconds
            callback: Function to call when timer fires
        """
        self.deinit()  # Stop any existing timer

        self._mode = mode
        self._period_ms = period
        self._callback = callback
        self._active = True

        if period > 0 and callback is not None:
            self._start_timer()

    def _start_timer(self):
        """Internal method to start the threading.Timer."""
        if self._callback is None or self._period_ms is None:
            return

        def timer_fired():
            if self._callback:
                self._callback(self)

            # Restart for PERIODIC mode
            if self._mode == MockTimer.PERIODIC and self._active:
                self._start_timer()

        self._timer = threading.Timer(self._period_ms / 1000.0, timer_fired)
        self._timer.daemon = True
        self._timer.start()

    def deinit(self):
        """Stop and deinitialize the timer."""
        self._active = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._callback = None
        self._mode = None
        self._period_ms = None

    def __del__(self):
        """Cleanup when timer object is destroyed."""
        self.deinit()
