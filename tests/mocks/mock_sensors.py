"""Mocks for the mp_lib's sensor drivers"""
# Standard imports
import time
from machine import I2C
from micropython import const
from typing import List, Optional, Tuple

# Third party imports

# Local imports
from mp_libs import logging
from mp_libs.sensors import veml7700
try:
    from config import config  # type: ignore
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants
I2C_ADDR = const(0x10)
DEFAULT_DATA = [
    100, 200, 300, 400, 500, 600, 700, 800, 900,
    1000, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900,
    2000, 2200, 2300, 2400, 2500, 2600, 2700, 2800, 2900,
    3000, 3200, 3300, 3400, 3500, 3600, 3700, 3800, 3900,
    4000, 4200, 4300, 4400, 4500, 4600, 4700, 4800, 4900,
    5000, 5200, 5300, 5400, 5500, 5600, 5700, 5800, 5900,
    6000, 6200, 6300, 6400, 6500, 6600, 6700, 6800, 6900,
    7000, 7200, 7300, 7400, 7500, 7600, 7700, 7800, 7900,
    8000, 8200, 8300, 8400, 8500, 8600, 8700, 8800, 8900,
    9000, 9200, 9300, 9400, 9500, 9600, 9700, 9800, 9900,
]

# Globals
logger = logging.getLogger("VEML7700")
logger.setLevel(config["logging_level"])


class MockVEML7000:
    def __init__(self, i2c: Optional[I2C] = None, address: int = I2C_ADDR, raw_data: List[int] = DEFAULT_DATA) -> None:
        self._i2c = i2c
        self._address = address
        self._is_enabled = False
        self._gain = veml7700.ALS_GAIN_1_4
        self._integration = veml7700.ALS_100MS
        self._raw_data = raw_data
        self._data_idx = 0

        logger.info("Initialized VEML7700")

    def disable(self, wait: int = 5) -> None:
        self._is_enabled = False

        if wait:
            time.sleep(wait / 1_000)

    def enable(self, wait: int = 5):
        self._is_enabled = True

        if wait:
            time.sleep(wait / 1000)

    def gain(self, gain: int = veml7700.ALS_GAIN_READ) -> int:
        if gain != veml7700.ALS_GAIN_READ:
            self._gain = gain
            time.sleep(0.05)

        return veml7700.VEML7700._gain_reg_to_actual[veml7700.VEML7700._gain_index_to_reg[self._gain]]

    def integration_time(self, integration: int = veml7700.ALS_INTEGRATION_READ) -> int:
        if integration != veml7700.ALS_INTEGRATION_READ:
            self._integration = integration
            time.sleep(0.4)

        return veml7700.VEML7700._it_reg_to_actual[veml7700.VEML7700._it_index_to_reg[self._integration]]

    def light_raw(self) -> int:
        data = self._raw_data[self._data_idx]
        self._data_idx = (self._data_idx + 1) % len(self._raw_data)
        return data

    def lux(self) -> float:
        return round(self.resolution() * self.light_raw(), 2)

    def resolution(self) -> float:
        """Calculate resolution necessary to calculate lux.

        Based on integration time and gain settings.

        Returns:
            float: Calculated resolution.
        """
        resolution_at_max = const(0.0036)
        gain_max = const(2)
        gain = self.gain()
        integration_time_max = const(800)
        integration_time = self.integration_time()

        if (gain == gain_max) and (integration_time == integration_time_max):
            return resolution_at_max

        return resolution_at_max * (integration_time_max / integration_time) * (gain_max / gain)
