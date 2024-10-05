"""Basic Precision Time Protocol (PTP) implementation
"""
# pylint: disable=raise-missing-from

# Standard imports
import io
import struct
import sys
import time
from collections import namedtuple
from machine import RTC        # pylint: disable=import-error,
from micropython import const  # pylint: disable=import-error, wrong-import-order
try:
    from typing import Any, Callable, List, Tuple, Union
except ImportError:
    pass

# Third party imports
from mp_libs import logging
from mp_libs import statistics
from mp_libs.enum import Enum
from mp_libs.mpy_decimal import DecimalNumber
from mp_libs.protocols import InterfaceProtocol

# Local imports
try:
    from config import config  # type: ignore
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants
PTP_PACKET_DELIM = b"<PTP>"
PTP_PACKET_FORMAT_STR = f"<{len(PTP_PACKET_DELIM)}sBQ"
PTP_PACKET_SIZE_BYTES = struct.calcsize(PTP_PACKET_FORMAT_STR)
DEFAULT_TIMEOUT_MSEC = const(1000)

# Globals
logger: logging.Logger = logging.getLogger("PTP")
logger.setLevel(config["logging_level"])
rtc = RTC()


# Tuple defining all of the PtpPacket elements
PtpPacketTuple = namedtuple("PtpPacket", ("delim", "msg", "payload"))


class PtpPacketError(Exception):
    """PTP Packet Error Exception"""
    def __init__(self, message: str) -> None:
        msg = f"PTP - {message}"
        super().__init__(msg)


class TimeoutError(Exception):  # pylint: disable=redefined-builtin
    """General timeout exception"""


class PtpMsg(Enum):
    """All PTP message types"""
    SYNC_REQ = const(0)
    SYNC_START = const(1)
    DELAY_REQ = const(2)
    DELAY_RESP = const(3)
    _to_str_lut = {
        SYNC_REQ: "SYNC REQ",
        SYNC_START: "SYNC_START",
        DELAY_REQ: "DELAY_REQ",
        DELAY_RESP: "DELAY_RESP"
    }

    @classmethod
    def to_str(cls, msg: Union["PtpMsg", int]) -> str:
        """Get the associated string for a given PtpMsg enum value.

        Args:
            msg (PtpMsg): PtpMsg enum value (eg PtpMsg.SYNC_REQ).

        Returns:
            str: Enum string value.
        """
        return cls._to_str_lut[msg]


class PtpPacket():
    """PTP packet definition used for all PTP transmissions.

    PTP packet composition:
    -------------------------
    | <PTP> | Msg | Payload |
    -------------------------

    Msg must be one of the PtpMsg values. Payload must be an int.
    """
    def __init__(self, msg: Union[PtpMsg, int], payload: int) -> None:
        self._packet = PtpPacketTuple(
            delim=PTP_PACKET_DELIM,
            msg=msg,
            payload=payload
        )
        self._serialized_packet = b""
        self._serialize()

    def _serialize(self) -> None:
        self._serialized_packet = struct.pack(
            PTP_PACKET_FORMAT_STR,
            self._packet.delim,
            self._packet.msg,
            self._packet.payload
        )

    @property
    def msg(self) -> PtpMsg:
        """Get packet message type.

        Returns:
            PtpMsg: Packet message type.
        """
        return self._packet.msg

    @property
    def payload(self) -> int:
        """Get packet payload.

        Returns:
            int: Packet payload.
        """
        return self._packet.payload

    @classmethod
    def deserialize(cls, data: bytes) -> "PtpPacket":
        """Deserializes a bytes object into a PtpPacket instance.

        Args:
            data (bytes): bytes object produced by PtpPacket.serialize()

        Raises:
            PtpPacketError: Invalid packet size.
            PtpPacketError: Failed to deserialize.
            PtpPacketError: Invalid delim.
            PtpPacketError: Invalid msg.
            PtpPacketError: Invalid payload.

        Returns:
            PtpPacket: New PtpPacket instance.
        """
        if len(data) != PTP_PACKET_SIZE_BYTES:
            raise PtpPacketError(
                f"Invalid size. Expected: {PTP_PACKET_SIZE_BYTES} bytes. Actual: {len(data)} bytes")

        # Deserialize
        try:
            ptp_tuple = PtpPacketTuple(*struct.unpack(PTP_PACKET_FORMAT_STR, data))
        except (ValueError, TypeError) as exc:
            buf = io.StringIO()
            sys.print_exception(exc, buf)  # type: ignore pylint: disable=no-member
            raise PtpPacketError(
                f"Failed to deserialize packet: {data}\nexc: {buf.getvalue()}")

        # Verify header
        if ptp_tuple.delim != PTP_PACKET_DELIM:
            raise PtpPacketError(f"Invalid packet delim: {ptp_tuple.delim}")
        if not PtpMsg.contains(ptp_tuple.msg):
            raise PtpPacketError(f"Packet contains invalid msg: {ptp_tuple.msg}")
        if not isinstance(ptp_tuple.payload, int):
            raise PtpPacketError(f"Invalid payload: {ptp_tuple.payload}")

        return cls(ptp_tuple.msg, ptp_tuple.payload)

    def serialize(self) -> bytes:
        """Serializes this packet instance into a bytes object.

        Returns:
            bytes: Serialized bytes object representing this packet instance.
        """
        return self._serialized_packet


