"""PowerFeather BSP

TODO: Use specific exceptions instead of just RuntimeError everywhere
TODO: Add support for thermistors
TODO: Add support for alarms
TODO: Instead of throwing, return None for these functions:
            batt_voltage()
            batt_charge()
            batt_cycles()
            batt_health()
            batt_time_left()
"""
# pylint: disable=import-error, wrong-import-order

# Standard imports
import time
from micropython import const
from machine import I2C, Pin
try:
    from typing import Callable, Optional
except ImportError:
    pass

# Third party imports
from mp_libs import logging
from mp_libs.button import Button
from mp_libs.enum import Enum
from mp_libs.singleton import singleton

# Local imports
from mp_libs.power import bq2562x as bq
from mp_libs.power import lc709204f as fg
try:
    from config import config  # type: ignore
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants
I2C_FREQ = const(100000)
I2C_TIMEOUT = const(50000)
CHARGER_ADC_WAIT_TIME_MS = const(90)

# Globals
logger: logging.Logger = logging.getLogger("PF")
logger.setLevel(config["logging_level"])


class BatteryError(Exception):
    """Battery errors"""


class BatteryType(Enum):
    """Supported Battery Types"""
    GENERIC_3V7 = fg.BATT_PROF_3V7_4V2        # Generic Li-ion/LiPo, 3.7 V nominal and 4.2 V max
    ICR18650_26H = fg.BATT_PROF_ICR18650_26H  # Samsung ICR18650-26H
    UR18650ZY = fg.BATT_PROF_UR18650ZY        # Panasonic UR18650ZY


