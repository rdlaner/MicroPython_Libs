"""
VEML7700 Lux Sensor Driver

TODO: Do the gain, it, etc. values persist on the sensor between deep sleep cycles?
"""
# Standard imports
import struct
from machine import I2C
from micropython import const
from time import sleep_ms

# Third party imports
from mp_libs import logging

# Local imports
try:
    from config import config  # type: ignore
except ImportError:
    config = {"logging_level": logging.INFO}

# Ambient light sensor gain index
ALS_GAIN_1_8 = const(1)
ALS_GAIN_1_4 = const(2)
ALS_GAIN_1 = const(3)
ALS_GAIN_2 = const(4)
ALS_GAIN_READ = const(5)

# Ambient light integration time index
ALS_25MS = const(1)
ALS_50MS = const(2)
ALS_100MS = const(3)
ALS_200MS = const(4)
ALS_400MS = const(5)
ALS_800MS = const(6)
ALS_INTEGRATION_READ = const(7)

# Default I2C address
I2C_ADDR = const(0x10)

# Globals
logger = logging.getLogger("VEML7700")
logger.setLevel(config["logging_level"])


class VEML7700:
    """Driver for the VEML7700 ambient light sensor.

    I2C register write and read 16 bits in this order: LSB, MSB
    """

    # Command Codes, aka I2C register addresses
    CMD_CODE_0 = const(0)
    CMD_CODE_1 = const(1)
    CMD_CODE_2 = const(2)
    CMD_CODE_3 = const(3)
    CMD_CODE_4 = const(4)
    CMD_CODE_5 = const(5)
    CMD_CODE_6 = const(6)

    _gain_reg_to_actual = {
        const(2): const(0.125),
        const(3): const(0.25),
        const(0): const(1),
        const(1): const(2),
    }

    _gain_index_to_reg = {
        ALS_GAIN_1_8: const(2),
        ALS_GAIN_1_4: const(3),
        ALS_GAIN_1: const(0),
        ALS_GAIN_2: const(1),
    }

    _it_reg_to_actual = {
        const(0xC): const(25),
        const(0x8): const(50),
        const(0x0): const(100),
        const(0x1): const(200),
        const(0x2): const(400),
        const(0x3): const(800),
    }

    _it_index_to_reg = {
        ALS_25MS: const(0xC),
        ALS_50MS: const(0x8),
        ALS_100MS: const(0x0),
        ALS_200MS: const(0x1),
        ALS_400MS: const(0x2),
        ALS_800MS: const(0x3),
    }

    def __init__(self, i2c: I2C, address: int = I2C_ADDR):
        """Init

        Args:
            i2c (I2C): I2C bus.
            address (int, optional): I2C device address. Defaults to I2C_ADDR.

        Raises:
            RuntimeError: Failure to enable device
        """
        self._i2c = i2c
        self._address = address
        self._reg_buffer = bytearray(2)
        self._gain_idx = None
        self._it_idx = None
        for _ in range(3):
            try:
                self.enable(wait=1)
                break
            except OSError:
                pass
        else:
            raise RuntimeError("Unable to enable VEML7700 device")

        # Default values
        self.gain(ALS_GAIN_1_4)
        self.integration_time(ALS_100MS)

        logger.info("Initialized VEML7700")

    def disable(self, wait: int = 5) -> None:
        """Disable/Shutdown ALS.

        Args:
            wait (int, optional): Wait time in msec after starting shutdown. Defaults to 5.
        """
        lsb_bit_mask = 0x01
        self._i2c.readfrom_mem_into(
            self._address, self.CMD_CODE_0, self._reg_buffer)

        self._reg_buffer[0] |= lsb_bit_mask
        self._i2c.writeto_mem(self._address, self.CMD_CODE_0, self._reg_buffer)

        if wait:
            sleep_ms(5)

    def enable(self, wait: int = 5) -> None:
        """Enable/Wakeup ALS.

        Args:
            wait (int, optional): Wait time in msec after starting wakeup. Defaults to 5.
        """
        lsb_bit_mask = 0x01
        self._i2c.readfrom_mem_into(
            self._address, self.CMD_CODE_0, self._reg_buffer)

        self._reg_buffer[0] &= ~lsb_bit_mask
        self._i2c.writeto_mem(self._address, self.CMD_CODE_0, self._reg_buffer)

        if wait:
            sleep_ms(5)

    def gain(self, gain: int = ALS_GAIN_READ) -> int:
        """Read/Write and return ALS gain value

        To read the ALS gain, pass ALS_GAIN_READ.
        To write the ALS gain, pass any other ALS_GAIN_XXX value.

        Args:
            gain (int, optional): Gain. Defaults to ALS_GAIN_READ.

        Returns:
            int: Current gain value.
        """
        msb_bit_mask = 0x18
        msb_bit_shift = 3

        if gain != ALS_GAIN_READ:
            self.disable()
            self._i2c.readfrom_mem_into(self._address, self.CMD_CODE_0, self._reg_buffer)
            self._reg_buffer[1] &= ~msb_bit_mask
            self._reg_buffer[1] |= (self._gain_index_to_reg[gain] << msb_bit_shift)
            self._i2c.writeto_mem(self._address, self.CMD_CODE_0, self._reg_buffer)
            self.enable()
            self._gain_idx = gain
            sleep_ms(50)

        self._i2c.readfrom_mem_into(self._address, self.CMD_CODE_0, self._reg_buffer)
        reg = (self._reg_buffer[1] & msb_bit_mask) >> msb_bit_shift

        return self._gain_reg_to_actual[reg]

    def integration_time(self, integration: int = ALS_INTEGRATION_READ) -> int:
        """Read/Write and return ALS integration time.

        To read the ALS integration time, pass ALS_INTEGRATION_READ.
        To write the ALS integration time, pass any other ALS_XXXMS value.

        Args:
            integration (int, optional): Integration time. Defaults to ALS_INTEGRATION_READ.

        Returns:
            int: Current integration time.
        """
        bit_mask = 0x3C0
        bit_shift = 6

        if integration != ALS_INTEGRATION_READ:
            self.disable()
            self._i2c.readfrom_mem_into(self._address, self.CMD_CODE_0, self._reg_buffer)
            reg = (self._reg_buffer[1] << 8) | (self._reg_buffer[0])
            reg &= ~bit_mask
            reg |= (self._it_index_to_reg[integration] << bit_shift)
            self._reg_buffer[1] = (reg >> 8) & 0xFF
            self._reg_buffer[0] = reg & 0xFF
            self._i2c.writeto_mem(self._address, self.CMD_CODE_0, self._reg_buffer)
            self.enable()
            self._it_idx = integration
            sleep_ms(self._it_reg_to_actual[self._it_index_to_reg[self._it_idx]] + 10)

        self._i2c.readfrom_mem_into(self._address, self.CMD_CODE_0, self._reg_buffer)
        reg = (((self._reg_buffer[1] << 8) | (self._reg_buffer[0])) & bit_mask) >> bit_shift

        return self._it_reg_to_actual[reg]

    def light_raw(self) -> int:
        """Read and return raw ALS light value

        Returns:
            int: Raw light counts.
        """
        self._i2c.readfrom_mem_into(self._address, self.CMD_CODE_4, self._reg_buffer)
        counts = struct.unpack("<H", self._reg_buffer)[0]

        logger.debug(f"Gain: {self.gain()}")
        logger.debug(f"IT: {self.integration_time()}ms")
        logger.debug(f"Res: {self.resolution()}")
        logger.debug(f"Counts: {counts}")
        logger.debug(f"gain-idx: {self._gain_idx}")
        logger.debug(f"it_idx: {self._it_idx}")

        return counts

    def lux(self) -> float:
        """Read and return light value in lux.

        Returns:
            float: Current lux reading.
        """
        lux = self.resolution() * self.light_raw()

        logger.debug(f"Gain: {self.gain()}")
        logger.debug(f"IT: {self.integration_time()}ms")
        logger.debug(f"Res: {self.resolution()}")
        logger.debug(f"Lux: {lux}")

        return lux

    def lux_auto_cal(self) -> float:
        """Auto calibrate gain and integration time for reading lux

        NOTE: This takes several seconds to perform.

        Returns:
            float: Current lux reading.
        """
        # Initial gain and integration time
        self.integration_time(ALS_100MS)
        self.gain(ALS_GAIN_1_8)
        sleep_ms(800)
        counts = self.light_raw()

        # Calibrate low-end
        while ((self._gain_idx != ALS_GAIN_2) or (self._it_idx != ALS_800MS)) and (counts <= 100):
            if self._gain_idx < ALS_GAIN_2:
                self.gain(self._gain_idx + 1)
            elif self._it_idx < ALS_800MS:
                self.integration_time(self._it_idx + 1)

            sleep_ms(800)
            counts = self.light_raw()

        # Calibrate high-end
        while (self._it_idx != ALS_25MS) and (counts >= 10000):
            self.integration_time(self._it_idx - 1)

            sleep_ms(800)
            counts = self.light_raw()

        return self.lux()

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
