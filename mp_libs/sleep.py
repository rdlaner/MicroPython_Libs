"""Sleep Support Library"""
# pylint: disable=c-extension-no-member
# pyright: reportGeneralTypeIssues=false
# Standard imports
import gc
import time
from machine import deepsleep, soft_reset, lightsleep, wake_reason

# Third party imports
from mp_libs import logging

# Local imports
try:
    from config import config
except ImportError:
    config = {"logging_level": logging.INFO}

# Globals
logger = logging.getLogger("sleep")
logger.setLevel(config["logging_level"])
stream_handler = logging.StreamHandler()
stream_handler.setLevel(config["logging_level"])
stream_handler.setFormatter(logging.Formatter("%(mono)d %(name)s-%(levelname)s:%(message)s"))
logger.addHandler(stream_handler)


class ResetCause:
    PWRON_RESET: 1
    HARD_RESET: 2
    WDT_RESET: 3
    DEEPSLEEP_RESET: 4
    SOFT_RESET: 5


class WakeReason:
    PIN_WAKE: 2  # PIN and EXT0 are both defined as ESP_SLEEP_WAKEUP_EXT0 and have the same value.
    EXT0_WAKE: 2
    EXT1_WAKE: 3
    TIMER_WAKE: 4
    TOUCHPAD_WAKE: 5
    ULP_WAKE: 6


def deep_sleep(sleep_time_sec: float, is_serial_connected: "Callable", is_esp32: bool = True) -> None:
    """Deep sleep for specified time.

    If `is_serial_connected` returns True, will not deep sleep but instead delay for the specified
    sleep time. This is to allow for serial connection to be maintained for debugging purposes.

    If using esp32 hardware, make sure `is_esp32` is set to True. This will ensure that a soft
    device reboot occurs if serial is connected in order to emulate the esp deep sleep behavior.

    Args:
        sleep_time_sec (float): Deep sleep duration in seconds
        is_serial_connected (Calleable): Function that returns a True if serial is connected,
                                         False if it is not
        is_esp32 (bool): True if using esp32 hardware, False otherwise. Defaults to True.
    """
    logger.info("Deep Sleeping...\n")

    if is_serial_connected():
        time.sleep(sleep_time_sec)
        if is_esp32:
            soft_reset()
    else:
        sleep_time_msec = int(sleep_time_sec * 1000)
        deepsleep(sleep_time_msec)


def light_sleep(sleep_time_sec: float, is_serial_connected: "Callable") -> int:
    """Light sleep for specified time.

    If `is_serial_connected` returns True, will not deep sleep but instead delay for the specified
    sleep time. This is to allow for serial connection to be maintained for debugging purposes.

    Args:
        sleep_time_sec (float): Light sleep duration in seconds
        is_serial_connected (Calleable): Function that returns a True if serial is connected,
                                         False if it is not

    Returns:
        int: Wake reason
    """
    logger.info("Light Sleeping...\n")

    if is_serial_connected():
        time.sleep(sleep_time_sec)
    else:
        sleep_time_msec = int(sleep_time_sec * 1000)
        lightsleep(sleep_time_msec)

    gc.collect()

    return wake_reason()