@singleton
class PowerFeather():
    """PowerFeather Driver Class"""
    def __init__(
            self,
            batt_type: Optional[BatteryType] = None,
            batt_cap: Optional[int] = None,
            first_boot: bool = True,
            init_periphs: bool = True
    ) -> None:
        if batt_cap is not None and not fg.MIN_BATT_CAPACITY <= batt_cap <= fg.MAX_BATT_CAPACITY:
            raise ValueError(
                f"Invalid batt capacity ({batt_cap}). "
                f"Must be between {fg.MIN_BATT_CAPACITY} and {fg.MAX_BATT_CAPACITY} mah."
            )

        if batt_type is not None and not BatteryType.contains(batt_type):
            raise ValueError(f"Invalid battery type: {batt_type}. Supported types are: {BatteryType.print()}")

        self._battery_configure(batt_type, batt_cap)

        # Initialize pins
        self._pin_sqt = Pin(Pin.board.SQT_EN, Pin.OUT)      # type: ignore[reportAttributeAccessIssue]
        self._pin_3v3 = Pin(Pin.board.EN_3V3, Pin.OUT)      # type: ignore[reportAttributeAccessIssue]
        self._pin_fw_wr = Pin(Pin.board.FW_EN_WR, Pin.OUT)  # type: ignore[reportAttributeAccessIssue]
        self._pin_led = Pin(Pin.board.LED, Pin.OUT)         # type: ignore[reportAttributeAccessIssue]
        self._pin_fw_rd = Pin(Pin.board.FW_EN_RD, Pin.IN)   # type: ignore[reportAttributeAccessIssue]
        self._pin_btn = Pin(Pin.board.BTN, Pin.IN)          # type: ignore[reportAttributeAccessIssue]
        self._pin_pg = Pin(Pin.board.PG, Pin.IN)            # type: ignore[reportAttributeAccessIssue]
        if first_boot:
            self._pin_sqt.on()
            self._pin_fw_wr.on()
            self._pin_3v3.on()

        logger.debug(f"SQT state: {self._pin_sqt.value()}")
        logger.debug(f"FW EN: {self._pin_fw_rd.value()}")
        logger.debug(f"3V3 EN: {self._pin_3v3.value()}")

        # Initialize peripherals
        self._i2c = I2C(0, freq=I2C_FREQ, timeout=I2C_TIMEOUT)
        self._button = Button(pin=self._pin_btn, cb=None)
        self._charger = bq.BQ25628(self._i2c)
        self._fuel_gauge = fg.LC709204F(self._i2c)

        # Using VSQT (I2C pull-up pwr) as indicator to determine if the charger and fuel gauge can be initialized
        if self._pin_sqt.value() and init_periphs:
            self._init_charger()
            self._init_fuel_gauge()

        logger.debug(
            f"PowerFeather initialized with batt cap of {self._batt_cap} mah and {self._batt_type} type")

    def _battery_configure(self, batt_type: Optional[BatteryType], capacity: Optional[int]):
        if batt_type in (fg.BATT_PROF_ICR18650_26H, fg.BATT_PROF_UR18650ZY):
            # Used a predefined capacity for these specific battery profiles
            capacity = 2600

        # Set termination current to C // 10 or within the charger's min/max limits
        self._batt_type = batt_type
        self._batt_cap = capacity
        if self._batt_cap:
            self._term_curr = min(max(self._batt_cap // 10, bq.MIN_ITERM_CURRENT), bq.MAX_ITERM_CURRENT)
        else:
            self._term_curr = None

        logger.info(f"Term current: {self._term_curr}")

    def _init_charger(self, force: bool = False) -> None:
        if not force and self._is_charger_initialized():
            logger.info("Charger IC already initialized")
            return

        # Default initialization
        self._charger.charging_enable = False
        self._charger.ts_enable = False
        self._charger.batt_fet_delay = bq.BATT_FET_DELAY_20_MS
        self._charger.batt_fet_wvbus_enable = True
        self._charger.topoff = bq.TOPOFF_17_MIN
        self._charger.batt_overcurrent_threshold = bq.DISCHARGE_LIMIT_3A
        self._charger.interrupts_enable = False
        self._charger_adc_enable = False

        # Disable the charger watchdog to keep the charger in host mode and to
        # keep some registers from resetting to their POR values.
        self._charger.wd_enable = bq.WDT_DISABLED

        # TODO: Set NTC thermistor related charge settings

        # Capacity dependent initialization
        if self._batt_cap is not None and self._term_curr is not None:
            self._charger.term_current = self._term_curr
            self._charger.charging_current_limit = self._batt_cap // 2  # Set charge current limit to 1/2 C

        logger.info("Charger IC initialized")

    def _init_fuel_gauge(self, force: bool = False) -> None:
        if not self.is_batt_connected:
            logger.warning("Cannot initialize batt, no battery is connected")
            return

        if not force and self._is_fuel_gauge_initialized():
            logger.debug("Fuel gauge already initialized")
            return

        # Default initialization
        # NOTE: Sleep mode current consumption (1.3uA) is almost the same as normal mode (2uA). So
        # for now, this driver will always use normal mode.
        self._fuel_gauge.tsense_enable(False, False)
        self._fuel_gauge.power_mode = fg.PWR_MODE_NORMAL

        # Capacity and Profile dependent initialization
        # Initialize Fuel Gauge if a battery capacity & profile have been defined. If a battery is
        # not present on startup, this will fail.
        # Fuel Gauge initialization checks will therefore be made with subsequent commands.
        if self.is_batt_configured:
            apa = self._fuel_gauge.apa_calculate(self._batt_type, self._batt_cap)
            self._fuel_gauge.apa = apa
            self._fuel_gauge.batt_profile = self._batt_type
            self._fuel_gauge.batt_rsoc_init()
            self._fuel_gauge.termination_factor(self._term_curr, self._batt_cap)
            self._fuel_gauge.initialized = True
        else:
            logger.info("Skipping part of fuel gauge init. Missing battery config.")

        logger.info("Fuel gauge initialized")

    def _is_charger_initialized(self) -> bool:
        # Use term_curr value to determine if charger has been initialized. It's possible
        # a charge was initialized with a different battery capacity and since then a new battery
        # with a different capacity has been applied.
        if self._charger and self._term_curr is not None:
            return self._term_curr == self._charger.term_current
        return False

    def _is_fuel_gauge_initialized(self) -> bool:
        # Use the APA value to determine if the fuel gauge has been initialized properly.
        # It's possible a fuel gauge was initialized with a different battery capacity and since then a new battery
        # with a different capacity has been connected.
        if (
            self.is_batt_configured and
            self.is_batt_connected and
            self._fuel_gauge.apa == self._fuel_gauge.apa_calculate(self._batt_type, self._batt_cap)
        ):
            return True
        return False

    @property
    def _charger_adc_enable(self) -> bool:
        return self._charger.adc_enable(bq.ADC_IBUS)

    @_charger_adc_enable.setter
    def _charger_adc_enable(self, enable: bool):
        self._charger.adc_enable(bq.ADC_IBUS, enable)
        self._charger.adc_enable(bq.ADC_IBAT, enable)
        self._charger.adc_enable(bq.ADC_VBUS, enable)
        self._charger.adc_enable(bq.ADC_VBAT, enable)
        self._charger.adc_enable(bq.ADC_VSYS, enable)
        self._charger.adc_enable(bq.ADC_TS, enable)
        self._charger.adc_enable(bq.ADC_TDIE, enable)
        self._charger.adc_enable(bq.ADC_VPMID, enable)

        logger.info(f"Charger ADC {'enabled' if enable else 'disabled'}")

    def _charger_adc_update(self) -> None:
        if not self._charger_adc_enable:
            self._charger_adc_enable = True

        self._charger.adc_setup(True, bq.ADC_RATE_ONESHOT, bq.ADC_RESOLUTION_10, False, False)
        # TODO: Consider polling ADC_DONE_STAT to potentially reduce delay time
        time.sleep_ms(CHARGER_ADC_WAIT_TIME_MS)  # pylint: disable=no-member
        logger.debug("Charger ADC updated")

    @property
    def is_batt_configured(self) -> bool:
        return self._batt_type is not None and self._batt_cap is not None and self._term_curr is not None

    @property
    def is_batt_connected(self) -> bool:
        try:
            self._fuel_gauge.apa
        except fg.FuelGaugeError:
            return False
        return True

    def alarm_batt_low_charge(self, percent: int) -> None:
        pass

    def alarm_batt_low_volt(self, low_volt: int) -> None:
        pass

    def alarm_batt_high_volt(self, high_volt: int) -> None:
        pass

    def batt_configure(self, batt_type: BatteryType, capacity: int) -> None:
        """Update battery configuration.

        Will force a new initialization of both the battery charger and fuel gauge.

        Args:
            batt_type (BatteryType): New battery type.
            capacity (int): Battery capacity in mah.

        Raises:
            ValueError: Invalid battery capacity.
            ValueError: Invalid battery type.
        """
        if not fg.MIN_BATT_CAPACITY <= capacity <= fg.MAX_BATT_CAPACITY:
            raise ValueError(
                f"Invalid batt capacity ({capacity}). "
                f"Must be between {fg.MIN_BATT_CAPACITY} and {fg.MAX_BATT_CAPACITY} mah."
            )

        if not BatteryType.contains(batt_type):
            raise ValueError(f"Invalid battery type: {batt_type}. Supported types are: {BatteryType.print()}")

        self._battery_configure(batt_type, capacity)
        self._pin_sqt.on()
        self._init_charger(force=True)
        self._init_fuel_gauge(force=True)

    def batt_charge(self) -> int:
        """Get the estimated battery charge percentage.

        Raises:
            BatteryError: SQT power (I2C PU power) is not enabled.
            BatteryError: No battery is connected.
            BatteryError: No battery has been configured.

        Returns:
            int: Battery charge percentage.
        """
        if not self._pin_sqt.value():
            raise BatteryError("Can't get batt charge until SQT is enabled")
        if not self.is_batt_connected:
            raise BatteryError("Can't get batt charge, no battery is connected")
        if not self.is_batt_configured:
            raise BatteryError("Can't get batt charge, no battery has been configured")

        self._init_fuel_gauge()  # Will skip initialization if already initialized

        charge = self._fuel_gauge.batt_rsoc
        logger.debug(f"Estimated Batt Charge: {charge} %")
        return charge

    def batt_charging_enable(self, enable: bool) -> None:
        """Enable/Disable battery charging.

        Args:
            enable (bool): True to enable, False to disable.

        Raises:
            BatteryError: SQT power (I2C PU power) is not enabled.
            BatteryError: No battery has been configured.
        """
        if not self._pin_sqt.value():
            raise BatteryError("Can't update batt charging until SQT is enabled")
        if self._batt_cap is None:
            raise BatteryError("Can't update batt charging, no battery has been configured")

        self._charger.charging_enable = enable
        logger.debug(f"Batt charging set to: {enable}")

    def batt_charging_max_current(self, current: Optional[int] = None) -> Optional[int]:
        """Get/Set the battery's maximum charging current.

        Sets the current limit to the specified value in mA. If no value is provided, will return
        the current charging current limit.

        Args:
            current (int): Max current in mA. Defaults to None.

        Raises:
            BatteryError: SQT power (I2C PU power) is not enabled.
            BatteryError: No battery has been configured.

        Returns:
            Optional[init]: Max charging current, if none specified.
        """
        if not self._pin_sqt.value():
            raise BatteryError("Can't update batt charging until SQT is enabled")
        if self._batt_cap is None:
            raise BatteryError("Can't update batt charging, no battery has been configured")

        if current is None:
            return self._charger.charging_current_limit

        self._charger.charging_current_limit = current
        logger.debug(f"Batt max charge current set to: {current} mA")
        return None

    def batt_charging_status(self) -> str:
        """Get the current battery charging status string.

        Raises:
            BatteryError: SQT power (I2C PU power) is not enabled.
            BatteryError: No battery has been configured.

        Returns:
            str: Charging status
        """
        if not self._pin_sqt.value():
            raise BatteryError("Can't get batt charging status until SQT is enabled")
        if self._batt_cap is None:
            raise BatteryError("Can't get batt charging status, no battery has been configured")

        status = self._charger.charging_status
        if status == bq.CHARGE_STATUS_NOT:
            status = "Not Charging"
        elif status == bq.CHARGE_STATUS_TRICKLE:
            status = "Trickle"
        elif status == bq.CHARGE_STATUS_TAPER:
            status = "Taper"
        elif status == bq.CHARGE_STATUS_TOPOFF:
            status = "Topoff"
        else:
            status = "Unknown"

        logger.debug(f"Batt Charging Status: {status}")
        return status

    def batt_current(self) -> Optional[int]:
        """Get the most recent battery current in mA.

        Raises:
            BatteryError: SQT power (I2C PU power) is not enabled.
            BatteryError: No battery has been configured.

        Returns:
            Optional[int]: Battery current in mA if valid. None if invalid.
        """
        if not self._pin_sqt.value():
            raise BatteryError("Can't get batt current until SQT is enabled")
        if self._batt_cap is None:
            raise BatteryError("Can't get batt current, no battery has been configured")

        self._charger_adc_update()
        current = self._charger.batt_current

        # TODO: Verify negative value for discharge and positive for charge.
        logger.debug(f"Measured Batt Current: {current} mA")
        return current

    def batt_cycles(self) -> int:
        """Get the estimated number of battery cycles.

        Raises:
            BatteryError: SQT power (I2C PU power) is not enabled.
            BatteryError: No battery is connected.
            BatteryError: No battery has been configured.

        Returns:
            int: Number of battery cycles.
        """
        if not self._pin_sqt.value():
            raise BatteryError("Can't get batt cycles until SQT is enabled")
        if not self.is_batt_connected:
            raise BatteryError("Can't get batt cycles, no battery is connected")
        if not self.is_batt_configured:
            raise BatteryError("Can't get batt cycles, no battery has been configured")

        self._init_fuel_gauge()  # Will skip initialization if already initialized

        cycles = self._fuel_gauge.batt_cycles
        logger.debug(f"Estimated Batt Cycles: {cycles}")
        return cycles

    def batt_fuel_gauge_enable(self, enable: bool) -> None:
        """Enable/Disable the battery fuel gauge.

        Args:
            enable (bool): True to enable, False to disable.

        Raises:
            BatteryError: SQT power (I2C PU power) is not enabled.
            BatteryError: No battery is connected.
            BatteryError: No battery has been configured.
        """
        if not self._pin_sqt.value():
            raise BatteryError("Can't enable/disable fuel gauge until SQT is enabled")
        if not self.is_batt_connected:
            raise BatteryError("Can't enable/disable fuel gauge, no battery is connected")
        if not self.is_batt_configured:
            raise BatteryError("Can't enable/disable fuel gauge, no battery has been configured")

        # Perform initialization regardless since it is possible for the battery to be plugged
        # and unplugged throughout runtime.
        self._init_fuel_gauge(force=True)

        if enable:
            logger.info("Setting fuel gauge power mode to NORMAL")
            self._fuel_gauge.power_mode = fg.PWR_MODE_NORMAL
        else:
            logger.info("Setting fuel gauge power mode to SLEEP")
            self._fuel_gauge.power_mode = fg.PWR_MODE_SLEEP

    def batt_health(self) -> int:
        """Get estimated battery health percentage.

        Raises:
            BatteryError: SQT power (I2C PU power) is not enabled.
            BatteryError: No battery is connected.
            BatteryError: No battery has been configured.

        Returns:
            int: Battery health percentage
        """
        if not self._pin_sqt.value():
            raise BatteryError("Can't get batt health until SQT is enabled")
        if not self.is_batt_connected:
            raise BatteryError("Can't get batt health, no battery is connected")
        if not self.is_batt_configured:
            raise BatteryError("Can't get batt health, no battery has been configured")

        self._init_fuel_gauge()  # Will skip initialization if already initialized

        health = self._fuel_gauge.batt_soh
        logger.debug(f"Estimated Batt Health: {health} %")
        return health

    def batt_temp(self) -> float:
        pass

    def batt_temp_enable(self, enable: bool) -> None:
        pass

    def batt_time_left(self) -> Optional[int]:
        """Get estimated minutes left.

        If battery is charging, will return the estimated number of minutes until battery is fully charged.
        If battery is discharging, will return the estimated number of minutes until battery is fully discharged.

        NOTE: Checking this value will cause a delay of CHARGER_ADC_WAIT_TIME_MS

        Raises:
            BatteryError: SQT power (I2C PU power) is not enabled.
            BatteryError: No battery is connected.
            BatteryError: No battery has been configured.

        Returns:
            Optional[int]: Remaining battery minutes. None if estimation error.
        """
        if not self._pin_sqt.value():
            raise BatteryError("Can't get time left until SQT is enabled")
        if not self.is_batt_connected:
            raise BatteryError("Can't get time left, no battery is connected")
        if not self.is_batt_configured:
            raise BatteryError("Can't get time left, no battery has been configured")

        self._init_fuel_gauge()  # Will skip initialization if already initialized

        is_charging = (self.batt_current() or 0) > 0
        if is_charging:
            time_left = self._fuel_gauge.batt_time_to_full
        else:
            time_left = self._fuel_gauge.batt_time_to_empty

        if time_left == 0xFFFF:
            charge = self.batt_charge()
            if charge in (0, 100):
                time_left = 0
            else:
                logger.warning("Can't yet provide estimate for time left to full/empty.")
                time_left = None

        logger.debug(f"Time Left to full/empty: {time_left} min")
        return time_left

    def batt_voltage(self) -> int:
        """Get battery voltage.

        Attempts to read voltage from fuel gauge first. If that fails, will fall back to reading
        it from the battery charger. The latter takes longer in order to sample the ADC.

        Raises:
            BatteryError: SQT power (I2C PU power) is not enabled.
            BatteryError: No battery is connected.
            BatteryError: No battery has been configured.

        Returns:
            int: Battery voltage in mV.
        """
        if not self._pin_sqt.value():
            raise BatteryError("Can't get batt voltage until SQT is enabled")
        if not self.is_batt_connected:
            raise BatteryError("Can't get batt voltage, no battery is connected")
        if not self.is_batt_configured:
            raise BatteryError("Can't get batt voltage, no battery has been configured")

        try:
            self._init_fuel_gauge()  # Will skip initialization if already initialized
            voltage = self._fuel_gauge.batt_voltage
        except fg.FuelGaugeError as exc:
            logger.exception("Batt Voltage - FG is not available, switching to charger", exc_info=exc)
            self._charger_adc_update()
            voltage = self._charger.batt_voltage

        logger.debug(f"Measured Batt Voltage: {voltage} mV")
        return voltage

    def is_usb_connected(self) -> bool:
        """Checks if a usb-c cable is connected by checking if the bus voltage is greater than 0.

        Returns:
            bool: True if USB-C is connected. False if not.
        """
        if not self._pin_sqt.value():
            raise BatteryError("Can't check USB connection until SQT is enabled")

        self._charger_adc_update()
        return self._charger.bus_voltage > 0

    def led_on(self) -> None:
        """Turns ON user LED."""
        self._pin_led.on()

    def led_off(self) -> None:
        """Turns OFF user LED."""
        self._pin_led.off()

    def led_toggle(self) -> None:
        """Toggles user LED."""
        if self._pin_led.value():
            self.led_off()
        else:
            self.led_on()

    def mode_ship(self) -> None:
        pass

    def mode_shutdown(self) -> None:
        pass

    def power_3v3(self, enable: Optional[bool] = None) -> Optional[bool]:
        """Get/Set 3.3V power.

        If no value is specified, will return the current status.

        Args:
            enable (Optional[bool]): True to enable, False to disable. Defaults to None.

        Returns:
            Optional[bool]: Current 3.3V enable status, if none provided.
        """
        if enable is None:
            is_enabled = bool(self._pin_3v3.value())
            logger.info(f"3V3 Enable Read: {is_enabled}")
            return is_enabled

        self._pin_3v3.value(enable)
        logger.info(f"3V3 Enable Write: {enable}")
        return None

    def power_cycle(self) -> None:
        pass

    def power_feather_wing(self, enable: Optional[bool] = None) -> Optional[bool]:
        """Get/Set Feather Wing power.

        If no value is specified, will return the current status.

        Args:
            enable (Optional[bool]): True to enable, False to disable. Defaults to None.

        Returns:
            Optional[bool]: Current Feather Wing enable status, if none provided.
        """
        if enable is None:
            is_enabled = bool(self._pin_fw_rd.value())
            logger.info(f"FW Enable Read: {is_enabled}")
            return is_enabled

        self._pin_fw_wr(enable)
        logger.info(f"FW Enable Write: {enable}")
        return None

    def power_vsqt(self, enable: Optional[bool] = None) -> Optional[bool]:
        """Get/Set Stemma QT connector power.

        If no value is specified, will return the current status.

        Args:
            enable (Optional[bool]): True to enable, False to disable. Defaults to None.

        Returns:
            Optional[bool]: Current SQT enable status, if none provided.
        """
        if enable is None:
            is_enabled = bool(self._pin_sqt.value())
            logger.info(f"VSQT Enable Read: {is_enabled}")
            return is_enabled

        self._pin_sqt.value(enable)
        logger.info(f"VSQT Enable Write: {enable}")
        return None

    def register_button_irq(self, irq: Callable[[Pin], None]) -> None:
        """Register a callback to be invoked upon a button press.

        Args:
            irq (Callable[[Pin], None]): Button callback.
        """
        self._button.register_cb(irq)

    def supply_current(self) -> int:
        """Gets the most recent supply current.

        Raises:
            RuntimeError: SQT power (I2C PU power) is not enabled.

        Returns:
            int: Supply current in mA.
        """
        if not self._pin_sqt.value():
            raise RuntimeError("Can't get supply current until SQT is enabled")

        self._charger_adc_update()
        current = self._charger.bus_current
        logger.debug(f"Supply current: {current} ma")
        return current

    def supply_good(self) -> bool:
        """Checks if valid power input from battery or supply.

        Returns:
            bool: True if good, False if not.
        """
        is_good = self._pin_pg.value() == 0
        logger.debug(f"Power Good: {is_good}")
        return is_good

    def supply_voltage(self) -> int:
        """Gets the most recent supply voltage.

        Raises:
            RuntimeError: SQT power (I2C PU power) is not enabled.

        Returns:
            int: Supply voltage in mV.
        """
        if not self._pin_sqt.value():
            raise RuntimeError("Can't get supply voltage until SQT is enabled")

        self._charger_adc_update()
        voltage = self._charger.bus_voltage
        logger.debug(f"Supply voltage: {voltage} mv")
        return voltage
