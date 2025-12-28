"""
Serial protocols tests

To run all tests: `poetry run pytest -n auto protocols/test_serial_protocols.py`

"""
# Standard imports
import ast
import pdb
import random
import string
from collections import Counter
from math import ceil
from typing import Any, List, Optional

# Third party imports
import pytest
from pytest_mock import MockerFixture

# Local imports
from mp_libs import logging
from mp_libs.protocols import InterfaceProtocol
from mp_libs.protocols import serial_protocols as sp

# Constants
NUM_REPEATED_TESTS = 50
NUM_PACKETS_TO_GENERATE = 50


################################################################################
# Helper Functions
################################################################################
def generate_msg_data(data_type: type, low=0, high=255, size=50):
    if data_type in (int, float):
        return [data_type(random.uniform(low, high)) for _ in range(size)]

    if data_type is bytes:
        return bytes(random.randint(0, 255) for _ in range(size))

    if data_type is bytearray:
        return bytearray(random.randint(0, 255) for _ in range(size))

    if data_type is str:
        return "".join([random.choice(string.ascii_letters) for _ in range(size)])

    if data_type is bool:
        return [random.choice([True, False]) for _ in range(size)]

    return []


def generate_packets(
    num_packets,
    max_payload_size=65536,
    max_msg_id=255,
    max_packet_id=255,
    max_packets_per_msg=255,
    min_payload_size=0,
    min_msg_id=0,
    min_packet_id=0,
    min_packets_per_msg=0
) -> List[sp.SerialPacket]:
    packets = []
    for _ in range(num_packets):
        payload_size = random.randint(min_payload_size, max_payload_size)
        msg_id = random.randint(min_msg_id, max_msg_id)
        packet_id = random.randint(min_packet_id, max_packet_id)
        packets_per_msg = random.randint(min_packets_per_msg, max_packets_per_msg)
        encoded = random.choice([True, False])

        packets.append(sp.SerialPacket(
            bytes(random.getrandbits(8) for _ in range(payload_size)),
            msg_id,
            packet_id,
            packets_per_msg,
            encoded
        ))

    return packets


################################################################################
# SerialPacket Tests
################################################################################
@pytest.mark.parametrize("test_input, expected", [
    ((b"123456789", 0, 0, 10, False), b'<SER>\x00\x00\n\t\x00\x00123456789}\xb3\x08@'),
    ((b"ABCDEFGHI", 0, 0, 10, False), b'<SER>\x00\x00\n\t\x00\x00ABCDEFGHI\x1b\x1c\x97B')
])
def test_serial_packet_construction(test_input, expected):
    header = sp.SerialPacketHeader(
        delim=sp.SERIAL_PACKET_DELIM,
        msg_id=test_input[1],
        packet_id=test_input[2],
        packets_per_msg=test_input[3],
        payload_size=len(test_input[0]),
        encoded=test_input[4])
    packet = sp.SerialPacket(*test_input)

    assert packet.header == header
    assert packet.payload == test_input[0]
    assert packet._serialized_packet == expected


@pytest.mark.parametrize("packet", generate_packets(NUM_PACKETS_TO_GENERATE))
def test_serial_packet_serdes(packet):
    deserialized = packet.deserialize(packet.serialize())

    assert packet.header == deserialized.header
    assert packet.payload == deserialized.payload
    assert packet.crc == deserialized.crc
    assert packet._serialized_packet == deserialized._serialized_packet


def test_serial_packet_serialize_failure_payload_size():
    with pytest.raises(sp.SerialPacketException):
        _ = generate_packets(1, min_payload_size=65536, max_payload_size=65536)[0]


def test_serial_packet_serialize_failure_msg_id():
    with pytest.raises(sp.SerialPacketException):
        _ = generate_packets(1, min_msg_id=256, max_msg_id=256)[0]


def test_serial_packet_serialize_failure_packet_id():
    with pytest.raises(sp.SerialPacketException):
        _ = generate_packets(1, min_packet_id=256, max_packet_id=256)[0]


def test_serial_packet_serialize_failure_packets_per_msg():
    with pytest.raises(sp.SerialPacketException):
        _ = generate_packets(1, min_packets_per_msg=256, max_packets_per_msg=256)[0]


