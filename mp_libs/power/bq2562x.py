"""BQ2562x Battery Charger Driver

TODO: Add thermistor support
"""
# pylint: disable=import-error, wrong-import-order

# Standard imports
from machine import I2C
from micropython import const
try:
    from typing import Optional
except ImportError:
    pass

# Third party imports
from mp_libs import logging

# Local imports
try:
    from config import config  # type: ignore
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants
I2C_ADDR = const(0x6A)

# ADC Inputs
ADC_IBUS = const(7)
ADC_IBAT = const(6)
ADC_VBUS = const(5)
ADC_VBAT = const(4)
ADC_VSYS = const(3)
ADC_TS = const(2)
ADC_TDIE = const(1)
ADC_VPMID = const(0)

# ADC Setup
ADC_RATE_CONTINUOUS = const(0)
ADC_RATE_ONESHOT = const(1)
ADC_RESOLUTION_12 = const(0)
ADC_RESOLUTION_11 = const(1)
ADC_RESOLUTION_10 = const(2)
ADC_RESOLUTION_9 = const(3)

# Delays
BATT_FET_DELAY_20_MS = const(0)
BATT_FET_DELAY_10_SEC = const(1)

# Charging Status
CHARGE_STATUS_NOT = const(0)
CHARGE_STATUS_TRICKLE = const(1)
CHARGE_STATUS_TAPER = const(2)
CHARGE_STATUS_TOPOFF = const(3)

# Min/Max Values
MIN_CHARGING_CURRENT = const(40)
MAX_CHARGING_CURRENT = const(2000)
MIN_VINDPM_VOLT = const(4600)
MAX_VINDPM_VOLT = const(16800)
RESET_VINDPM_VOLT = const(4600)
MIN_IINDPM_CURRENT = const(100)
MAX_IINDPM_CURRENT = const(3200)
MAX_ITERM_CURRENT = const(310)
MIN_ITERM_CURRENT = const(5)

# Top-Off Timer Values
TOPOFF_DISABLE = const(0)
TOPOFF_17_MIN = const(1)
TOPOFF_35_MIN = const(2)
TOPOFF_52_MIN = const(3)

# Battery Discharge Current Limits
DISCHARGE_LIMIT_1_5A = const(0)
DISCHARGE_LIMIT_3A = const(1)
DISCHARGE_LIMIT_6A = const(2)
DISCHARGE_LIMIT_12A = const(3)

# Watchdog Timer Values
WDT_DISABLED = const(0)
WDT_50_SEC = const(1)
WDT_100_SEC = const(2)
WDT_200_SEC = const(3)

# Globals
logger = logging.getLogger("BQ2562x")
logger.setLevel(config["logging_level"])


