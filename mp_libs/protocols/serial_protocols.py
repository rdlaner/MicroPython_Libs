"""Serial Protocol Implementation"""
# TODO: Could use ctypes Union to reduce SerialPacket header size.

# Standard imports
import binascii
import io
import struct
import sys
from collections import namedtuple
from math import ceil
from micropython import const
try:
    from typing import List
except ImportError:
    pass

# Third party imports
from mp_libs import logging
from mp_libs.protocols import InterfaceProtocol

# Local imports
try:
    from config import config
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants
DEFAULT_SERIAL_MESSAGE_MTU_SIZE_BYTES = const(200)  # aka SerialPacket size
SERIAL_MSG_ID_MAX = const(256)
SERIAL_PACKET_DELIM = b"<SER>"
SERIAL_PACKET_HDR_FORMAT_STR = f"<{len(SERIAL_PACKET_DELIM)}sBBBHB"
SERIAL_PACKET_HDR_SIZE_BYTES = struct.calcsize(SERIAL_PACKET_HDR_FORMAT_STR)
SERIAL_PACKET_CRC_SIZE_BYTES = const(4)
SERIAL_PACKET_META_DATA_SIZE_BYTES = SERIAL_PACKET_HDR_SIZE_BYTES + SERIAL_PACKET_CRC_SIZE_BYTES

# Globals
logger = logging.getLogger("serial-protocols")
logger.setLevel(config["logging_level"])
SerialPacketHeader = namedtuple("SerialPacketHeader",
                                ("delim",
                                 "msg_id",
                                 "packet_id",
                                 "packets_per_msg",
                                 "payload_size",
                                 "encoded"
                                 ))


class SerialPacketException(Exception):
    """Custom exception for SerialPackets"""


class SerialMessageException(Exception):
    """Custom exception for SerialMessages"""


class SerialPacket():
    """
    A SerialPacket is the smallest unit of data to be sent over a serial transport. In other words,
    it is the MTU for transmission of SerialMessages. It is intended to be used with a SerialMessage
    in that a SerialMessage is composed of 1 or more SerialPackets.

    Each SerialPacket contains a header defining it's position within a SerialMessage, as well as
    packet specific data so that a consumer can correctly parse a serialized SerialPacket and
    ultimately reconstruct a SerialMessage.
    """
    def __init__(self,
                 data: bytes,
                 msg_id: int,
                 packet_id: int,
                 packets_per_msg: int,
                 encoded: bool) -> None:
        self.header = SerialPacketHeader(
            delim=SERIAL_PACKET_DELIM,
            msg_id=msg_id,
            packet_id=packet_id,
            packets_per_msg=packets_per_msg,
            payload_size=len(data),
            encoded=encoded
        )
        self.payload = data
        self.crc = None
        self._serialized_packet = None

        self._serialize()

    def __repr__(self) -> str:
        return f"{self.header}\nPayload: {self.payload}\nCRC: {self.crc}"

    def _serialize(self) -> None:
        """Serializes this packet into a bytes object.

        Serializes the header and payload data first, then calculates the packet's crc value
        based on that, and then appends the crc value to the end completing the serialized object.
        """
        format_str = SERIAL_PACKET_HDR_FORMAT_STR + f"{len(self.payload)}s"

        packed = struct.pack(format_str,
                             self.header.delim,
                             self.header.msg_id,
                             self.header.packet_id,
                             self.header.packets_per_msg,
                             self.header.payload_size,
                             self.header.encoded,
                             self.payload)
        self.crc = binascii.crc32(packed)
        self._serialized_packet = bytes(
            bytearray(packed) + bytearray(self.crc.to_bytes(SERIAL_PACKET_CRC_SIZE_BYTES, "little"))
        )

    @classmethod
    def deserialize(cls, data: bytes) -> "SerialPacket":
        """Deserializes a bytes object into a SerialPacket.

        If a given bytes object was generated by SerialPacket._serialize(), then this method can
        extract the necessary components and produce a new SerialPacket instance with that data.

        Args:
            data (bytes): bytes object produced by SerialPacket._serialize()

        Raises:
            SerialPacketException: Failed to deserialize packet
            SerialPacketException: Invalid packet header delim
            SerialPacketException: Invalid packet header msg id
            SerialPacketException: CRC check failure

        Returns:
            SerialPacket: New instance of SerialPacket.
        """
        # Extract header
        header_size = struct.calcsize(SERIAL_PACKET_HDR_FORMAT_STR)
        header_data = data[0:header_size]
        try:
            header = SerialPacketHeader(*struct.unpack(SERIAL_PACKET_HDR_FORMAT_STR, header_data))
        except RuntimeError as exc:
            buf = io.StringIO()
            sys.print_exception(exc, buf)
            raise SerialPacketException(
                f"Failed to deserialize packet header: {header_data}\nexc: {buf.getvalue()}")

        # Validate header
        if header.delim != SERIAL_PACKET_DELIM:
            raise SerialPacketException(f"Invalid packet header delim: {header.delim}")
        if header.msg_id >= SERIAL_MSG_ID_MAX:
            raise SerialPacketException(f"Invalid packet header msg id: {header.msg_id}")

        # Build new SerialPacket
        payload_idx = header_size
        crc_idx = payload_idx + header.payload_size
        payload = data[payload_idx:crc_idx]
        expected_crc = int.from_bytes(data[crc_idx: crc_idx + 4], "little")
        packet = cls(payload, header.msg_id, header.packet_id, header.packets_per_msg, header.encoded)

        # Check crc
        if expected_crc != packet.crc:
            raise SerialPacketException(
                f"CRC check Failed! Expected: {expected_crc}. Actual: {packet.crc}")

        return packet

    def serialize(self) -> bytes:
        """Serializes this packet into a bytes object.

        Returns:
            bytes: Serialized bytes object representing this packet instance.
        """
        return self._serialized_packet  # type: ignore