def test_serial_packet_deserialize_success():
    serialized_packet = b"<SER>\xdf\xe2\xcf\x10\x00\x01\x88\x9f\xe3\xa9\x8c\xfa\x01\x84\x1e\xca\x989=\x98\xee\xc2|\x15\xf3\xeb"
    packet = sp.SerialPacket.deserialize(serialized_packet)

    assert packet.header.delim == sp.SERIAL_PACKET_DELIM
    assert packet.header.msg_id == 223
    assert packet.header.packet_id == 226
    assert packet.header.packets_per_msg == 207
    assert packet.header.payload_size == 16
    assert packet.header.encoded == 1
    assert packet.payload == b'\x88\x9f\xe3\xa9\x8c\xfa\x01\x84\x1e\xca\x989=\x98\xee\xc2'
    assert packet.crc == 0xEBF3157C


def test_serial_packet_deserialize_failure_header_delim():
    serialized_packet = b"[SER>\xdf\xe2\xcf\x10\x00\x01\x88\x9f\xe3\xa9\x8c\xfa\x01\x84\x1e\xca\x989=\x98\xee\xc2|\x15\xf3\xeb"
    with pytest.raises(sp.SerialPacketException):
        sp.SerialPacket.deserialize(serialized_packet)


def test_serial_packet_deserialize_failure_header_msg_id():
    serialized_packet = b"<SER>\xdaf\xe2\xcf\x10\x00\x01\x88\x9f\xe3\xa9\x8c\xfa\x01\x84\x1e\xca\x989=\x98\xee\xc2|\x15\xf3\xeb"
    with pytest.raises(sp.SerialPacketException):
        sp.SerialPacket.deserialize(serialized_packet)


def test_serial_packet_deserialize_failure_header_packets_id():
    serialized_packet = b"<SER>\xda\xea2\xcf\x10\x00\x01\x88\x9f\xe3\xa9\x8c\xfa\x01\x84\x1e\xca\x989=\x98\xee\xc2|\x15\xf3\xeb"
    with pytest.raises(sp.SerialPacketException):
        sp.SerialPacket.deserialize(serialized_packet)


def test_serial_packet_deserialize_failure_header_packets_per_msg():
    serialized_packet = b"<SER>\xdf\xe2\xcaf\x10\x00\x01\x88\x9f\xe3\xa9\x8c\xfa\x01\x84\x1e\xca\x989=\x98\xee\xc2|\x15\xf3\xeb"
    with pytest.raises(sp.SerialPacketException):
        sp.SerialPacket.deserialize(serialized_packet)


def test_serial_packet_deserialize_failure_header_payload_size():
    serialized_packet = b"<SER>\xdf\xe2\xcf\x10\x01\x88\x9f\xe3\xa9\x8c\xfa\x01\x84\x1e\xca\x989=\x98\xee\xc2|\x15\xf3\xeb"
    with pytest.raises(sp.SerialPacketException):
        sp.SerialPacket.deserialize(serialized_packet)


def test_serial_packet_deserialize_failure_header_encoded():
    serialized_packet = b"<SER>\xdf\xe2\xcf\x10\x00\x01a\x88\x9f\xe3\xa9\x8c\xfa\x01\x84\x1e\xca\x989=\x98\xee\xc2|\x15\xf3\xeb"
    with pytest.raises(sp.SerialPacketException):
        sp.SerialPacket.deserialize(serialized_packet)


def test_serial_packet_deserialize_failure_crc():
    serialized_packet = b"<SER>\xdf\xe2\xcf\x10\x00\x01\x88\x9f\xe3\xa9\x8c\xfa\x01\x84\x1e\xca\x989=\x98\xee\xc2|\x15\xf3\xea"
    with pytest.raises(sp.SerialPacketException):
        sp.SerialPacket.deserialize(serialized_packet)


################################################################################
# SerialMessage Tests
################################################################################
def test_serial_msg_fail_direct_instantiation():
    payload_size = random.randint(0, 65536)
    data = bytes(random.getrandbits(8) for _ in range(payload_size))
    with pytest.raises(sp.SerialMessageException):
        sp.SerialMessage(data, 240, 0)


def test_serial_msg_small_mtu():
    data = generate_msg_data(int, high=65536)
    with pytest.raises(sp.SerialMessageException):
        _ = sp.SerialMessage.create_msg_from_data(data, sp.SERIAL_PACKET_META_DATA_SIZE_BYTES)