def calculate_delay(t1: int, t2: int, t3: int, t4: int) -> int:
    """Calculates the transmission delay value from t1-t4 timestamps.

    Args:
        t1 (int): SYNC_START TX timestamp.
        t2 (int): SYNC_START RX timestamp.
        t3 (int): DELAY_REQ TX timestamp.
        t4 (int): DELAY_REQ RX timestamp.

    Returns:
        int: Transmission delay value.
    """
    return ((t2 - t1) + (t4 - t3)) // 2


def calculate_offset(t1: int, t2: int, t3: int, t4: int) -> int:
    """Calculates the offset value from t1-t4 timestamps.

    Args:
        t1 (int): SYNC_START TX timestamp.
        t2 (int): SYNC_START RX timestamp.
        t3 (int): DELAY_REQ TX timestamp.
        t4 (int): DELAY_REQ RX timestamp.

    Returns:
        int: Offset value.
    """
    return ((t2 - t1) - (t4 - t3)) // 2


def sync_req(transport: InterfaceProtocol, num_sync_cycles: int = 1, **kwargs) -> None:
    """Send SYNC_REQ packet.

    Args:
        transport (InterfaceProtocol): Transport to send message over.
        num_sync_cycles (int, optional): Number of PTP sync cycles to perform. Defaults to 1.
    """
    logger.debug("Sending SYNC REQ")
    transport.send(PtpPacket(PtpMsg.SYNC_REQ, num_sync_cycles).serialize(), **kwargs)


def sync_start(transport: InterfaceProtocol, **kwargs) -> int:
    """Send SYNC_START packet.

    Args:
        transport (InterfaceProtocol): Transport to send message over.

    Returns:
        int: T1 timestamp.
    """
    logger.debug("Sending SYNC START")
    t1 = rtc.now()
    transport.send(PtpPacket(PtpMsg.SYNC_START, t1).serialize(), **kwargs)
    return t1


def delay_req(transport: InterfaceProtocol, **kwargs) -> int:
    """Send DELAY_REQ packet.

    Args:
        transport (InterfaceProtocol): Transport to send message over.

    Returns:
        int: T3 timestamp.
    """
    logger.debug("Sending DELAY REQ")
    t3 = rtc.now()
    transport.send(PtpPacket(PtpMsg.DELAY_REQ, t3).serialize(), **kwargs)
    return t3


def delay_resp(transport: InterfaceProtocol, ts: int, **kwargs) -> None:
    """Send DELAY_RESP packet.

    Args:
        transport (InterfaceProtocol): Transport to send message over.
        ts (int): T4 timestamp.
    """
    logger.debug("Sending DELAY RESP")
    transport.send(PtpPacket(PtpMsg.DELAY_RESP, ts).serialize(), **kwargs)


def is_ptp_msg(msg: bytes) -> bool:
    """Checks if a given serialized array of bytes is a PTP Packet.

    Args:
        msg (bytes): Bytes to check.

    Returns:
        bool: True if it is a PtpPacket, False if not.
    """
    result = True
    try:
        PtpPacket.deserialize(msg)
    except PtpPacketError:
        result = False

    return result


def parse_msg(msg: bytes) -> Tuple[Union[PtpMsg, int], int]:
    """Parse a serialized PtpPacket.

    Args:
        msg (bytes): Serialized PtpPacket.

    Returns:
        Tuple[Union[PtpMsg, int], int]: (msg type, payload)
    """
    packet = PtpPacket.deserialize(msg)
    return (packet.msg, packet.payload)


def process_offsets(offsets: Union[List[int], List[DecimalNumber]]) -> int:
    """Calculates the average offset from a list of calculated offsets.

    First removes any outliers from the offsets list and then calculates the average offset.

    Args:
        offsets (Union[List[int], List[DecimalNumber]]): List of offset values.
                                                         Can either by a list of ints or a list of DecimalNumbers.

    Returns:
        int: Average offset value.
    """
    if not isinstance(offsets[0], DecimalNumber):
        offsets = [DecimalNumber(x) for x in offsets]         # type: ignore

    cleaned_offsets = statistics.remove_outliers_iqr(offsets, 25, 75)
    ave_offset = sum(cleaned_offsets) / len(cleaned_offsets)  # type: ignore
    return ave_offset.to_int_truncate()                       # type: ignore


