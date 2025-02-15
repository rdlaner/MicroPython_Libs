"""Hardware Button Support Library

Debounces button inputs and invokes any registered callback when button is pressed.
"""
# Standard imports
import time
from machine import Pin, Timer
from micropython import const

# Constants
DEF_DEBOUNCE_PERIOD_MSEC = const(10)
DEF_DEBOUNCE_DURATION_MSEC = const(50)


class Button():
    def __init__(
        self,
        pin: Pin,
        timer_id: int = 0,
        cb: "Callable[[Pin], None]" = None,
        debounce_period_msec: int = DEF_DEBOUNCE_PERIOD_MSEC,
        debounce_duration_msec: int = DEF_DEBOUNCE_DURATION_MSEC,
        active_low: bool = True
    ) -> None:
        self._pin = pin
        self._cb = cb
        self.period_msec = debounce_period_msec
        self._active_low = active_low
        self._check_count = 0
        self._total_checks = debounce_duration_msec // debounce_period_msec
        self._timer = Timer(timer_id)
        self._pin.irq(handler=self._button_handler, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING)

    def _button_handler(self, pin):
        # Stop interrupts for this pin until debouncing has completed
        self._pin.irq(trigger=0)

        # Reset counter and start debounce timer
        self._check_count = 0
        self._timer.init(mode=Timer.ONE_SHOT, period=self.period_msec, callback=self._timer_handler)

    def _timer_handler(self, timer):
        if self._active_low:
            button_pressed = not self._pin.value()
        else:
            button_pressed = self._pin.value()

        if button_pressed:
            # Button is still pressed, restart timer and counter
            self._check_count = 0
            self._timer.init(mode=Timer.ONE_SHOT, period=self.period_msec, callback=self._timer_handler)
            return

        self._check_count += 1
        if self._check_count >= self._total_checks:
            # Button is debounced, invoke callback if one is registered
            if self._cb:
                self._cb(self._pin)

            # Restart interrupts for this pin
            self._pin.irq(handler=self._button_handler, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING)
        else:
            # Button has not been released long enough, restart timer
            self._timer.init(mode=Timer.ONE_SHOT, period=self.period_msec, callback=self._timer_handler)

    def register_cb(self, cb: "Callable[[Pin], None]") -> None:
        """Register a callback function to be called on a button press event.

        Callback takes one argument, the Pin triggered, and returns None.

        Args:
            cb (Callable[[Pin], None]): Callback function.
        """
        self._cb = cb