@pytest.mark.repeat(NUM_REPEATED_TESTS)
@pytest.mark.parametrize("data_type", [int, float, bool])
def test_serial_msg_create_from_data_encoded_types(data_type):
    data = generate_msg_data(data_type, size=50)
    mtu_size_bytes = 50
    msg_from_data = sp.SerialMessage.create_msg_from_data(data, mtu_size_bytes)
    msg_from_packets = sp.SerialMessage.create_msg_from_packets(msg_from_data.packets)

    assert msg_from_data.packets[0].header.encoded is True
    assert data == ast.literal_eval(msg_from_data.data) == ast.literal_eval(msg_from_packets.data)
    assert isinstance(msg_from_data.data, str)
    assert isinstance(msg_from_packets.data, str)
    assert msg_from_data.msg_id == msg_from_packets.msg_id
    assert len(msg_from_data.packets) == len(msg_from_packets.packets)
    for i, pkt in enumerate(msg_from_data):
        assert id(pkt) == id(msg_from_packets.packets[i])
        assert pkt.header == msg_from_packets.packets[i].header
        assert pkt.payload == msg_from_packets.packets[i].payload
        assert pkt.crc == msg_from_packets.packets[i].crc
        assert pkt._serialized_packet == msg_from_packets.packets[i]._serialized_packet


@pytest.mark.repeat(NUM_REPEATED_TESTS)
def test_serial_msg_create_from_data_str():
    data = generate_msg_data(str, high=65536)
    mtu_size_bytes = random.randint(sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1, 50)
    msg_from_data = sp.SerialMessage.create_msg_from_data(data, mtu_size_bytes)
    msg_from_packets = sp.SerialMessage.create_msg_from_packets(msg_from_data.packets)

    assert data == msg_from_data.data
    assert msg_from_data.packets[0].header.encoded is True
    assert msg_from_data.data == msg_from_packets.data
    assert msg_from_data.msg_id == msg_from_packets.msg_id
    assert len(msg_from_data.packets) == len(msg_from_packets.packets)
    for i, pkt in enumerate(msg_from_data):
        assert id(pkt) == id(msg_from_packets.packets[i])
        assert pkt.header == msg_from_packets.packets[i].header
        assert pkt.payload == msg_from_packets.packets[i].payload
        assert pkt.crc == msg_from_packets.packets[i].crc
        assert pkt._serialized_packet == msg_from_packets.packets[i]._serialized_packet


@pytest.mark.repeat(NUM_REPEATED_TESTS)
@pytest.mark.parametrize("data_type", [bytes, bytearray])
def test_serial_msg_create_from_data_bytes_bytearray(data_type):
    data = generate_msg_data(data_type, high=65536)
    mtu_size_bytes = random.randint(sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1, 50)
    msg_from_data = sp.SerialMessage.create_msg_from_data(data, mtu_size_bytes)
    msg_from_packets = sp.SerialMessage.create_msg_from_packets(msg_from_data.packets)

    assert data == msg_from_data.data
    assert msg_from_data.packets[0].header.encoded is False
    assert msg_from_data.data == msg_from_packets.data
    assert msg_from_data.msg_id == msg_from_packets.msg_id
    assert len(msg_from_data.packets) == len(msg_from_packets.packets)
    for i, pkt in enumerate(msg_from_data):
        assert id(pkt) == id(msg_from_packets.packets[i])
        assert pkt.header == msg_from_packets.packets[i].header
        assert pkt.payload == msg_from_packets.packets[i].payload
        assert pkt.crc == msg_from_packets.packets[i].crc
        assert pkt._serialized_packet == msg_from_packets.packets[i]._serialized_packet