def sequence_master(
    transport: InterfaceProtocol,
    msg_parser: Callable[[Any], bytes],
    timeout_ms: int = DEFAULT_TIMEOUT_MSEC,
    num_sync_cycles: int = 1,
    **kwargs
) -> None:
    """Performs the PTP master's sync operations.

    Args:
        transport (InterfaceProtocol): Transport to send messages over.
        msg_parser (Callable[[Any], bytes]): Callable to parse the transport message and return a bytes payload.
        timeout_ms (int, optional): Time to wait for responses. Defaults to DEFAULT_TIMEOUT_MSEC.
        num_sync_cycles (int, optional): Number of time sync cycles to perform. Defaults to 1.
    """
    cycle_count = 0
    while cycle_count < num_sync_cycles:
        sync_start(transport, **kwargs)
        _, t4 = wait_for_msg(PtpMsg.DELAY_REQ, transport, msg_parser, timeout_ms, **kwargs)
        delay_resp(transport, t4, **kwargs)
        time.sleep_ms(25)  # pylint: disable=no-member

        cycle_count += 1


def sequence_periph(
    transport: InterfaceProtocol,
    msg_parser: Callable[[Any], bytes],
    timeout_ms: int = DEFAULT_TIMEOUT_MSEC,
    initiate_sync: bool = False,
    num_sync_cycles: int = 1,
    **kwargs
) -> List[Tuple[int, int, int, int]]:
    """Performs the PTP peripheral's sync operations.

    Args:
        transport (InterfaceProtocol): Transport to send messages over.
        msg_parser (Callable[[Any], bytes]): Callable to parse the transport message and return a bytes payload.
        timeout_ms (int, optional): Time to wait for responses. Defaults to DEFAULT_TIMEOUT_MSEC.
        initiate_sync (bool, optional): If True, peripheral will initiate the sync process.
                                        If False, peripheral will go straight to waiting for SYNC_START.
                                        Defaults to False.
        num_sync_cycles (int, optional): Number of time sync cycles to perform. Defaults to 1.

    Returns:
        List[Tuple[int, int, int, int]]: List of T1-T4 timestamp tuples. One tuple per sync cycle.
    """
    if initiate_sync:
        sync_req(transport, num_sync_cycles, **kwargs)

    cycle_count = 0
    results = []
    while cycle_count < num_sync_cycles:
        t1, t2 = wait_for_msg(PtpMsg.SYNC_START, transport, msg_parser, timeout_ms, **kwargs)
        t3 = delay_req(transport, **kwargs)
        t4, _ = wait_for_msg(PtpMsg.DELAY_RESP, transport, msg_parser, timeout_ms, **kwargs)

        results.append((t1, t2, t3, t4))
        cycle_count += 1

    return results


def wait_for_msg(
    msg_type: Union[PtpMsg, int],
    transport: InterfaceProtocol,
    msg_parser: Callable[[Any], bytes],
    timeout_ms: int = DEFAULT_TIMEOUT_MSEC,
    **kwargs
) -> Tuple[int, int]:
    """Wait for the specified message to be received.

    Args:
        msg_type (Union[PtpMsg, int]): Message to wait for.
        transport (InterfaceProtocol): Transport to receive message from.
        msg_parser (Callable[[Any], bytes]): Callable to parse the transport message and return a bytes payload.
        timeout_ms (int, optional): Time to wait for responses. Defaults to DEFAULT_TIMEOUT_MSEC.

    Raises:
        TimeoutError: Timed out waiting for message.
        PtpPacketError: Did not receive a valid PtpPacket.
        PtpPacketError: PtpPacket contained unexpected message.

    Returns:
        Tuple[int, int]: (payload, received timestamp)
    """
    logger.debug(f"Waiting for {PtpMsg.to_str(msg_type)}")

    transport_msgs = []
    data_available = False
    start = time.ticks_ms()  # pylint: disable=no-member

    while not data_available:
        if timeout_ms is not None and time.ticks_diff(time.ticks_ms(), start) > timeout_ms:  # pylint: disable=no-member
            raise TimeoutError(f"Timed out waiting for PTP message: {PtpMsg.to_str(msg_type)}.")

        data_available = transport.receive(transport_msgs, kwargs=kwargs)

    rx_ts = rtc.now()
    actual_msg_type = None
    payload = None
    packets = [msg_parser(msg) for msg in transport_msgs]

    # Process packets until we find one that parses successfully
    for pkt in packets:
        try:
            actual_msg_type, payload = parse_msg(pkt)
        except PtpPacketError as exc:
            logger.exception("PTP packet parsing failed. Skipping packet", exc_info=exc)
        else:
            break

    if actual_msg_type is None or payload is None:
        raise PtpPacketError(f"wait_for_msg - Received data, but did not receive a valid PtpPacket: {packets}")

    if actual_msg_type != msg_type:
        raise PtpPacketError(f"Rx'ed unexpected msg. Expected: {msg_type}. Actual: {actual_msg_type}.")

    logger.debug(f"Rx'ed msg: {PtpMsg.to_str(msg_type)}, Payload: {payload}, TS: {rx_ts}")
    return (payload, rx_ts)