class SerialMessage():
    """
    A SerialMessage is composed of SerialPackets and is used to define a message that is larger than
    the MTU size defined by a SerialPacket. It supports sending variable length messages over a
    serial transport. Meta data for the SerialMessage is contained in each SerialPacket

    |------------------- MSG X -------------------|
    Packet 0 | Packet 1 | Packet 2 | ... | Packet X
    """
    msg_id = 0

    def __init__(self, data, mtu_size_bytes: int, msg_id: int = None) -> None:
        """Not intended to be initialized directly. Users should use one of the create classmethods.

        Args:
            data (generic): Msg data.
            mtu_size_bytes (int): Max size of each SerialPacket.
            msg_id (int, optional): Msg identifier. If none, will increment from static count.
        """
        self.data = data
        self.mtu_size_bytes = mtu_size_bytes
        self.msg_id = msg_id if msg_id else self._get_and_increment_msg_id()
        self.packets = []
        self._iter_idx = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._iter_idx < len(self.packets):
            packet = self.packets[self._iter_idx]
            self._iter_idx += 1
            return packet
        else:
            self._iter_idx = 0
            raise StopIteration("noop")

    def __new__(cls, *args, **kwargs):
        raise SerialMessageException(
            "SerialMessage does not support direct instantiation. Use factory classmethods.")

    def __repr__(self) -> str:
        return "\n".join(str(packet) for packet in self.packets)

    def _get_and_increment_msg_id(self) -> int:
        msg_id = SerialMessage.msg_id
        SerialMessage.msg_id = (msg_id + 1) % SERIAL_MSG_ID_MAX

        return msg_id

    def encode(self) -> bytes:
        """Return an encoded copy of the SerialMessage's data using "utf-8" encoding.

        Raises:
            SerialMessageException: Can't encode if data is None.

        Returns:
            bytes: Byte string of encoded data.
        """
        if self.data is None:
            raise SerialMessageException("Data cannot be None.")

        return str(self.data).encode("utf-8")

    @classmethod
    def create_msg_from_packets(cls, packets: list[SerialPacket]) -> "SerialMessage":
        """Creates a new SerialMessage from a list of SerialPackets.

        Note: MTU size is chosen based on size of largest SerialPacket.

        Args:
            packets (list[SerialPacket]): 1 or more SerialPackets.

        Raises:
            SerialMessageException: List of SerialPackets cannot be empty.

        Returns:
            SerialMessage: New SerialMessage.
        """
        if not packets:
            raise SerialMessageException("Can't create msg from empty list of packets")

        # Extract data from packets
        mtu_size_bytes = max(len(packet.serialize()) for packet in packets)
        msg_id = packets[0].header.msg_id
        data = bytearray()
        for packet in packets:
            data.extend(packet.payload)

        # Decode data, if appropriate
        if packets[0].header.encoded:
            data = data.decode("utf-8")
        else:
            data = bytes(data)

        # Create new SerialMessage
        msg = object.__new__(cls)
        msg.__init__(data, mtu_size_bytes, msg_id)  # pylint: disable=unnecessary-dunder-call
        msg.packets = list(packets)  # Copies the whole list and not just a reference

        return msg

    @classmethod
    def create_msg_from_data(cls, data, mtu_size_bytes: int) -> "SerialMessage":
        """Creates a new SerialMessage from raw data.

        Note: If data is not of type bytes or bytearray it will be encoded as a byte string.

        Args:
            data (generic): Data to be contained in the new SerialMessage.
            mtu_size_bytes (int): MTU size in bytes. Determines how many SerialPackets are created.

        Raises:
            SerialMessageException: Data cannot be None.
            SerialMessageException: MTU size can't be less than the size of the SerialPacket header.

        Returns:
            SerialMessage: New SerialMessage.
        """
        if not data:
            raise SerialMessageException("Data cannot be None.")

        if mtu_size_bytes <= SERIAL_PACKET_META_DATA_SIZE_BYTES:
            raise SerialMessageException("MTU size is too small")

        # Initialize a new SerialMessage
        msg = object.__new__(cls)
        msg.__init__(data, mtu_size_bytes)  # pylint: disable=unnecessary-dunder-call

        # Encode data (if appropriate)
        if isinstance(data, (bytearray, bytes)):
            encoded_data = bytes(data)
            encoded = False
        else:
            encoded_data = msg.encode()
            encoded = True

        # Build array of packets from encoded data
        num_packets = ceil(len(encoded_data) / (mtu_size_bytes - SERIAL_PACKET_META_DATA_SIZE_BYTES))
        packet_id = 0
        payload_len = mtu_size_bytes - SERIAL_PACKET_META_DATA_SIZE_BYTES
        for i in range(num_packets):
            start = i * payload_len
            end = start + payload_len
            packet_data = encoded_data[start:end]
            packet = SerialPacket(packet_data, msg.msg_id, packet_id, num_packets, encoded)
            packet_id += 1

            msg.packets.append(packet)

        return msg