class BQ25628():
    """BQ25628 battery charger driver"""
    def __init__(self, i2c: I2C) -> None:
        self._i2c = i2c

    def _map(self, raw: int, step: float, min_val: int = 0, max_val: int = 0):
        if (min_val and max_val) and (min_val <= raw <= max_val):
            return (max_val - raw + 1) * (-1) * step

        return raw * step

    def _read_reg(self, reg: int, size: int, start: int, end: int) -> int:
        assert start <= end
        assert size in (1, 2)

        num_bits = end - start + 1
        mask = ((1 << num_bits) - 1) << start

        data = int.from_bytes(self._i2c.readfrom_mem(I2C_ADDR, reg, size), "little")
        data = (data & mask) >> start

        logger.debug(f"Read Reg Success - Reg: {hex(reg)}, Start: {start}, End: {end}, Data: {hex(data)}")
        return data

    def _write_reg(self, reg: int, size: int, start: int, end: int, value: int) -> None:
        assert size in (1, 2)
        assert start <= end
        assert end <= size * 8 - 1
        assert value <= ((2**(end - start + 1)) - 1)

        last_bit = size * 8 - 1
        num_bits = end - start + 1
        mask = ((1 << num_bits) - 1) << start

        curr_reg_val = self._read_reg(reg, size, 0, last_bit)
        new_reg_val = curr_reg_val & ~mask
        new_reg_val = new_reg_val | ((value << start) & mask)

        # Make sure data is in little endian format
        # pylint: disable=consider-using-enumerate
        data = bytearray(size)
        for i in range(len(data)):
            data[i] = new_reg_val & 0xFF
            new_reg_val = new_reg_val >> 8

        self._i2c.writeto_mem(I2C_ADDR, reg, data)
        logger.debug(f"Write Reg Success - Reg: {hex(reg)}, Start: {start}, End: {end}, Data: {hex(value)}")

    def adc_enable(self, adc: int, enable: Optional[bool] = None) -> Optional[bool]:
        """Enable/Disable a specific ADC input.

        Enables/Disables the specified ADC input. If no input is specified, will return the current
        enable/disable status.

        Args:
            adc (int): ADC input to enable/disable. See ADC_XXX constants.
            enable (Optional[bool]): True to enable, False to disable. Defaults to None.

        Raises:
            ValueError: Invalid ADC input provided.

        Returns:
            Optional[int]: Current enable status, if none specified.
        """
        if adc not in (ADC_IBUS, ADC_IBAT, ADC_VBUS, ADC_VBAT, ADC_VSYS, ADC_TS, ADC_TDIE, ADC_VPMID):
            raise ValueError(f"ADC Enable Failed. Invalid ADC: {adc}")

        if enable is None:
            return not bool(self._read_reg(0x27, 1, adc, adc))

        self._write_reg(0x27, 1, adc, adc, not enable)
        return None

    def adc_setup(
            self, enable: bool, rate: int, resolution: int, average: bool, average_init: bool = True
    ) -> None:
        """Configure the ADC(s) to sample data.

        Args:
            enable (bool): True to start ADC sampling, False to disable.
            rate (int): Either continuous or oneshot.
            resolution (int): 9, 10, 11, or 12 bit ADC resolution.
            average (bool): True to collect a running average, False to collect a single value.
            average_init (bool): True to start averaging with existing register value,
                                           False to start averaging with a new ADC sample.
                                           Defaults to True.

        Raises:
            RuntimeError: Invalid ADC rate
            RuntimeError: Invalid ADC resolution
        """
        if rate not in (ADC_RATE_CONTINUOUS, ADC_RATE_ONESHOT):
            raise RuntimeError(f"Invalid ADC rate: {rate}")
        if resolution not in (ADC_RESOLUTION_12, ADC_RESOLUTION_11, ADC_RESOLUTION_10, ADC_RESOLUTION_9):
            raise RuntimeError(f"Invalid ADC resolution: {resolution}")

        reg_value = enable << 7
        if reg_value:
            reg_value = reg_value | rate << 6 | resolution << 4
            reg_value = reg_value | 1 << 3 if average else reg_value
            reg_value = reg_value | 1 << 2 if average_init else reg_value

        self._write_reg(0x26, 1, 0, 7, reg_value)

    @property
    def batt_current(self) -> Optional[int]:
        """Get latest IBAT ADC value

        Returns:
            Optional[int]: IBAT current in mA if valid, None if invalid
        """
        invalid_result = const(0x2000)
        raw_curr = self._read_reg(0x2A, 2, 2, 15)

        if raw_curr == invalid_result:
            return None

        return round(self._map(raw_curr, 4.0, 0x38ad, 0x3fff))

    @property
    def batt_fet_delay(self) -> int:
        """Get the battery FET delay value.

        Returns:
            int: BATT_FET_DELAY_20_MS or BATT_FET_DELAY_10_SEC.
        """
        return self._read_reg(0x18, 1, 2, 2)

    @batt_fet_delay.setter
    def batt_fet_delay(self, delay: int) -> None:
        """Set the delay applied after modifying the BATFET control register

        Args:
            delay (int): BATT_FET_DELAY_20_MS or BATT_FET_DELAY_10_SEC

        Raises:
            ValueError: Invalid delay value
        """
        if delay not in (BATT_FET_DELAY_20_MS, BATT_FET_DELAY_10_SEC):
            raise ValueError(f"Batt FET Delay Set Failed. Invalid delay: {delay}")

        self._write_reg(0x18, 1, 2, 2, delay)

    @property
    def batt_fet_wvbus_enable(self) -> bool:
        """Check if WVBus is enabled or disabled.

        Returns:
            bool: True if enabled, False if disabled.
        """
        return bool(self._read_reg(0x18, 1, 3, 3))

    @batt_fet_wvbus_enable.setter
    def batt_fet_wvbus_enable(self, enable: bool) -> None:
        """Enable/Disable WVBus

        Args:
            enable (bool): True to enable, False to disable
        """
        self._write_reg(0x18, 1, 3, 3, enable)

    @property
    def batt_overcurrent_threshold(self) -> int:
        """Get the battery discharge current threshold.

        Returns:
            int: DISCHARGE_LIMIT_1_5A, DISCHARGE_LIMIT_3A, DISCHARGE_LIMIT_6A, or DISCHARGE_LIMIT_12A
        """
        return self._read_reg(0x19, 1, 6, 7)

    @batt_overcurrent_threshold.setter
    def batt_overcurrent_threshold(self, current: int) -> None:
        """Set the battery discharge current threshold.

        Args:
            current (int): DISCHARGE_LIMIT_1_5A, DISCHARGE_LIMIT_3A, DISCHARGE_LIMIT_6A, or DISCHARGE_LIMIT_12A

        Raises:
            ValueError: Invalid threshold.
        """
        if current not in (DISCHARGE_LIMIT_1_5A, DISCHARGE_LIMIT_3A, DISCHARGE_LIMIT_6A, DISCHARGE_LIMIT_12A):
            raise ValueError(f"Overcurrent threshold is invalid: {current}")

        self._write_reg(0x19, 1, 6, 7, current)

    @property
    def batt_voltage(self) -> int:
        """Get latest VBAT ADC value.

        Returns:
            int: VBAT voltage in mV
        """
        raw_volt = self._read_reg(0x30, 2, 1, 12)
        return round(self._map(raw_volt, 1.99))

    @property
    def bus_current(self) -> int:
        """Get latest IBUS ADC value.

        Returns:
            int: IBUS current in mA
        """
        raw_curr = self._read_reg(0x28, 2, 1, 15)
        return round(self._map(raw_curr, 2.0, 0x7830, 0x7fff))

    @property
    def bus_voltage(self) -> int:
        """Get latest VBUS ADC value.

        Returns:
            int: VBUS voltage in mV
        """
        raw_volt = self._read_reg(0x2C, 2, 2, 14)
        return round(self._map(raw_volt, 3.97))

    @property
    def charging_current_limit(self) -> int:
        """Get the charging current limit.

        Returns:
            int: Charging current limit in mA.
        """
        current = self._read_reg(0x02, 2, 5, 10)
        return round(self._map(current, 40))

    @charging_current_limit.setter
    def charging_current_limit(self, current: int) -> None:
        """Set the charging current limit.

        Args:
            current (int): New charging current limit in mA.

        Raises:
            RuntimeError: Invalid charge current limit.
        """
        if not MIN_CHARGING_CURRENT <= current <= MAX_CHARGING_CURRENT:
            raise RuntimeError(f"Invalid charge current limit: {current}")

        value = round(self._map(current, 1.0 / 40.0))
        self._write_reg(0x02, 2, 5, 10, value)

    @property
    def charging_enable(self) -> bool:
        """Check if charging is enabled or not.

        Returns:
            bool: True if enabled, False if disabled.
        """
        return bool(self._read_reg(0x16, 1, 5, 5))

    @charging_enable.setter
    def charging_enable(self, enable: bool) -> None:
        """Enable/Disable battery charging.

        Args:
            enable (bool): True to enable charging, False to disable.
        """
        self._write_reg(0x16, 1, 5, 5, enable)

    @property
    def charging_status(self) -> int:
        """Return current charging status.

        Returns:
            int: Current charging status. See CHARGE_STATUS_XXX options.
        """
        return self._read_reg(0x1E, 1, 3, 4)

    @property
    def interrupts_enable(self) -> bool:
        """Check if interrupts are enabled or not.

        Returns:
            bool: True if enabled, False if disabled.
        """
        reg_val = self._read_reg(0x23, 1, 0, 7)
        reg_val = reg_val | self._read_reg(0x24, 1, 0, 7)
        reg_val = reg_val | self._read_reg(0x25, 1, 0, 7)

        return reg_val == 0

    @interrupts_enable.setter
    def interrupts_enable(self, enable: bool) -> None:
        """Enable/Disable all interrupts

        Args:
            enable (bool): True to enable, False to disable.
        """
        reg_val = 0 if enable else 0xFF

        self._write_reg(0x23, 1, 0, 7, reg_val)
        self._write_reg(0x24, 1, 0, 7, reg_val)
        self._write_reg(0x25, 1, 0, 7, reg_val)

    @property
    def term_current(self) -> int:
        """Get the termination current.

        Returns:
            int: Termination current in mA.
        """
        term_current = self._read_reg(0x12, 2, 2, 7)
        return round(self._map(term_current, 5.0))

    @term_current.setter
    def term_current(self, current: int) -> None:
        """Set the termination current.

        Args:
            current (int): New termination current in mA.

        Raises:
            RuntimeError: Invalid termination current.
        """
        if not MIN_ITERM_CURRENT <= current <= MAX_ITERM_CURRENT:
            raise RuntimeError(f"Invalid termination current: {current}")

        term_current = round(self._map(current, 1.0 / 5.0))
        self._write_reg(0x12, 2, 2, 7, term_current)

    @property
    def topoff(self) -> int:
        """Get the topoff timer value.

        Returns:
            int: TOPOFF_DISABLE, TOPOFF_17_MIN, TOPOFF_35_MIN, or TOPOFF_52_MIN
        """
        return self._read_reg(0x14, 1, 3, 4)

    @topoff.setter
    def topoff(self, topoff_time: int) -> None:
        """Set the topoff timer value.

        Args:
            topoff_time (int): TOPOFF_DISABLE, TOPOFF_17_MIN, TOPOFF_35_MIN, or TOPOFF_52_MIN

        Raises:
            ValueError: Invalid topoff timer value.
        """
        if topoff_time not in (TOPOFF_DISABLE, TOPOFF_17_MIN, TOPOFF_35_MIN, TOPOFF_52_MIN):
            raise ValueError(f"Topoff time is invalid: {topoff_time}")

        self._write_reg(0x14, 1, 3, 4, topoff_time)

    @property
    def ts_enable(self) -> bool:
        """Check if TS is enabled or not.

        Returns:
            bool: True if enabled, False if disabled.
        """
        return not self._read_reg(0x1A, 1, 7, 7)

    @ts_enable.setter
    def ts_enable(self, enable: bool) -> None:
        """Enable/Disable TS

        Args:
            enable (bool): True to enable, False to disable.
        """
        self._write_reg(0x1A, 1, 7, 7, not enable)
        self.adc_enable(ADC_TS, enable)

    @property
    def wd_enable(self) -> bool:
        """Check if watchdog timer is enabled or not.

        Returns:
            bool: True if enabled, False if disabled.
        """
        return bool(self._read_reg(0x16, 1, 0, 1))

    @wd_enable.setter
    def wd_enable(self, enable: int) -> None:
        """Enable/Disable watchdog timer.

        Args:
            enable (int): WDT_DISABLED, WDT_50_SEC, WDT_100_SEC, or WDT_200_SEC

        Raises:
            RuntimeError: Invalid watchdog timer value.
        """
        if enable not in (WDT_DISABLED, WDT_50_SEC, WDT_100_SEC, WDT_200_SEC):
            raise RuntimeError(f"WDT Enable value is invalid: {enable}")

        self._write_reg(0x16, 1, 0, 1, enable)
