"""Serial Protocol Implementation"""
# TODO: Optimize how we use _cached_data. Probably could allocate max size upfront based on the
#       mtu_size and then just use a memorview over the top of it.
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
    from typing import List, Optional
except ImportError:
    pass

# Third party imports
from mp_libs import logging
from mp_libs.collections import defaultdict
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
logger: logging.Logger = logging.getLogger("serial-protocols")
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
        return f"{self.header}\nPayload: {self.payload}\nCRC: 0x{self.crc:X}"

    def _serialize(self) -> None:
        """Serializes this packet into a bytes object.

        Serializes the header and payload data first, then calculates the packet's crc value
        based on that, and then appends the crc value to the end completing the serialized object.
        """
        format_str = SERIAL_PACKET_HDR_FORMAT_STR + f"{len(self.payload)}s"

        try:
            packed = struct.pack(format_str,
                                 self.header.delim,
                                 self.header.msg_id,
                                 self.header.packet_id,
                                 self.header.packets_per_msg,
                                 self.header.payload_size,
                                 self.header.encoded,
                                 self.payload)
        except:  # Note: micropython does not have a struct.error exception type
            raise SerialPacketException(  # pylint: disable=raise-missing-from
                f"Failed to serialize packet. Header: {self.header}, Payload: {self.payload}")

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
        header_data = data[0:SERIAL_PACKET_HDR_SIZE_BYTES]
        try:
            header = SerialPacketHeader(*struct.unpack(SERIAL_PACKET_HDR_FORMAT_STR, header_data))
        except ValueError as exc:
            buf = io.StringIO()
            sys.print_exception(exc, buf)  # type: ignore
            raise SerialPacketException(  # pylint: disable=raise-missing-from
                f"Failed to deserialize packet header: {header_data}\nexc: {buf.getvalue()}")  # type: ignore

        # Validate header
        if header.delim != SERIAL_PACKET_DELIM:
            raise SerialPacketException(f"Invalid packet header delim: {header.delim}")
        if header.msg_id >= SERIAL_MSG_ID_MAX:
            raise SerialPacketException(f"Invalid packet header msg id: {header.msg_id}")
        if SERIAL_PACKET_META_DATA_SIZE_BYTES + header.payload_size != len(data):
            raise SerialPacketException(f"Unexpected/extra data when deserializing packet: {data}")

        # Build new SerialPacket
        payload_idx = SERIAL_PACKET_HDR_SIZE_BYTES
        crc_idx = payload_idx + header.payload_size
        payload = data[payload_idx:crc_idx]
        expected_crc = int.from_bytes(data[crc_idx: crc_idx + SERIAL_PACKET_CRC_SIZE_BYTES], "little")
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
    _global_msg_id_counter: int = 0

    def __init__(self, data: Optional[bytes] = None, msg_id: Optional[int] = None) -> None:
        """Not intended to be initialized directly. Users should use one of the create classmethods.

        Args:
            data (generic): Msg data.
            msg_id (int, optional): Msg identifier. If none, will increment from static count.
        """
        self._data: bytearray = bytearray(data) if data is not None else bytearray()
        self._packets: List[SerialPacket] = []
        self._msg_id = msg_id
        self._next_packet_id = 0
        self._iter_idx = 0
        self._complete = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._iter_idx < len(self._packets):
            packet = self._packets[self._iter_idx]
            self._iter_idx += 1
            return packet
        else:
            self._iter_idx = 0
            raise StopIteration("noop")

    def __new__(cls, *args, **kwargs):
        raise SerialMessageException(
            "SerialMessage does not support direct instantiation. Use factory classmethods.")

    def __repr__(self) -> str:
        return "\n".join(str(packet) for packet in self._packets)

    @property
    def data(self):
        """Returns data contained by the SerialMessage.

        Returns:
            Data
        """
        if self._data is None:
            return None

        if self._packets[0].header.encoded:
            return self._data.decode("utf-8")

        return bytes(self._data)

    @property
    def msg_id(self) -> Optional[int]:
        """Returns Msg ID for this message."""
        return self._msg_id

    @property
    def packets(self) -> List[SerialPacket]:
        """Returns list of packets held by this serial message."""
        return self._packets

    def add_packet(self, packet: SerialPacket, deepcopy: bool = False) -> bool:
        """Supports adding packets to a SerialMessage in order to construct a full message
        incrementally.

        Args:
            packet (SerialPacket): Packet to add to message.
            deepcopy (bool, optional): Create a deep copy of the packet added. Defaults to False.

        Raises:
            SerialMessageException: Attempted to add a new packet to an already completed msg
            SerialMessageException: Attempted to add packet with different message ID
            SerialMessageException: Attempted to add packet with out of order packet ID
            SerialMessageException: Attempted to add packet with different packets per msg value

        Returns:
            bool: True if full message is complete, False otherwise.
        """
        # Check if message is already completed
        if self._complete:
            raise SerialMessageException(
                f"Attempted to add a new packet to an already completed msg.\n"
                f"Current msg ID:    {self._msg_id}\n"
                f"New packet msg ID: {packet.header.msg_id}"
            )

        # Check msg ID
        if self._msg_id is None:
            self._msg_id = packet.header.msg_id
        elif self._msg_id != packet.header.msg_id:
            raise SerialMessageException(
                f"Attempted to add packet with different message ID\n"
                f"Expected: {self._msg_id}\n"
                f"Actual:   {packet.header.msg_id}"
            )

        # Check packet ID
        if self._next_packet_id == packet.header.packet_id:
            self._next_packet_id += 1
        else:
            raise SerialMessageException(
                f"Attempted to add packet with out of order packet ID\n"
                f"Expected: {self._next_packet_id}\n"
                f"Actual:   {packet.header.packet_id}"
            )

        # Check packets per msg
        if self._packets and self._packets[0].header.packets_per_msg != packet.header.packets_per_msg:
            raise SerialMessageException(
                f"Attempted to add packet with different packets per msg value\n"
                f"Expected: {self.packets[0].header.packets_per_msg}"
                f"Actual:   {packet.header.packets_per_msg}"
            )

        # Add packet data to msg
        self._data.extend(packet.payload)
        if deepcopy:
            self._packets.append(SerialPacket(
                packet.payload,
                packet.header.msg_id,
                packet.header.packet_id,
                packet.header.packets_per_msg,
                packet.header.encoded
            ))
        else:
            self._packets.append(packet)

        # Check if msg is complete
        if len(self._packets) == self._packets[0].header.packets_per_msg:
            self._complete = True

        return self._complete

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

    def is_msg_complete(self) -> bool:
        """Checks if this message is completed, ie. it contains all its component packets.

        Returns:
            bool: True if message is complete, False otherwise.
        """
        return self._complete

    @classmethod
    def _get_and_increment_msg_id(cls) -> int:
        msg_id = cls._global_msg_id_counter
        cls._global_msg_id_counter = (msg_id + 1) % SERIAL_MSG_ID_MAX

        return msg_id

    @classmethod
    def create_msg_empty(cls, msg_id: Optional[int] = None) -> "SerialMessage":
        """Creates an empty serial message.

        Args:
            msg_id (Optional[int], optional): Message ID to start empty message with. Defaults to None.

        Returns:
            SerialMessage: New SerialMessage instance.
        """
        msg = object.__new__(cls)
        msg.__init__(data=None, msg_id=msg_id)  # pylint: disable=unnecessary-dunder-call

        return msg

    @classmethod
    def create_msg_from_packets(
        cls, packets: list[SerialPacket], check: bool = True, deepcopy: bool = False
    ) -> "SerialMessage":
        """Creates a new SerialMessage from a list of SerialPackets.

        Note: MTU size is chosen based on size of largest SerialPacket.

        Args:
            packets (list[SerialPacket]): 1 or more SerialPackets.
            check (bool): Perform packet checks. Will throw if errors found.
            deepcopy (bool): Perform deepcopy of packets into new msg.

        Raises:
            SerialMessageException: List of SerialPackets cannot be empty.
            SerialMessageException: Not enough packets for a msg.
            SerialMessageException: Mismatching msg ID's.

        Returns:
            SerialMessage: New SerialMessage.
        """
        if not packets:
            raise SerialMessageException("Can't create msg from empty list of packets")

        msg_id = packets[0].header.msg_id
        if check:
            # Check that we have enough packets to make up a message
            packets_per_msg = packets[0].header.packets_per_msg
            if packets_per_msg > len(packets):
                raise SerialMessageException(
                    f"Not enough packets to build the full message\n"
                    f"Expected: {packets[0].header.packets_per_msg}\n"
                    f"Actual:   {len(packets)}"
                )

            # Check that all packets comprising an entire message are present
            for i in range(1, packets_per_msg):
                if msg_id != packets[i].header.msg_id:
                    # Since enough packets exist in the buffer, if the first contiguous set of packets
                    # do not all have the same msg_id, then that means we must have dropped one
                    # somewhere.
                    raise SerialMessageException(
                        "Received incomplete msg with mismatching msg ID's. Missing one or more packets.")

        # Start with an empty msg and add in each packet
        msg = SerialMessage.create_msg_empty(msg_id=msg_id)
        for pkt in packets:
            msg.add_packet(pkt, deepcopy=deepcopy)

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

        # Encode data (if appropriate)
        if isinstance(data, (bytearray, bytes)):
            encoded_data = bytes(data)
            encoded = False
        else:
            encoded_data = str(data).encode()
            encoded = True

        # Start with an empty msg and add in each newly created packet
        msg_id = cls._get_and_increment_msg_id()
        msg = SerialMessage.create_msg_empty(msg_id=msg_id)
        num_packets = ceil(len(encoded_data) / (mtu_size_bytes - SERIAL_PACKET_META_DATA_SIZE_BYTES))
        packet_id = 0
        payload_len = mtu_size_bytes - SERIAL_PACKET_META_DATA_SIZE_BYTES
        for i in range(num_packets):
            start = i * payload_len
            end = start + payload_len
            packet_data = encoded_data[start:end]
            packet = SerialPacket(packet_data, msg_id, packet_id, num_packets, encoded)
            packet_id += 1

            msg.add_packet(packet)

        return msg