class SerialProtocol(InterfaceProtocol):
    """InterfaceProtocol implementation for sending and receiving serial messages."""

    def __init__(self,
                 transport: InterfaceProtocol,
                 mtu_size_bytes: int = DEFAULT_SERIAL_MESSAGE_MTU_SIZE_BYTES) -> None:
        self.transport = transport
        self.mtu_size_bytes = mtu_size_bytes
        self.curr_msg_id = None
        self.next_packet_id = 0
        self.cached_serial_packets = []

    def _extract_msg(self) -> "SerialMessage":
        """Extract a SerialMessage from the cached SerialPackets.

        If enough SerialPackets are cached, this function will construct a SerialMessage from
        the SerialPackets starting from the beginning of the cache.
        Once constructed, the constituent SerialPackets will be removed from the cache.

        Raises:
            SerialMessageException: Received incomplete SerialMessage. Missing one or more packets.

        Returns:
            SerialMessage: A new SerialMessage if enough packets are cached, otherwise None.
        """
        if not self.cached_serial_packets:
            return None

        # Check that we have enough packets to make up a message
        packets_per_msg = self.cached_serial_packets[0].header.packets_per_msg
        if packets_per_msg > len(self.cached_serial_packets):
            return None

        # Check that all packets comprising an entire message are present
        msg_id = self.cached_serial_packets[0].header.msg_id
        for i in range(1, packets_per_msg):
            if msg_id != self.cached_serial_packets[i].header.msg_id:
                # Since enough packets exist in the buffer, if the first contiguous set of packets
                # do not all have the same msg_id, then that means we must have dropped one
                # somewhere.
                # Therefore, clear cache of all packets of that msg_id.
                self.cached_serial_packets = self.cached_serial_packets[i:]
                raise SerialMessageException(
                    "Received incomplete SerialMessage. Missing one or more packets.")

        # Construct and return serial message
        serial_packets = []
        for _ in range(packets_per_msg):
            serial_packets.append(self.cached_serial_packets.pop(0))

        return SerialMessage.create_msg_from_packets(serial_packets)

    def _process_packet(self, packet: bytes) -> None:
        """Process serialized SerialPacket received from transport.

        This function will deserialize a SerialPacket and use the packet's header information to
        ensure all packets comprising a SerialMessage are received correctly.
        If not all packets are processed before the msg_id changes or if a packet is missed or if
        packets are received out of order, it will log an error.
        All successfully processed packets are cached so that they can be used to construct a
        SerialMessage via `_extract_msg`.
        This function relies on `_extract_msg` to check if enough packets are present for a msg.
        To be called on each newly received packet.

        Args:
            packet (bytes): Serialized SerialPacket received from transport.

        Raises:
            SerialPacketException: Received new msg id before finishing current
            SerialPacketException: Received out of order packet
        """
        # Construct serial packet
        serial_packet = SerialPacket.deserialize(packet)
        logger.debug(f"{serial_packet.header}")

        # Check msg ID
        if not self.curr_msg_id:
            self.curr_msg_id = serial_packet.header.msg_id
        elif self.curr_msg_id != serial_packet.header.msg_id:
            # Reset packet processing with latest packet
            self.curr_msg_id = serial_packet.header.msg_id
            self.next_packet_id = serial_packet.header.packet_id
            logger.error("".join(("Received new msg id before finishing current.\n",
                                  f"Expected: {self.curr_msg_id}.\n",
                                  f"Actual: {serial_packet.header.msg_id}\n")))

        # Check packet ID
        if self.next_packet_id == serial_packet.header.packet_id:
            self.next_packet_id += 1
        else:
            # Reset packet processing with latest packet
            self.next_packet_id = serial_packet.header.packet_id + 1
            logger.error("".join(("Received out of order packet.\n",
                                  f"Expected: {self.next_packet_id}.\n",
                                  f"Actual: {serial_packet.header.packet_id}\n")))

        # Check if last packet
        if serial_packet.header.packet_id == serial_packet.header.packets_per_msg - 1:  # Minus 1 since 0-based
            self.curr_msg_id = None
            self.next_packet_id = 0

        self.cached_serial_packets.append(serial_packet)

    @property
    def mtu_size(self):
        """Return current MTU size in bytes"""
        return self.mtu_size_bytes

    @mtu_size.setter
    def mtu_size(self, value):
        """Set MTU size in bytes"""
        self.mtu_size_bytes = value

    def connect(self, **kwargs) -> bool:
        """Connect underlying transport.

        Returns:
            bool: True if connected, False if failed to connect.
        """
        return self.transport.connect(**kwargs)

    def disconnect(self, **kwargs) -> bool:
        """Disconnect underlying transport.

        Returns:
            bool: True if disconnected, False if failed to disconnect.
        """
        return self.transport.disconnect(**kwargs)

    def is_connected(self) -> bool:
        return self.transport.is_connected()

    def receive(self, rxed_data: list, **kwargs) -> bool:
        """Attempts to construct and return a SerialMessage payload.

        This function should be called in a polling fashion as each call will read in a piece of
        a SerialMessage. Once enough pieces have been received, one or more SerialMessages will
        be constructed, their payloads extracted and returned.

        Args:
            rxed_data (list): List of SerialMessage payloads, if any.

        Returns:
            bool: True if data is ready and returned. False if no data available.
        """
        data_available = False
        rxed_packets = []

        if self.transport.receive(rxed_packets):
            data_available = True

            # If the received packet is a serial packet, perform processing.
            # If it isn't, just pass it on up, let the upper layers handle it.
            for packet in rxed_packets:
                if packet.startswith(SERIAL_PACKET_DELIM):
                    try:
                        self._process_packet(packet)
                    except SerialPacketException as exc:
                        logger.exception("Failed processing SerialPacket", exc_info=exc)
                else:
                    rxed_data.append(packet)

            # Extract all fully formed serial messages, if enough packets have been received
            while True:
                try:
                    msg = self._extract_msg()
                except SerialMessageException as exc:
                    logger.exception("Failed extracting SerialMessage", exc_info=exc)
                    continue

                # Extract msg payload from any SerialMessages.
                if msg:
                    data_available = True
                    rxed_data.append(msg.data)
                else:
                    break

        return data_available

    def recover(self, **kwargs) -> bool:
        """Recovers underlying transport.

        Returns:
            bool: True if recovery succeeded, False if it failed.
        """
        return self.transport.recover(**kwargs)

    def scan(self, **kwargs) -> List:
        """Performs scan operation.

        SerialProtocol does not have an explicit scan operation, passes this req on to the transport instead.

        Returns:
            List: Result of scan operation.
        """
        return self.transport.scan(**kwargs)

    def send(self, msg, **kwargs) -> bool:
        """Synchronously send data using the SerialProtocol.

        If msg is of type SerialMessage, this function will take it as-is and send over transport.
        If msg is of any other type, this function will construct a SerialMessage with the msg
        as the payload and send it over the transport.

        Args:
            msg (any): Message to send. Can be a prebuilt SerialMessage or just the data.

        Returns:
            bool: True if send succeeded, False if it failed.
        """
        if isinstance(msg, SerialMessage):
            serial_msg = msg
        else:
            serial_msg = SerialMessage.create_msg_from_data(msg, self.mtu_size_bytes)

        return self.send_serial_msg(serial_msg)

    def send_serial_msg(self, serial_msg: SerialMessage) -> bool:
        """Synchronously sends a SerialMessage over the transport.

        Sequentially sends the SerialPackets comprising the SerialMessage over the transport.

        Args:
            serial_msg (SerialMessage): SerialMessage to send.

        Returns:
            bool: True if send succeeded, False if it failed.
        """
        success = True

        for packet in serial_msg:
            success = success and self.transport.send(packet.serialize())

        return success
