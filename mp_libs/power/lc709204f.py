"""LC709204F Fuel Gauge Driver

TODO: Add alarm support API
"""
# pylint: disable=import-error, wrong-import-order

# Standard imports
from machine import I2C
from micropython import const

# Third party imports
from mp_libs import logging

# Local imports
try:
    from config import config  # type: ignore
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants
CRC_TABLE = bytearray([
    0x00, 0x07, 0x0E, 0x09, 0x1C, 0x1B, 0x12, 0x15,
    0x38, 0x3F, 0x36, 0x31, 0x24, 0x23, 0x2A, 0x2D,
    0x70, 0x77, 0x7E, 0x79, 0x6C, 0x6B, 0x62, 0x65,
    0x48, 0x4F, 0x46, 0x41, 0x54, 0x53, 0x5A, 0x5D,
    0xE0, 0xE7, 0xEE, 0xE9, 0xFC, 0xFB, 0xF2, 0xF5,
    0xD8, 0xDF, 0xD6, 0xD1, 0xC4, 0xC3, 0xCA, 0xCD,
    0x90, 0x97, 0x9E, 0x99, 0x8C, 0x8B, 0x82, 0x85,
    0xA8, 0xAF, 0xA6, 0xA1, 0xB4, 0xB3, 0xBA, 0xBD,
    0xC7, 0xC0, 0xC9, 0xCE, 0xDB, 0xDC, 0xD5, 0xD2,
    0xFF, 0xF8, 0xF1, 0xF6, 0xE3, 0xE4, 0xED, 0xEA,
    0xB7, 0xB0, 0xB9, 0xBE, 0xAB, 0xAC, 0xA5, 0xA2,
    0x8F, 0x88, 0x81, 0x86, 0x93, 0x94, 0x9D, 0x9A,
    0x27, 0x20, 0x29, 0x2E, 0x3B, 0x3C, 0x35, 0x32,
    0x1F, 0x18, 0x11, 0x16, 0x03, 0x04, 0x0D, 0x0A,
    0x57, 0x50, 0x59, 0x5E, 0x4B, 0x4C, 0x45, 0x42,
    0x6F, 0x68, 0x61, 0x66, 0x73, 0x74, 0x7D, 0x7A,
    0x89, 0x8E, 0x87, 0x80, 0x95, 0x92, 0x9B, 0x9C,
    0xB1, 0xB6, 0xBF, 0xB8, 0xAD, 0xAA, 0xA3, 0xA4,
    0xF9, 0xFE, 0xF7, 0xF0, 0xE5, 0xE2, 0xEB, 0xEC,
    0xC1, 0xC6, 0xCF, 0xC8, 0xDD, 0xDA, 0xD3, 0xD4,
    0x69, 0x6E, 0x67, 0x60, 0x75, 0x72, 0x7B, 0x7C,
    0x51, 0x56, 0x5F, 0x58, 0x4D, 0x4A, 0x43, 0x44,
    0x19, 0x1E, 0x17, 0x10, 0x05, 0x02, 0x0B, 0x0C,
    0x21, 0x26, 0x2F, 0x28, 0x3D, 0x3A, 0x33, 0x34,
    0x4E, 0x49, 0x40, 0x47, 0x52, 0x55, 0x5C, 0x5B,
    0x76, 0x71, 0x78, 0x7F, 0x6A, 0x6D, 0x64, 0x63,
    0x3E, 0x39, 0x30, 0x37, 0x22, 0x25, 0x2C, 0x2B,
    0x06, 0x01, 0x08, 0x0F, 0x1A, 0x1D, 0x14, 0x13,
    0xAE, 0xA9, 0xA0, 0xA7, 0xB2, 0xB5, 0xBC, 0xBB,
    0x96, 0x91, 0x98, 0x9F, 0x8A, 0x8D, 0x84, 0x83,
    0xDE, 0xD9, 0xD0, 0xD7, 0xC2, 0xC5, 0xCC, 0xCB,
    0xE6, 0xE1, 0xE8, 0xEF, 0xFA, 0xFD, 0xF4, 0xF3
])