@pytest.mark.repeat(NUM_REPEATED_TESTS)
@pytest.mark.parametrize("data_type", [int, float, bool])
def test_serial_msg_create_from_data_deepcopy_encoded_types(data_type):
    data = generate_msg_data(data_type, size=50)
    mtu_size_bytes = 50
    msg_from_data = sp.SerialMessage.create_msg_from_data(data, mtu_size_bytes)
    msg_from_packets = sp.SerialMessage.create_msg_from_packets(msg_from_data.packets, deepcopy=True)

    assert msg_from_data.packets[0].header.encoded is True
    assert data == ast.literal_eval(msg_from_data.data) == ast.literal_eval(msg_from_packets.data)
    assert isinstance(msg_from_data.data, str)
    assert isinstance(msg_from_packets.data, str)
    assert msg_from_data.msg_id == msg_from_packets.msg_id
    assert len(msg_from_data.packets) == len(msg_from_packets.packets)
    for i, pkt in enumerate(msg_from_data):
        assert id(pkt) != id(msg_from_packets.packets[i])
        assert pkt.header == msg_from_packets.packets[i].header
        assert pkt.payload == msg_from_packets.packets[i].payload
        assert pkt.crc == msg_from_packets.packets[i].crc
        assert pkt._serialized_packet == msg_from_packets.packets[i]._serialized_packet


@pytest.mark.repeat(NUM_REPEATED_TESTS)
def test_serial_msg_create_from_data_deepcopy_str():
    data = generate_msg_data(str, high=65536)
    mtu_size_bytes = random.randint(sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1, 50)
    msg_from_data = sp.SerialMessage.create_msg_from_data(data, mtu_size_bytes)
    msg_from_packets = sp.SerialMessage.create_msg_from_packets(msg_from_data.packets, deepcopy=True)

    assert data == msg_from_data.data
    assert msg_from_data.packets[0].header.encoded is True
    assert msg_from_data.data == msg_from_packets.data
    assert msg_from_data.msg_id == msg_from_packets.msg_id
    assert len(msg_from_data.packets) == len(msg_from_packets.packets)
    for i, pkt in enumerate(msg_from_data):
        assert id(pkt) != id(msg_from_packets.packets[i])
        assert pkt.header == msg_from_packets.packets[i].header
        assert pkt.payload == msg_from_packets.packets[i].payload
        assert pkt.crc == msg_from_packets.packets[i].crc
        assert pkt._serialized_packet == msg_from_packets.packets[i]._serialized_packet


@pytest.mark.repeat(NUM_REPEATED_TESTS)
@pytest.mark.parametrize("data_type", [bytes, bytearray])
def test_serial_msg_create_from_data_deepcopy_bytes_bytearray(data_type):
    data = generate_msg_data(data_type, high=65536)
    mtu_size_bytes = random.randint(sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1, 50)
    msg_from_data = sp.SerialMessage.create_msg_from_data(data, mtu_size_bytes)
    msg_from_packets = sp.SerialMessage.create_msg_from_packets(msg_from_data.packets, deepcopy=True)

    assert data == msg_from_data.data
    assert msg_from_data.packets[0].header.encoded is False
    assert msg_from_data.data == msg_from_packets.data
    assert msg_from_data.msg_id == msg_from_packets.msg_id
    assert len(msg_from_data.packets) == len(msg_from_packets.packets)
    for i, pkt in enumerate(msg_from_data):
        assert id(pkt) != id(msg_from_packets.packets[i])
        assert pkt.header == msg_from_packets.packets[i].header
        assert pkt.payload == msg_from_packets.packets[i].payload
        assert pkt.crc == msg_from_packets.packets[i].crc
        assert pkt._serialized_packet == msg_from_packets.packets[i]._serialized_packet


@pytest.mark.parametrize("msg_size", range(0, 1000 + 10, 10))
@pytest.mark.parametrize("mtu_size", range(0, 255 + 5, 5))
def test_serial_msg_create_from_data_various_msg_and_mtu_sizes(msg_size, mtu_size):
    if msg_size == 0:
        return
    if mtu_size <= sp.SERIAL_PACKET_META_DATA_SIZE_BYTES:
        return

    payload_size = mtu_size - sp.SERIAL_PACKET_META_DATA_SIZE_BYTES
    num_packets = ceil(msg_size / payload_size)
    data = generate_msg_data(bytes, size=msg_size)

    if num_packets >= 256:
        with pytest.raises(sp.SerialPacketException):
            msg = sp.SerialMessage.create_msg_from_data(data, mtu_size)
        return

    msg = sp.SerialMessage.create_msg_from_data(data, mtu_size)

    expected_packet_data = []
    for i in range(num_packets):
        expected_packet_data.append(data[i * payload_size:(i * payload_size) + payload_size])

    assert num_packets == len(msg.packets)
    assert msg.data == data
    for i, pkt in enumerate(msg.packets):
        assert sp.SERIAL_PACKET_DELIM == pkt.header.delim
        assert msg.msg_id == pkt.header.msg_id
        assert i == pkt.header.packet_id
        assert num_packets == pkt.header.packets_per_msg
        assert len(expected_packet_data[i]) == pkt.header.payload_size
        assert expected_packet_data[i] == pkt.payload