class SerialProtocol(InterfaceProtocol):
    """InterfaceProtocol implementation for sending and receiving serial messages."""

    def __init__(self,
                 transport: InterfaceProtocol,
                 mtu_size_bytes: int = DEFAULT_SERIAL_MESSAGE_MTU_SIZE_BYTES) -> None:
        self.metrics = defaultdict(int)
        self._transport = transport
        self._mtu_size_bytes = mtu_size_bytes
        self._curr_msg = SerialMessage.create_msg_empty()
        self._cached_data = bytearray()

    def _parse_packets(self, rxed_data: List) -> List:
        # Collect received data and append it to any existing cached data
        self._cached_data.extend(b"".join(rxed_data))
        cache = memoryview(self._cached_data)

        # Iterate over cache marking the location of each detected delimiter.
        # It is possible, however, that a delim is corrupted or we have a partial delimiter at
        # the end of the cache. Therefore, we still need to extract the header and calc the
        # packet size.
        delim_idxs = []
        for i, elem in enumerate(cache):
            if (
                elem == SERIAL_PACKET_DELIM[0] and
                cache[i:i + len(SERIAL_PACKET_DELIM)] == SERIAL_PACKET_DELIM
            ):
                delim_idxs.append(i)

        # Iterate over delim indices and construct packets
        rxed_packets = []
        final_packet = False
        for i, idx in enumerate(delim_idxs):
            if idx == delim_idxs[-1]:
                final_packet = True

            # Extract packet header
            header_data = cache[idx:idx + SERIAL_PACKET_HDR_SIZE_BYTES]
            try:
                header = SerialPacketHeader(*struct.unpack(SERIAL_PACKET_HDR_FORMAT_STR, header_data))
            except Exception:
                logger.debug("Received partial serial packet header")
                self.metrics["partial_packets"] += 1
                if final_packet:
                    # del self._cached_data[:idx]
                    cache = cache[idx:]
                continue

            packet_size = SERIAL_PACKET_META_DATA_SIZE_BYTES + header.payload_size

            # Verify packet size
            if final_packet and packet_size > len(cache) - idx:
                logger.debug("Received partial serial packet")
                self.metrics["partial_packets"] += 1
                # del self._cached_data[:idx]
                cache = cache[idx:]
                continue

            # Attempt to deserialize the data chunk
            try:
                packet = SerialPacket.deserialize(bytes(cache[idx:idx + packet_size]))
            except SerialPacketException as exc:
                logger.exception("Failed deserializing SerialPacket", exc_info=exc)
                self.metrics["invalid_packets"] += 1
                if final_packet:
                    # del self._cached_data[:idx]
                    cache = cache[idx:]
                continue

            # Received a full, valid packet
            rxed_packets.append(packet)
            if final_packet:
                # Don't clear the entire cache as there could be a partial delimiter still remaining
                # del self._cached_data[:idx + packet_size]
                cache = cache[idx + packet_size:]

        # Reconcile cache memoryview with actual cache
        self._cached_data = bytearray(cache)

        return rxed_packets

    @property
    def mtu_size(self):
        """Return current MTU size in bytes"""
        return self._mtu_size_bytes

    @mtu_size.setter
    def mtu_size(self, value):
        """Set MTU size in bytes"""
        self._mtu_size_bytes = value

    def connect(self, **kwargs) -> bool:
        """Connect underlying transport.

        Returns:
            bool: True if connected, False if failed to connect.
        """
        return self._transport.connect(**kwargs)

    def disconnect(self, **kwargs) -> bool:
        """Disconnect underlying transport.

        Returns:
            bool: True if disconnected, False if failed to disconnect.
        """
        return self._transport.disconnect(**kwargs)

    def is_connected(self) -> bool:
        return self._transport.is_connected()

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
        serial_data = []

        if self._transport.receive(serial_data, **kwargs):
            # Parse any fully received packets
            rxed_packets = self._parse_packets(serial_data)

            # Build up current serial message
            for packet in rxed_packets:
                try:
                    self._curr_msg.add_packet(packet)
                except SerialMessageException as exc:
                    logger.exception("Failed adding packet to SerialMessage", exc_info=exc)
                    self.metrics["invalid_packets"] += 1

                # Return data if a full msg has been received
                if self._curr_msg.is_msg_complete():
                    rxed_data.append(self._curr_msg.data)
                    data_available = True
                    self._curr_msg = SerialMessage.create_msg_empty()

        return data_available

    def recover(self, **kwargs) -> bool:
        """Recovers underlying transport.

        Returns:
            bool: True if recovery succeeded, False if it failed.
        """
        return self._transport.recover(**kwargs)

    def scan(self, **kwargs) -> List:
        """Performs scan operation.

        SerialProtocol does not have an explicit scan operation, passes this req on to the transport instead.

        Returns:
            List: Result of scan operation.
        """
        return self._transport.scan(**kwargs)

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
            serial_msg = SerialMessage.create_msg_from_data(msg, self._mtu_size_bytes)

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
            success = success and self._transport.send(packet.serialize())

        return success