# Battery capacity to APA lookup. Must be sorted in ascending order by capacity.
APA_TABLE = [
    (const(50), const(0x13)),
    (const(100), const(0x15)),
    (const(200), const(0x18)),
    (const(500), const(0x21)),
    (const(1000), const(0x2D)),
    (const(2000), const(0x3A)),
    (const(3000), const(0x3F)),
    (const(4000), const(0x42)),
    (const(5000), const(0x44)),
    (const(6000), const(0x45)),
]

I2C_ADDR = const(0x0B)

# Registers
REG_TIME_TO_EMPTY = const(0x03)
REG_BEFORE_RSOC = const(0x04)
REG_TIME_TO_FULL = const(0x05)
REG_TSENSE1 = const(0x06)
REG_INIT_RSOC = const(0x07)
REG_CELL_TEMP = const(0x08)
REG_CELL_VOLT = const(0x09)
REG_CURR_DIR = const(0x0A)
REG_APA = const(0x0B)
REG_APT = const(0x0C)
REG_RSOC = const(0x0D)
REG_TSENSE2 = const(0x0E)
REG_ITE = const(0x0F)
REG_VERSION = const(0x11)
REG_BATT_PROF = const(0x12)
REG_ALRM_LOW_RSOC = const(0x13)
REG_ALRM_LOW_CELL_VOLT = const(0x14)
REG_PWR_MODE = const(0x15)
REG_THERM_STATUS = const(0x16)
REG_CYCLE_COUNT = const(0x17)
REG_BATT_STATUS = const(0x19)
REG_TERM_CURRENT = const(0x1C)
REG_ALRM_HIGH_CELL_VOLT = const(0x1F)
REG_ALRM_LOW_TEMP = const(0x20)
REG_SOH = const(0x32)

# Battery Profiles (Change of Parameter)
BATT_PROF_3V7_4V2 = const(0x00)
BATT_PROF_UR18650ZY = const(0x01)
BATT_PROF_ICR18650_26H = const(0x02)
BATT_PROF_3V8_4V35 = const(0x03)
BATT_PROF_3V85_4V4 = const(0x04)

# Battery Alarms/Status
BATT_ALRM_HIGH_CELL_VOLT = const(15)
BATT_ALRM_HIGH_TEMP = const(12)
BATT_ALRM_LOW_CELL_VOLT = const(11)
BATT_ALRM_LOW_RSOC = const(9)
BATT_ALRM_LOW_TEMP = const(8)
BATT_STATUS_INITIALIZED = const(7)
BATT_STATUS_DISCHARGING = const(6)

# Power Modes
PWR_MODE_NORMAL = const(0x01)
PWR_MODE_SLEEP = const(0X02)

# Max/Min Values
MIN_VOLT_ALARM = const(2500)
MAX_VOLT_ALARM = const(5000)
MAX_BATT_CAPACITY = const(6000)
MIN_BATT_CAPACITY = const(50)
MAX_TERM_FACTOR = const(300)
MIN_TERM_FACTOR = const(2)


# Globals
logger = logging.getLogger("LC709204F")
logger.setLevel(config["logging_level"])