def test_serial_msg_create_from_data_invalid_payload_size():
    data = generate_msg_data(bytes, size=0)
    with pytest.raises(sp.SerialMessageException, match="Data cannot be None."):
        _ = sp.SerialMessage.create_msg_from_data(data, sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1)


@pytest.mark.parametrize("mtu_size_bytes", range(0, sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1))
def test_serial_msg_create_from_data_invalid_mtu_size(mtu_size_bytes):
    data = generate_msg_data(bytes, size=10)
    with pytest.raises(sp.SerialMessageException, match="MTU size is too small"):
        _ = sp.SerialMessage.create_msg_from_data(data, mtu_size_bytes)


def test_serial_msg_create_from_data_msg_id_inc():
    cycles = sp.SERIAL_MSG_ID_MAX * 5
    start_msg_id = sp.SerialMessage._global_msg_id_counter

    for i in range(cycles):
        msg_id = (start_msg_id + i) % sp.SERIAL_MSG_ID_MAX
        data = generate_msg_data(bytes, size=100)
        msg = sp.SerialMessage.create_msg_from_data(data, sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1)

        assert msg_id == msg.msg_id
        assert (msg_id + 1) % sp.SERIAL_MSG_ID_MAX == sp.SerialMessage._global_msg_id_counter


def test_serial_msg_iterator():
    data = generate_msg_data(bytes, size=100)
    msg = sp.SerialMessage.create_msg_from_data(data, sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1)

    for i, pkt in enumerate(msg):
        assert id(msg.packets[i]) == id(pkt)


def test_serial_msg_misssing_packets():
    data = generate_msg_data(bytes, size=100)
    msg = sp.SerialMessage.create_msg_from_data(data, sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1)
    packets = msg.packets
    index = random.randint(0, len(packets) - 1)
    packets.pop(index)

    with pytest.raises(sp.SerialMessageException):
        _ = sp.SerialMessage.create_msg_from_packets(packets, check=True)


def test_serial_msg_invalid_msg_id():
    num_packets = 10
    packets = generate_packets(num_packets)

    # generate_packets will use a random value for msg_id for each packet. Odds are very unlikely
    # that all packets will have the same msg_id, but check just in case.
    data_ready = False
    while not data_ready:
        msg_id = packets[0].header.msg_id
        for pkt in packets:
            if pkt.header.msg_id != msg_id:
                data_ready = True
                break

        if not data_ready:
            packets = generate_packets(num_packets)

    with pytest.raises(sp.SerialMessageException):
        _ = sp.SerialMessage.create_msg_from_packets(packets, check=True)


################################################################################
# SerialProtocol Tests
################################################################################
class MockTransport(InterfaceProtocol):
    def __init__(self, rx_packets: Optional[List] = None) -> None:
        self.rx_packets = rx_packets if rx_packets is not None else []

    def connect(self, **kwargs) -> bool:
        return True

    def disconnect(self, **kwargs) -> bool:
        return True

    def is_connected(self) -> bool:
        return True

    def receive(self, rxed_data: List, **kwargs) -> bool:
        data = bytearray(b"".join(self.rx_packets))
        for i in range(0, len(data), 37):
            rxed_data.append(data[i:i + 37])

        return True

    def recover(self, **kwargs) -> bool:
        return True

    def scan(self, **kwargs) -> List[Any]:
        return []

    def send(self, msg, **kwargs) -> bool:
        self.rx_packets.append(msg)

        return True


@pytest.mark.repeat(NUM_REPEATED_TESTS)
@pytest.mark.parametrize("data_type", [bytes, bytearray])
@pytest.mark.parametrize("mtu_size", range(sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1, 256))
def test_protocol_send_receive_byte_types(data_type, mtu_size):
    msg_size = random.randint(50, 5000)
    data = generate_msg_data(data_type, size=msg_size)
    transport = MockTransport()
    protocol = sp.SerialProtocol(transport, mtu_size)
    payload_size = mtu_size - sp.SERIAL_PACKET_META_DATA_SIZE_BYTES
    num_packets = ceil(msg_size / payload_size)

    if num_packets >= 256:
        with pytest.raises(sp.SerialPacketException):
            protocol.send(data)
        return

    # Send data
    protocol.send(data)

    # Receive same data
    rx_data = []
    protocol.receive(rx_data)

    assert data == rx_data[0]
    assert len(rx_data) == 1


