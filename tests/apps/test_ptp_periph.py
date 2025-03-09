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
    "logging_level": logging.DEBUG,
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
from mp_libs.network import Network
from mp_libs.protocols.min_iot_protocol import MinIotProtocol
from mp_libs.protocols.serial_protocols import SerialProtocol
from mp_libs.protocols.espnow_protocol import EspnowProtocol
from mp_libs.time import ptp
from tests.apps.socket_protocol import SocketProtocol
from tests.fixtures.protocols_fixtures import protocol_mocks

# Constants
MTU_SIZE = 245
TIMEOUT_MSEC = 5000
NUM_SYNC_CYCLES = 15


def main():
    rtc = RTC()
    socket_protocol = SocketProtocol(is_client=True)
    espnow_protocol = EspnowProtocol(peers=[b'p\x04\x1d\xad|\xc0'])  # Underlying epn class is mocked via protocol_mocks fixture
    espnow_protocol.epn._transport = socket_protocol
    serial_protocol = SerialProtocol(transport=espnow_protocol, mtu_size_bytes=MTU_SIZE)
    miniot_protocol = MinIotProtocol(transport=serial_protocol)

    # pdb.set_trace()
    miniot_protocol.connect()
    print("PTP Periph is connected")

    while True:
        # Perform periph sequence
        timestamps = ptp.sequence_periph(
            miniot_protocol,
            lambda miniot_msg: miniot_msg.msg,
            TIMEOUT_MSEC,
            initiate_sync=True,
            num_sync_cycles=NUM_SYNC_CYCLES)

        # Calculate offsets
        offsets = [ptp.calculate_offset(t1, t2, t3, t4) for t1, t2, t3, t4 in timestamps]

        print(f"timestamps: {timestamps}")
        print(f"offsets: {offsets}")

        # Process offsets
        ave_offset = ptp.process_offsets(offsets)

        # Update time
        rtc.offset(str(ave_offset).encode())

        print(f"ave_offset: {ave_offset}")
        print(f"ave_offset bytes: {str(ave_offset).encode()}")
        print(f"now: {rtc.datetime()}")
        print(f"RTC now: {rtc.now()}")

        time.sleep(15)


@pytest.mark.apps
def test_main(protocol_mocks):
    main()