class LC709204F():
    """LC709204F Battery Fuel Gauge Driver"""
    def __init__(self, i2c: I2C) -> None:
        self._i2c = i2c

    def _crc8(self, data: bytearray) -> int:
        val = 0
        for pos in data:
            val = CRC_TABLE[val ^ pos]
        return val

    def _read_reg(self, reg: int) -> int:
        data_raw = self._i2c.readfrom_mem(I2C_ADDR, reg, 3)
        data = int.from_bytes(data_raw[0:2], "little")

        cmd = bytearray(5)
        cmd[0] = I2C_ADDR << 1  # Write byte
        cmd[1] = reg            # Register
        cmd[2] = cmd[0] | 0x01  # Read byte
        cmd[3] = data_raw[0]
        cmd[4] = data_raw[1]
        actual_crc = data_raw[2]
        expected_crc = self._crc8(cmd)

        if actual_crc != expected_crc:
            raise RuntimeError(f"I2C read failed CRC. Expected: {hex(expected_crc)}, Actual: {hex(actual_crc)}")

        logger.debug(f"Read Reg Success - Reg: {hex(reg)}, Data: {hex(data)}, CRC: {hex(actual_crc)}")
        return data

    def _write_reg(self, reg: int, data: int) -> None:
        cmd = bytearray(5)
        cmd[0] = I2C_ADDR << 1  # Write byte
        cmd[1] = reg            # Register
        cmd[2] = data & 0x00FF
        cmd[3] = (data & 0xFF00) >> 8
        cmd[4] = self._crc8(cmd[0:4])
        self._i2c.writeto_mem(I2C_ADDR, reg, cmd[2:])

        logger.debug(f"Write Reg Success - Reg: {hex(reg)}, Data: {hex(data)}, CRC: {hex(cmd[4])}")

    def _set_volt_alarm(self, reg: int, voltage: int) -> None:
        pass

    def _clear_alarm(self, alarm: int) -> None:
        pass

    @property
    def apa(self) -> int:
        """Get the current APA value for the fuel gauge.

        Returns:
            int: Current APA value.
        """
        return self._read_reg(REG_APA)

    @apa.setter
    def apa(self, value: int) -> None:
        """Set the APA value for the fuel gauge.

        APA value should be calculated by the `apa_calculate` method.

        Args:
            value (int): APA value.
        """
        self._write_reg(REG_APA, value)

    def apa_calculate(self, batt_profile: int, batt_cap: int) -> int:
        """Calculate the APA value based on the battery profile and capacity provided.

        Args:
            batt_profile (int): Battery profile. One of the BATT_PROF_XXX options.
            batt_cap (int): Battery capacity mah.

        Raise:
            ValueError: Invalid battery profile.
            ValueError: Invalid battery capacity.

        Returns:
            int: APA value.
        """
        if not MIN_BATT_CAPACITY <= batt_cap <= MAX_BATT_CAPACITY:
            raise ValueError(f"Invalid batt capacity: {batt_cap}")

        if batt_profile not in (BATT_PROF_3V7_4V2, BATT_PROF_UR18650ZY, BATT_PROF_ICR18650_26H,
                                BATT_PROF_3V8_4V35, BATT_PROF_3V85_4V4):
            raise ValueError(f"Invalid profile: {batt_profile}")

        if batt_profile == BATT_PROF_ICR18650_26H:
            return 0x0606

        if batt_profile == BATT_PROF_UR18650ZY:
            return 0x1010

        # Iterate through APA table to find the two rows (curr, prev) that most
        # closely match the target capacity
        prev = APA_TABLE[0]
        for curr in (APA_TABLE):
            cap = curr[0]

            if batt_cap == cap:
                prev = curr
                break
            if batt_cap < cap:
                break
            prev = curr

        if prev == curr:
            apa = (curr[1] << 8) | curr[1]
        else:
            # Use linear interpolation to find the approximate APA value
            lower_apa = prev[1]
            lower_cap = prev[0]
            upper_apa = curr[1]
            upper_cap = curr[0]
            apa = lower_apa + (upper_apa - lower_apa) * ((batt_cap - lower_cap) / (upper_cap - lower_cap))
            apa = round(apa)
            apa = (apa << 8) | apa

        return apa

    @property
    def batt_cycles(self) -> int:
        """Get battery cycle count

        Returns:
            int: Cycle count
        """
        return self._read_reg(REG_CYCLE_COUNT)

    @property
    def batt_profile(self) -> int:
        """Get the current battery profile.

        Returns:
            int: Current battery profile. See one of the BATT_PROF_XXX options.
        """
        return self._read_reg(REG_BATT_PROF)

    @batt_profile.setter
    def batt_profile(self, batt_profile: int):
        """Set the battery profile

        Args:
            batt_profile (int): Battery profile. See one of the BATT_PROF_XXX options.

        Raises:
            ValueError: Invalid battery profile.
        """
        if batt_profile not in (BATT_PROF_3V7_4V2, BATT_PROF_UR18650ZY, BATT_PROF_ICR18650_26H,
                                BATT_PROF_3V8_4V35, BATT_PROF_3V85_4V4):
            raise ValueError(f"Invalid profile: {batt_profile}")

        self._write_reg(REG_BATT_PROF, batt_profile)

    @property
    def batt_rsoc(self) -> int:
        """Get battery Relative State of Charge (RSOC) percentage.

        Returns:
            int: RSOC value
        """
        return self._read_reg(REG_RSOC)

    @property
    def batt_soh(self) -> int:
        """Get battery State of Health (SOH) percentage.

        Returns:
            int: SOH value
        """
        return self._read_reg(REG_SOH)

    @property
    def batt_time_to_empty(self) -> int:
        """Get estimated time to battery empty in minutes

        Returns:
            int: Time to empty minutes
        """
        return self._read_reg(REG_TIME_TO_EMPTY)

    @property
    def batt_time_to_full(self) -> int:
        """Get estimated time to full in minutes

        Returns:
            int: Time to full minutes
        """
        return self._read_reg(REG_TIME_TO_FULL)

    @property
    def batt_voltage(self) -> int:
        """Return current cell voltage in mV

        Returns:
            int: Cell voltage (mV)
        """
        return self._read_reg(REG_CELL_VOLT)

    @property
    def initialized(self) -> bool:
        """Get the fuel gauge's initialization status.

        Returns:
            bool: Current initialization status.
        """
        curr_status = self._read_reg(REG_BATT_STATUS)
        return bool(curr_status & (1 << BATT_STATUS_INITIALIZED))

    @initialized.setter
    def initialized(self, value: bool) -> None:
        """Set the fuel gauge's initialization status.

        Args:
            value (bool): True to set as initialized, False as uninitialized.
        """
        # Init bit resets to 1 after a POR. Therefore, set to 0 to indicate initialization.
        curr_status = self._read_reg(REG_BATT_STATUS)
        if value:
            new_status = curr_status & ~(1 << BATT_STATUS_INITIALIZED)
        else:
            new_status = curr_status | (1 << BATT_STATUS_INITIALIZED)

        self._write_reg(REG_BATT_STATUS, new_status)

    @property
    def power_mode(self) -> int:
        """Get fuel gauge power mode

        Returns:
            int: Current power mode. See POWER_MODE_XXX values.
        """
        return self._read_reg(REG_PWR_MODE)

    @power_mode.setter
    def power_mode(self, mode: int) -> None:
        """Set fuel gauge power mode

        Args:
            mode (int): Set power mode to this value. See POWER_MODE_XXX values.

        Raises:
            ValueError: If selected power mode is unsupported
        """
        if mode not in (PWR_MODE_NORMAL, PWR_MODE_SLEEP):
            raise ValueError(f"Set Pwr Mode Failed. Invalid mode: {mode}")

        self._write_reg(REG_PWR_MODE, mode)

    def termination_factor(self, term_curr: float, batt_cap: int) -> None:
        """Set termination factor based on target termination current and battery capacity

        Termination factor is the desired termination current (mah) represented in units of
        0.01C. For example, If the desired termination current for a 3000mah battery is 60ma,
        the termination factor is 2.

        Args:
            term_curr (float): Desired termination current in mA
            batt_cap (int): Battery capacity in mAh

        Raises:
            ValueError: Invalid battery capacity
            ValueError: If termination factor is outside min/max range
        """
        if batt_cap < MIN_BATT_CAPACITY or batt_cap > MAX_BATT_CAPACITY:
            raise ValueError(f"Invalid batt capacity: {batt_cap}")

        factor = int(term_curr // (batt_cap * 0.01))

        if factor < MIN_TERM_FACTOR or factor > MAX_TERM_FACTOR:
            raise ValueError(f"Set Term Failed. Invalid factor: {factor}")

        self._write_reg(REG_TERM_CURRENT, factor)

    def tsense_enable(self, en_tsense1: bool, en_tsense2: bool) -> None:
        """Enable/Disable TSense1 and/or Tsense2

        Args:
            en_tsense1 (bool): Enable/Disable TSense1
            en_tsense2 (bool): Enable/Disable TSense2
        """
        enable_status = en_tsense2 << 1 | en_tsense1
        self._write_reg(REG_THERM_STATUS, enable_status)

    def version(self) -> int:
        """Get Fuel Gauge internal version code

        Returns:
            int: Version
        """
        return self._read_reg(REG_VERSION)
