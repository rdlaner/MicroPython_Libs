import gc
import machine
from micropython import const
from mp_libs.nano_gui.drivers.epaper.epd29 import EPD as SSD

SPI_DUMMY_PIN_NUM = const(7)
SPI_MOSI_PIN_NUM = const(35)
SPI_MISO_PIN_NUM = const(37)
SPI_CLK_PIN_NUM = const(36)
EINK_CS_PIN_NUM = const(1)
EINK_DC_PIN_NUM = const(3)
EINK_BUSY_PIN_NUM = const(6)
SD_CS_PIN_NUM = const(33)
SRAM_CS_PIN_NUM = const(38)

pin_soft_dummy_mosi = machine.Pin(SPI_DUMMY_PIN_NUM, machine.Pin.OUT)
pin_soft_clk = machine.Pin(SPI_CLK_PIN_NUM, machine.Pin.OUT)
pin_soft_miso = machine.Pin(SPI_MOSI_PIN_NUM)  # Use physical MOSI pin as input
pin_dc = machine.Pin(EINK_DC_PIN_NUM, machine.Pin.OUT, value=1)
pin_cs = machine.Pin(EINK_CS_PIN_NUM, machine.Pin.OUT, value=1)
pin_busy = machine.Pin(EINK_BUSY_PIN_NUM, machine.Pin.IN)
pin_reset = None


def create_spi():
    """Creates SPI instance for this display"""
    return machine.SPI(2, baudrate=4_000_000)


def create_soft_spi():
    """Creates a SoftSPI instance for this display

    This is only needed when reading from the display since we need to bang out clock signals
    without putting data on the MOSI line. Therefore, this MOSI pin must be a dummy pin.

    This can also be handled in hardware with a resistor. If done this way, there is no need for
    a SoftSpi implementation:
    https://www.totalphase.com/support/articles/200350046-interfacing-with-3-wire-spi/
    """
    return machine.SoftSPI(baudrate=1_000_000, sck=pin_soft_clk, miso=pin_soft_miso, mosi=pin_soft_dummy_mosi)


gc.collect()  # Precaution before instantiating framebuf
ssd = SSD(create_spi, pin_cs, pin_dc, pin_reset, pin_busy, create_soft_spi=create_soft_spi)