@pytest.mark.repeat(NUM_REPEATED_TESTS)
@pytest.mark.parametrize("data_type", [int, float, bool])
@pytest.mark.parametrize("mtu_size", range(sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1, 256))
def test_protocol_send_receive_encoded_types(data_type, mtu_size):
    msg_size = random.randint(50, 5000)
    data = generate_msg_data(data_type, size=msg_size)
    encoded_msg_size = len(str(data).encode("utf-8"))
    transport = MockTransport()
    protocol = sp.SerialProtocol(transport, mtu_size)
    payload_size = mtu_size - sp.SERIAL_PACKET_META_DATA_SIZE_BYTES
    num_packets = ceil(encoded_msg_size / payload_size)

    if num_packets >= 256:
        with pytest.raises(sp.SerialPacketException):
            protocol.send(data)
        return

    # Send data
    protocol.send(data)

    # Receive same data
    rx_data = []
    protocol.receive(rx_data)

    assert data == ast.literal_eval(rx_data[0])
    assert len(rx_data) == 1


@pytest.mark.repeat(NUM_REPEATED_TESTS)
@pytest.mark.parametrize("mtu_size", range(sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1, 256))
def test_protocol_send_receive_str(mtu_size):
    msg_size = random.randint(50, 5000)
    data = generate_msg_data(str, size=msg_size)
    encoded_msg_size = len(data.encode("utf-8"))
    transport = MockTransport()
    protocol = sp.SerialProtocol(transport, mtu_size)
    payload_size = mtu_size - sp.SERIAL_PACKET_META_DATA_SIZE_BYTES
    num_packets = ceil(encoded_msg_size / payload_size)

    if num_packets >= 256:
        with pytest.raises(sp.SerialPacketException):
            protocol.send(data)
        return

    # Send data
    protocol.send(data)

    # Receive same data
    rx_data = []
    protocol.receive(rx_data)

    assert data == rx_data[0]
    assert len(rx_data) == 1


@pytest.mark.repeat(NUM_REPEATED_TESTS)
@pytest.mark.parametrize("mtu_size", range(sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1, 256))
def test_protocol_send_receive_unaligned(mtu_size, mocker):
    msg_size = random.randint(50, 5000)
    data = generate_msg_data(bytes, size=msg_size)
    transport = MockTransport()
    protocol = sp.SerialProtocol(transport, mtu_size)
    payload_size = mtu_size - sp.SERIAL_PACKET_META_DATA_SIZE_BYTES
    num_packets = ceil(msg_size / payload_size)

    if num_packets >= 256:
        with pytest.raises(sp.SerialPacketException):
            protocol.send(data)
        return

    def mock_receive(rxed_data: List, **kwargs) -> bool:
        chunk_size = kwargs.get("chunk_size", 37)
        idx = kwargs.get("idx", 0)
        data = bytearray(b"".join(transport.rx_packets))

        chunk = data[idx:idx + chunk_size]
        rxed_data.append(chunk)

        return True

    # Mock transport's receive function
    mocker.patch.object(transport, "receive", side_effect=mock_receive)

    # Send data
    protocol.send(data)

    # Receive corrupted data
    rx_data = []
    for i in range(0, mtu_size * num_packets, 37):
        protocol.receive(rx_data, chunk_size=37, idx=i)

    # Verify
    assert b"".join(rx_data) == data


