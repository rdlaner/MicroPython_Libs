import gc
import machine
from micropython import const
from mp_libs.nano_gui.drivers.epaper.epd29 import EPD as SSD

SPI_MOSI_PIN_NUM = const(35)
SPI_MISO_PIN_NUM = const(37)
SPI_CLK_PIN_NUM = const(36)
EINK_CS_PIN_NUM = const(1)
EINK_DC_PIN_NUM = const(3)
EINK_BUSY_PIN_NUM = const(6)
SD_CS_PIN_NUM = const(33)
SRAM_CS_PIN_NUM = const(38)

pin_dc = machine.Pin(EINK_DC_PIN_NUM, machine.Pin.OUT, value=1)
pin_cs = machine.Pin(EINK_CS_PIN_NUM, machine.Pin.OUT, value=1)
pin_busy = machine.Pin(EINK_BUSY_PIN_NUM, machine.Pin.IN)
pin_reset = None

spi = machine.SPI(2, baudrate=4_000_000)
gc.collect()  # Precaution before instantiating framebuf
ssd = SSD(spi, pin_cs, pin_dc, pin_reset, pin_busy)  # Create a display instance
