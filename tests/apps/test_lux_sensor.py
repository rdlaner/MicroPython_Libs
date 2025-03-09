# Handle mocked modules first
from mp_libs import logging
mock_config = {
    # Platform Configuration

    # App Configuration
    "device_name": "light_sensor",
    "light_sleep_sec": 5,
    "deep_sleep_sec": 120,
    "upload_rate_sec": 120,
    "receive_rate_sec": 120,
    "receive_window_sec": 0.5,
    "time_sync_rate_sec": 600,
    "send_discovery_rate_sec": 600,
    "display_refresh_rate_sec": 120,
    "ambient_pressure": 1000,
    # "temp_offset_c": 4.4,
    "temp_offset_c": 0.5,
    "force_deep_sleep": True,
    "fake_sleep": True,
    "logging_level": logging.INFO,
    "log_to_fs": False,
    "log_to_buffer": False,
    "buffer_logging_level": logging.INFO,
    "debug": True,

    # Display Configuration
    "display_enable": False,

    # Transport Configuration
    # supported transports are: "espnow", "miniot", or "mqtt"
    "enable_network": True,
    "network_transport": "miniot",
    "network_prefix_id": "CO2",

    # Wifi configuration parameters
    "wifi_channel": 8,

    # Mqtt configuration parameters
    "topics": {
        "pressure_topic": "homeassistant/aranet/pressure",
        "cmd_topic": "homeassistant/number/generic-device/cmd",
    },
    "keep_alive_sec": 60,
    "keep_alive_margin_sec": 20,
    "connect_retries": 5,
    "recv_timeout_sec": 10,
    "socket_timeout_sec": 1,

    # Espnow configuration parameters
    "epn_peer_mac": b'p\x04\x1d\xad|\xc0',
    "epn_channel": 1,
    "epn_timeout_ms": 0
}
import sys
sys.modules["config"].config = mock_config

# Standard imports
import pdb
import time
from machine import RTC

# Third party imports
import pytest

# Local imports
from config import config
from mp_libs.network import Network
from mp_libs.protocols.min_iot_protocol import MinIotProtocol
from mp_libs.protocols.serial_protocols import SerialProtocol
from mp_libs.sensors import veml7700
from mp_libs.time import ptp
from tests.apps.socket_protocol import SocketProtocol
from tests.mocks.mock_sensors import MockVEML7000

# Constants
MTU_SIZE = 20

# Globals
logger = logging.getLogger("app")
logger.setLevel(config["logging_level"])
logging.getLogger().setLevel(config["logging_level"])


def main():
    # Sensors init
    logger.debug("Sensors init...")
    lux_sensor = MockVEML7000()
    logger.info(f"Lux gain:             {lux_sensor.gain(veml7700.ALS_GAIN_1_8)}")
    logger.info(f"Lux integration time: {lux_sensor.integration_time(veml7700.ALS_50MS)}")
    logger.info(f"Lux resolution:       {lux_sensor.resolution()}")

    # Network init
    socket_protocol = SocketProtocol(is_client=True)
    serial_protocol = SerialProtocol(transport=socket_protocol, mtu_size_bytes=MTU_SIZE)
    net = MinIotProtocol(transport=serial_protocol)
    net.connect()

    # Homeassistant init
    # TBD

    logger.info("Starting light reading...")
    while True:
        # Get lux data
        lux = lux_sensor.lux()

        # Send data
        net.send(msg=lux, topic="/test/float")
        time.sleep(0.2)
        net.send(msg=b"\x01\x02\x04\x04\x05", topic="/test/binary")

        # Report
        logger.info(f"Light {lux:.2f} lux")

        # Sleep
        time.sleep(2)


@pytest.mark.apps
def test_main():
    main()
