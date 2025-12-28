"""
Espnow protocols tests

To run all tests: `poetry run pytest -n auto protocols/test_espnow_protocols.py`
"""
# Standard imports
import random
from typing import Any, List, Optional, Tuple

# Third party imports
import pytest
from pytest_mock import MockerFixture

# Local imports
from mp_libs import logging
from mp_libs.protocols import InterfaceProtocol
from mp_libs.protocols import espnow_protocol as ep
from tests.mocks.mock_protocols import MockESPNow, MockWifiProtocol
from tests.fixtures.protocols_fixtures import protocol_mocks

# Constants
NUM_REPEATED_TESTS = 50
NUM_PACKETS_TO_GENERATE = 50


################################################################################
# Helper Functions
################################################################################
def generate_packet_data(size: int = ep.EPN_PACKET_MAX_SIZE - ep.EPN_PACKET_HDR_SIZE_BYTES - 1) -> bytes:
    return bytes(random.randint(0, 255) for _ in range(size))


################################################################################
# EspnowPacket Tests
################################################################################
@pytest.mark.parametrize("data_size", range(0, 255))
def test_espnow_packet_serdes_happy_path(data_size):
    cmds = [ep.EpnCmds.CMD_SCAN_REQ, ep.EpnCmds.CMD_SCAN_RESP, ep.EpnCmds.CMD_PASS]

    for cmd in cmds:
        data = generate_packet_data(size=data_size)
        packet = ep.EspnowPacket(cmd, data)
        des_packet = packet.deserialize(packet.serialize())

        assert packet.header == des_packet.header
        assert packet.cmd == des_packet.cmd
        assert packet.payload == des_packet.payload
        assert packet.serialize() == des_packet.serialize()