@pytest.mark.repeat(NUM_REPEATED_TESTS)
@pytest.mark.parametrize("mtu_size", range(sp.SERIAL_PACKET_META_DATA_SIZE_BYTES + 1, 256))
def test_protocol_send_receive_corrupt_delim(mtu_size, mocker: MockerFixture):
    corrupt_pkts = []
    corrupt_idxs = []
    msg_size = random.randint(50, 5000)
    data = generate_msg_data(bytes, size=msg_size)
    transport = MockTransport()
    protocol = sp.SerialProtocol(transport, mtu_size)
    payload_size = mtu_size - sp.SERIAL_PACKET_META_DATA_SIZE_BYTES
    num_packets = ceil(msg_size / payload_size)
    num_corrupt_pkts = random.randint(1, num_packets)

    if num_packets >= 256:
        with pytest.raises(sp.SerialPacketException):
            protocol.send(data)
        return

    def mock_receive(rxed_data: List, **kwargs) -> bool:
        idxs = random.sample(range(0, len(transport.rx_packets)), num_corrupt_pkts)
        for index in idxs:
            # Pick a random packet and corrupt delim
            corrupt_pkt = bytearray(transport.rx_packets[index])
            corrupt_pkt[0:len(sp.SERIAL_PACKET_DELIM)] = b"<nop>"
            corrupt_pkts.append(bytes(corrupt_pkt))
            corrupt_idxs.append(index)

            # Replace with corrupted packet
            transport.rx_packets[index] = bytes(corrupt_pkt)

        # Perform normal receive mock operation
        for pkt in transport.rx_packets:
            rxed_data.append(pkt)

        return True

    # Mock transports receive fxn to corrupt a packet
    mocker.patch.object(transport, "receive", side_effect=mock_receive)

    # Send data
    protocol.send(data)

    # Receive corrupted data
    rx_data = []
    protocol.receive(rx_data)

    # Verify
    assert len(rx_data) == 0


@pytest.mark.repeat(NUM_REPEATED_TESTS)
@pytest.mark.parametrize("mtu_size", range(0, 255 + 5, 5))
def test_protocol_send_receive_corrupt_header(mtu_size, mocker: MockerFixture):
    if mtu_size <= sp.SERIAL_PACKET_META_DATA_SIZE_BYTES:
        return

    corrupt_pkts = []
    corrupt_idxs = []
    msg_size = random.randint(50, 5000)
    data = generate_msg_data(bytes, size=msg_size)
    transport = MockTransport()
    protocol = sp.SerialProtocol(transport, mtu_size)
    payload_size = mtu_size - sp.SERIAL_PACKET_META_DATA_SIZE_BYTES
    num_packets = ceil(msg_size / payload_size)
    num_corrupt_pkts = random.randint(1, num_packets)

    if num_packets >= 256:
        with pytest.raises(sp.SerialPacketException):
            protocol.send(data)
        return

    def mock_receive(rxed_data: List, **kwargs) -> bool:
        idxs = random.sample(range(0, len(transport.rx_packets)), num_corrupt_pkts)
        for index in idxs:
            # Pick a random packet to corrupt
            corrupt_pkt = bytearray(transport.rx_packets[index])

            # Corrupt a random byte in the header
            hdr_idx = random.randint(len(sp.SERIAL_PACKET_DELIM), sp.SERIAL_PACKET_HDR_SIZE_BYTES - 1)
            current_byte = corrupt_pkt[hdr_idx:hdr_idx + 1]
            corrupt_pkt[hdr_idx:hdr_idx + 1] = [current_byte[0] ^ 0xFF]
            corrupt_pkts.append(bytes(corrupt_pkt))
            corrupt_idxs.append(index)

            # Replace with corrupted packet
            transport.rx_packets[index] = bytes(corrupt_pkt)

        # Perform normal receive mock operation
        for pkt in transport.rx_packets:
            rxed_data.append(pkt)

        return True

    # Mock transports receive fxn to corrupt a packet
    mocker.patch.object(transport, "receive", side_effect=mock_receive)

    # Spy logger.exception so we can verify we are getting the CRC failure exception log
    spy = mocker.spy(logging.getLogger("serial-protocols"), "exception")

    # Send data
    protocol.send(data)

    # Receive corrupted data
    rx_data = []
    protocol.receive(rx_data)

    # Verify
    valid_packets = min(corrupt_idxs)
    assert len(rx_data) == 0
    assert valid_packets + protocol.metrics["partial_packets"] + protocol.metrics["invalid_packets"] == num_packets
    assert spy.call_count == protocol.metrics["invalid_packets"]
    for _, kwargs in spy.call_args_list:
        assert isinstance(kwargs.get("exc_info"), (sp.SerialMessageException, sp.SerialPacketException))


# Send / receive cached sends
