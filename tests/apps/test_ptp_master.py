"""
test_ptp_master.py

Pytest for testing the ptp library via the use of miniot and a custom test SocketProtocol.
This is meant to be executed together with the test_ptp_periph.py test file, the two will communicate
with each other using os python's socket library.

To test:
1. Run the master file first in its own terminal session: `poetry run pytest -s test_ptp_master.py`
2. Run the periph file in its own terminal session: `poetry run pytest -s test_ptp_periph.py`

"""

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
from mp_libs.network import Network
from mp_libs.protocols.min_iot_protocol import MinIotProtocol, MinIotMessage
from mp_libs.protocols.serial_protocols import SerialProtocol
from mp_libs.protocols.espnow_protocol import EspnowProtocol
from mp_libs.time import ptp
from tests.apps.socket_protocol import SocketProtocol
from tests.fixtures.protocols_fixtures import protocol_mocks

# Constants
MTU_SIZE = 245
TIMEOUT_MSEC = 5000


def main():
    rtc = RTC()
    socket_protocol = SocketProtocol(is_client=False)
    espnow_protocol = EspnowProtocol(peers=[b'p\x04\x1d\xad|\xc0'])  # Underlying micropython epn class is mocked via protocol_mocks fixture
    espnow_protocol.epn._transport = socket_protocol  # Force mocked mp epn class to send data via sockets
    serial_protocol = SerialProtocol(transport=espnow_protocol, mtu_size_bytes=MTU_SIZE)
    miniot_protocol = MinIotProtocol(transport=serial_protocol)

    # pdb.set_trace()
    miniot_protocol.connect()
    print("PTP Master is connected")

    while True:
        rxed_packets: list[MinIotMessage] = []
        data_available = False

        # Receive data
        while not data_available:
            data_available = miniot_protocol.receive(rxed_packets)
            time.sleep(0.1)

        # Parse rx'ed packets
        for packet in rxed_packets:
            if ptp.is_ptp_msg(packet.msg):
                ptp_type, payload = ptp.parse_msg(packet.msg)
            else:
                print(f"Rx'ed unexpected message: {packet}")
                continue

            # Perform PTP sync
            print(f"ptp_type: {ptp_type}, payload: {payload}")
            if ptp_type == ptp.PtpMsg.SYNC_REQ:
                ptp.sequence_master(
                    miniot_protocol.send,
                    miniot_protocol.receive,
                    lambda miniot_msg: miniot_msg.msg,
                    TIMEOUT_MSEC,
                    num_sync_cycles=payload)

                print(f"now: {rtc.datetime()}")
                print(f"RTC now: {rtc.now()}")


@pytest.mark.apps
def test_main(protocol_mocks):
    main()