@pytest.mark.parametrize("test_input", [
    (ep.EpnCmds.CMD_SCAN_REQ, b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0A"),
    (ep.EpnCmds.CMD_SCAN_RESP, b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0A"),
    (ep.EpnCmds.CMD_PASS, b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0A")
])
def test_espnow_packet_serialize_happy_path(test_input):
    packet = ep.EspnowPacket(test_input[0], test_input[1])
    expected = ep.EPN_PACKET_DELIM + test_input[0].to_bytes(1) + len(test_input[1]).to_bytes(1) + test_input[1]

    assert packet.cmd == test_input[0]
    assert packet.payload == test_input[1]
    assert packet.serialize() == expected


def test_espnow_packet_serialize_invalid_cmd():
    cmd = ep.EpnCmds.CMD_PASS + 1
    data = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0A"

    with pytest.raises(ep.EspnowPacketError):
        _ = ep.EspnowPacket(cmd, data)


def test_espnow_packet_serialize_too_large_payload():
    size = random.randint(256, 512)
    data = generate_packet_data(size)

    with pytest.raises(ep.EspnowPacketError):
        _ = ep.EspnowPacket(ep.EpnCmds.CMD_PASS, data)


def test_espnow_packet_serialize_zero_payload():
    cmd = ep.EpnCmds.CMD_PASS
    packet = ep.EspnowPacket(cmd, b"")

    assert packet.cmd == cmd
    assert packet.payload == b""
    assert packet.header.payload_size == 0
    assert len(packet.serialize()) == ep.EPN_PACKET_HDR_SIZE_BYTES


@pytest.mark.parametrize("data_size", range(0, 255))
def test_espnow_packet_len(data_size):
    data = generate_packet_data(size=data_size)
    packet = ep.EspnowPacket(ep.EpnCmds.CMD_PASS, data)
    assert len(packet) == len(data) + ep.EPN_PACKET_HDR_SIZE_BYTES


################################################################################
# EspnowProtocol Tests
################################################################################
def test_espnow_protocol_init_no_peers(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    epn_proto = ep.EspnowProtocol(peers=[], hostname=hostname, channel=channel)

    wifi_proto_mock.assert_called()
    espnow_mock.assert_called_once()
    assert epn_proto.wifi.is_connected() is False
    assert epn_proto.wifi._hostname == hostname
    assert epn_proto.wifi._channel == channel
    assert epn_proto.epn._active is True
    assert epn_proto.epn._rxbuf_size == ep.EspnowProtocol.ESPNOW_BUFFER_SIZE_BYTES
    assert epn_proto.epn._timeout_ms == ep.DEFAULT_TIMEOUT_MS
    assert epn_proto.peers == []
    assert epn_proto.epn._peers == []


def test_espnow_protocol_init_peers_list(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)

    wifi_proto_mock.assert_called()
    espnow_mock.assert_called_once()
    assert epn_proto.wifi.is_connected() is False
    assert epn_proto.wifi._hostname == hostname
    assert epn_proto.wifi._channel == channel
    assert epn_proto.epn._active is True
    assert epn_proto.epn._rxbuf_size == ep.EspnowProtocol.ESPNOW_BUFFER_SIZE_BYTES
    assert epn_proto.epn._timeout_ms == ep.DEFAULT_TIMEOUT_MS
    assert epn_proto.peers == peers
    assert epn_proto.epn._peers == peers


def test_espnow_protocol_init_single_peer(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = b'p\x04\x1d\xad|\xc0'
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)

    wifi_proto_mock.assert_called()
    espnow_mock.assert_called_once()
    assert epn_proto.wifi.is_connected() is False
    assert epn_proto.wifi._hostname == hostname
    assert epn_proto.wifi._channel == channel
    assert epn_proto.epn._active is True
    assert epn_proto.epn._rxbuf_size == ep.EspnowProtocol.ESPNOW_BUFFER_SIZE_BYTES
    assert epn_proto.epn._timeout_ms == ep.DEFAULT_TIMEOUT_MS
    assert len(epn_proto.peers) == 1
    assert epn_proto.peers[0] == peers
    assert epn_proto.epn._peers[0] == peers


def test_espnow_protocol_init_with_already_added_peer(mocker: MockerFixture, protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)

    wifi_proto_mock.assert_called()
    espnow_mock.assert_called_once()
    assert epn_proto.wifi.is_connected() is False
    assert epn_proto.wifi._hostname == hostname
    assert epn_proto.wifi._channel == channel
    assert epn_proto.epn._active is True
    assert epn_proto.epn._rxbuf_size == ep.EspnowProtocol.ESPNOW_BUFFER_SIZE_BYTES
    assert epn_proto.epn._timeout_ms == ep.DEFAULT_TIMEOUT_MS
    assert epn_proto.peers == peers
    assert epn_proto.epn._peers == peers

    peers = b'p\x04\x1d\xad|\xc0'
    logger_spy = mocker.spy(logging.getLogger("espnow-protocol"), "warning")
    _ = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)

    assert logger_spy.call_count == 1
    for args, kwargs in logger_spy.call_args_list:
        assert args[0] == "Peer has already been added, skipping. Peers: b'p\\x04\\x1d\\xad|\\xc0'"


def test_espnow_protocol_connect_first_time(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)

    epn_proto.connect()

    assert epn_proto.epn._active is True
    assert epn_proto.peers == peers
    assert epn_proto.epn._peers == peers


def test_espnow_protocol_reconnect(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)
    assert epn_proto.epn._config_call_count == 1
    assert epn_proto.epn._peers == peers

    epn_proto.connect()
    assert epn_proto.epn._active is True

    epn_proto.disconnect()
    assert epn_proto.epn._active is False
    assert epn_proto.epn._peers == []

    epn_proto.connect()
    assert epn_proto.epn._active is True
    assert epn_proto.epn._config_call_count == 2
    assert epn_proto.epn._peers == peers


def test_espnow_protocol_disconnect(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)
    assert epn_proto.epn._active is True

    epn_proto.disconnect()
    assert epn_proto.epn._active is False
    assert epn_proto.epn._peers == []


def test_espnow_protocol_isconnected(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)

    epn_proto.connect()
    assert epn_proto.is_connected() is True

    epn_proto.disconnect()
    assert epn_proto.is_connected() is False


def test_espnow_protocol_process_packet_cmd_pass(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)
    data = generate_packet_data()
    packet = ep.EspnowPacket(ep.EpnCmds.CMD_PASS, data)

    result = epn_proto.process_packet(packet)
    assert result == packet.payload


def test_espnow_protocol_process_packet_cmd_scan_req(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)
    data = generate_packet_data()
    packet = ep.EspnowPacket(ep.EpnCmds.CMD_SCAN_REQ, data)

    result = epn_proto.process_packet(packet)
    assert result == b""
    assert len(epn_proto.epn._sent_msgs) == 1
    assert isinstance(epn_proto.epn._sent_msgs[0], bytes)
    assert (ep.EspnowPacket.deserialize(epn_proto.epn._sent_msgs[0])).cmd == ep.EpnCmds.CMD_SCAN_RESP


def test_espnow_protocol_process_packet_cmd_scan_resp(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)
    data = generate_packet_data()
    packet = ep.EspnowPacket(ep.EpnCmds.CMD_SCAN_RESP, data)

    result = epn_proto.process_packet(packet)
    assert result == packet


def test_espnow_protocol_process_packet_invalid_cmd(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)
    data = generate_packet_data()
    packet = ep.EspnowPacket(ep.EpnCmds.CMD_PASS, data)

    # Corrupt cmd
    new_header = ep.EspnowPacketHeader(
        delim=ep.EPN_PACKET_DELIM,
        cmd=250,
        payload_size=len(data)
    )
    packet.header = new_header
    packet.cmd = 250
    packet._serialize()

    with pytest.raises(ep.EspnowPacketError):
        _ = epn_proto.process_packet(packet)


@pytest.mark.repeat(NUM_REPEATED_TESTS)
def test_espnow_protocol_send_packet_happy_path(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)
    packet = ep.EspnowPacket(ep.EpnCmds.CMD_PASS, generate_packet_data())

    result = epn_proto.send(packet)

    assert result is True
    assert epn_proto.epn._sent_msgs[-1] == packet.serialize()


def test_espnow_protocol_send_packet_too_large(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)

    data = generate_packet_data(size=ep.EPN_PACKET_MAX_SIZE + 1)
    packet = ep.EspnowPacket(ep.EpnCmds.CMD_PASS, data)

    with pytest.raises(ep.EspnowError):
        _ = epn_proto.send(packet)


@pytest.mark.repeat(NUM_REPEATED_TESTS)
def test_espnow_protocol_send_msg_happy_path(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)
    msg = generate_packet_data()

    result = epn_proto.send(msg)

    assert result is True
    assert ep.EspnowPacket.deserialize(epn_proto.epn._sent_msgs[-1]).payload == msg


def test_espnow_protocol_send_msg_too_large(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)

    msg = generate_packet_data(size=ep.EPN_PACKET_MAX_SIZE + 1)

    with pytest.raises(ep.EspnowError):
        _ = epn_proto.send(msg)


@pytest.mark.repeat(NUM_REPEATED_TESTS)
def test_espnow_protocol_send_receive_single_happy_path(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)
    msg = generate_packet_data()

    rx_msgs = []
    send_result = epn_proto.send(msg)
    receive_result = epn_proto.receive(rx_msgs)

    assert send_result is True
    assert receive_result is True
    assert rx_msgs[0] == msg


@pytest.mark.repeat(NUM_REPEATED_TESTS)
def test_espnow_protocol_send_receive_multiple_happy_path(protocol_mocks):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)

    send_msgs = []
    num_msgs = random.randint(1, 100)
    for _ in range(num_msgs):
        msg = generate_packet_data()
        send_msgs.append(msg)
        epn_proto.send(msg)

    rx_msgs = []
    while epn_proto.receive(rx_msgs) is True:
        ...

    for i, msg in enumerate(rx_msgs):
        assert msg == send_msgs[i]


def test_espnow_protocol_send_receive_fail_no_recover(protocol_mocks, mocker):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    msg = generate_packet_data()
    logger_spy = mocker.spy(logging.getLogger("espnow-protocol"), "exception")
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)

    rx_msgs = []
    epn_proto.epn.set_rx_exc(True)
    epn_proto.send(msg)

    with pytest.raises(ep.EspnowError):
        _ = epn_proto.receive(rx_msgs)

    assert logger_spy.call_count == 1
    for args, _ in logger_spy.call_args_list:
        assert args[0] == "Failed receiving espnow packet"


def test_espnow_protocol_send_receive_fail_and_recover(protocol_mocks, mocker):
    wifi_proto_mock, espnow_mock = protocol_mocks
    hostname = "test_hostname"
    channel = 0
    peers = [b'p\x04\x1d\xad|\xc0', b'p\x14\x03\xbc|\xc0', b'p\xff\x12\xef|\xc0']
    msg = generate_packet_data()
    logger_spy = mocker.spy(logging.getLogger("espnow-protocol"), "exception")
    epn_proto = ep.EspnowProtocol(peers=peers, hostname=hostname, channel=channel)

    old_espnow_calls = espnow_mock.call_count
    old_wifi_calls = wifi_proto_mock.call_count

    rx_msgs = []
    epn_proto.epn.set_rx_exc(True)
    epn_proto.send(msg)
    rx_result = epn_proto.receive(rx_msgs, recover=True)

    assert rx_result is False
    # New espnow and wifi instances should have been constructed during recovery
    assert espnow_mock.call_count == old_espnow_calls + 1
    assert wifi_proto_mock.call_count == old_wifi_calls + 1
    assert epn_proto.wifi._hostname == hostname
    assert epn_proto.wifi._channel == channel
    assert epn_proto.epn._active is True
    assert epn_proto.epn._rxbuf_size == ep.EspnowProtocol.ESPNOW_BUFFER_SIZE_BYTES
    assert epn_proto.epn._timeout_ms == ep.DEFAULT_TIMEOUT_MS
    assert epn_proto.peers == peers
    assert epn_proto.epn._peers == peers
    assert logger_spy.call_count == 1
    for args, _ in logger_spy.call_args_list:
        assert args[0] == "Failed receiving espnow packet"
