"""Basic Precision Time Protocol (PTP) implementation

TODO: Need a global way of allocating timer instances since esp32 port doesn't support virtual timers
"""
# pylint: disable=raise-missing-from

# Standard imports
import io
import struct
import sys
import time
from collections import namedtuple
from machine import RTC, Timer           # pylint: disable=import-error,
from micropython import const, schedule  # pylint: disable=import-error, wrong-import-order
try:
    from typing import Any, Callable, List, Optional, Tuple, Union, TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

# Third party imports
from mp_libs import event_sm
from mp_libs import logging
from mp_libs import statistics
from mp_libs.enum import Enum
from mp_libs.mpy_decimal import DecimalNumber

# Local imports
try:
    from config import config  # type: ignore
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants
PTP_PACKET_DELIM = b"<PTP>"
PTP_PACKET_FORMAT_STR = f"<{len(PTP_PACKET_DELIM)}sBQ"
PTP_PACKET_SIZE_BYTES = struct.calcsize(PTP_PACKET_FORMAT_STR)
DEFAULT_TIMEOUT_MSEC = const(750)

# Globals
logger: logging.Logger = logging.getLogger("PTP")
logger.setLevel(config["logging_level"])
rtc = RTC()
if TYPE_CHECKING:
    PtpStateBase = event_sm.InterfaceState["PtpSM"]
else:
    PtpStateBase = event_sm.InterfaceState


# Tuple defining all of the PtpPacket elements
PtpPacketTuple = namedtuple("PtpPacket", ("delim", "cmd", "payload"))


class PtpPacketError(Exception):
    """PTP Packet Error Exception"""
    def __init__(self, message: str) -> None:
        msg = f"PTP - {message}"
        super().__init__(msg)


class TimeoutError(Exception):  # pylint: disable=redefined-builtin
    """General timeout exception"""


class PtpCmd(Enum):
    """All PTP message types"""
    SYNC_REQ = const(0)
    SYNC_RESP = const(1)
    DELAY_REQ = const(2)
    DELAY_RESP = const(3)
    _to_str_lut = {
        SYNC_REQ: "SYNC REQ",
        SYNC_RESP: "SYNC_RESP",
        DELAY_REQ: "DELAY_REQ",
        DELAY_RESP: "DELAY_RESP"
    }

    @classmethod
    def to_str(cls, cmd: Union["PtpCmd", int]) -> str:
        """Get the associated string for a given PtpCmd enum value.

        Args:
            cmd (PtpCmd): PtpCmd enum value (eg PtpCmd.SYNC_REQ).

        Returns:
            str: Enum string value.
        """
        return cls._to_str_lut[cmd]


class PtpPacket():
    """PTP packet definition used for all PTP transmissions.

    PTP packet composition:
    -------------------------
    | <PTP> | Cmd | Payload |
    -------------------------

    Cmd must be one of the PtpCmd values. Payload must be an int.
    """
    def __init__(self, cmd: Union[PtpCmd, int], payload: int) -> None:
        self._packet = PtpPacketTuple(
            delim=PTP_PACKET_DELIM,
            cmd=cmd,
            payload=payload
        )
        self._serialized_packet = b""
        self._serialize()

    def _serialize(self) -> None:
        self._serialized_packet = struct.pack(
            PTP_PACKET_FORMAT_STR,
            self._packet.delim,
            self._packet.cmd,
            self._packet.payload
        )

    @property
    def cmd(self) -> PtpCmd:
        """Get packet message type.

        Returns:
            PtpCmd: Packet message type.
        """
        return self._packet.cmd

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
            PtpPacketError: Invalid cmd.
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
        if not PtpCmd.contains(ptp_tuple.cmd):
            raise PtpPacketError(f"Packet contains invalid cmd: {ptp_tuple.cmd}")
        if not isinstance(ptp_tuple.payload, int):
            raise PtpPacketError(f"Invalid payload: {ptp_tuple.payload}")

        return cls(ptp_tuple.cmd, ptp_tuple.payload)

    def serialize(self) -> bytes:
        """Serializes this packet instance into a bytes object.

        Returns:
            bytes: Serialized bytes object representing this packet instance.
        """
        return self._serialized_packet


class PtpSig(Enum):
    """All PTP signals"""
    SIG_BEGIN = const(0)
    SIG_SYNC_REQ = const(1)
    SIG_SYNC_RESP = const(2)
    SIG_DELAY_REQ = const(3)
    SIG_DELAY_RESP = const(4)
    SIG_TIMEOUT = const(5)


class PtpEvt(event_sm.Event):
    """PTP state machine event"""
    def __init__(
        self,
        signal: int,
        payload_ts: int = 0,
        rx_ts: int = 0
    ) -> None:
        super().__init__(signal)
        self.payload_ts = payload_ts
        self.rx_ts = rx_ts


class PtpSM(event_sm.StateMachine):
    """PTP state machine"""
    def __init__(
        self,
        name: str,
        tx_fxn: Callable[[Any], bool],
        timeout_ms: int,
        num_sync_cycles: int
    ) -> None:
        super().__init__(name)
        self._cycle_count = 0
        self._timeout_timer = Timer(3)
        self.tx_fxn = tx_fxn
        self.timeout_ms = timeout_ms
        self.num_sync_cycles = num_sync_cycles
        self.timestamps: List[Tuple] = []
        self.sync_complete_cbs = set()
        self.sync_started_cbs = set()
        self.t1 = 0
        self.t2 = 0
        self.t3 = 0
        self.t4 = 0

    def cycle_count_decr(self):
        """Decrement cycle count by 1"""
        if self._cycle_count > 0:
            self._cycle_count -= 1

    def cycle_count_reset(self):
        """Reset cycle count back to num_sync_cycles"""
        self._cycle_count = self.num_sync_cycles

    def cycle_count(self) -> int:
        """Get current cycle count value"""
        return self._cycle_count

    def timer_start(self):
        """Start timeout timer"""
        self._timeout_timer.init(mode=Timer.ONE_SHOT, period=self.timeout_ms, callback=timeout_timer_cb)

    def timer_stop(self):
        """Stop timeout timer"""
        self._timeout_timer.deinit()

    def timestamp_clear(self):
        """Clear current and cached timestamp values"""
        self.t1 = 0
        self.t2 = 0
        self.t3 = 0
        self.t4 = 0
        self.timestamps = []


class StateReady(PtpStateBase):
    """PTP Ready state"""
    def __init__(self) -> None:
        super().__init__("Ready")

    def entry(self):
        logger.debug(f"Entry: {self._name}")
        self.sm.timer_stop()
        self.sm.cycle_count_reset()
        self.sm.timestamp_clear()

    def exit(self):
        logger.debug(f"Exit: {self._name}")

    def process_evt(self, evt: event_sm.Event) -> None:
        logger.debug(f"Proc: {self._name}, Evt: {evt}")

        if evt.signal == PtpSig.SIG_SYNC_REQ:
            self.transition(StateSyncResp())
        elif evt.signal == PtpSig.SIG_BEGIN:
            for cb in self.sm.sync_started_cbs:
                cb()
            self.transition(StateSyncReq())
        else:
            logger.warning(f"{self._name}: rx'ed unhandled evt: {evt}")


class StateSyncReq(PtpStateBase):
    "PTP Sync Request state"
    def __init__(self) -> None:
        super().__init__("SyncReq")

    def entry(self):
        logger.debug(f"Entry: {self._name}")
        if self.sm.cycle_count() == 0:
            self.transition(StateReady())
        else:
            sync_req(self.sm.tx_fxn, self.sm.num_sync_cycles)
            self.sm.timer_start()

    def exit(self):
        logger.debug(f"Exit: {self._name}")

    def process_evt(self, evt: PtpEvt) -> None:
        logger.debug(f"Proc: {self._name}, Evt: {evt}")

        if evt.signal == PtpSig.SIG_TIMEOUT:
            self.sm.cycle_count_decr()
            self.transition(StateSyncReq())
        elif evt.signal == PtpSig.SIG_SYNC_RESP:
            self.sm.timer_stop()
            self.sm.t2 = evt.rx_ts
            self.sm.t1 = evt.payload_ts
            self.transition(StateDelayReq())


class StateSyncResp(PtpStateBase):
    """PTP Sync Response state"""
    def __init__(self) -> None:
        super().__init__("SyncResp")

    def entry(self):
        logger.debug(f"Entry: {self._name}")
        sync_resp(self.sm.tx_fxn)

    def exit(self):
        logger.debug(f"Exit: {self._name}")

    def process_evt(self, evt: PtpEvt) -> None:
        logger.debug(f"Proc: {self._name}, Evt: {evt}")

        if evt.signal == PtpSig.SIG_SYNC_REQ:
            sync_resp(self.sm.tx_fxn)
        elif evt.signal == PtpSig.SIG_DELAY_REQ:
            self.sm.t4 = evt.rx_ts
            self.transition(StateDelayResp())
        else:
            logger.warning(f"{self._name}: rx'ed unhandled evt: {evt}")


class StateDelayReq(PtpStateBase):
    """PTP Delay Request state"""
    def __init__(self) -> None:
        super().__init__("DelayReq")

    def entry(self):
        logger.debug(f"Entry: {self._name}")
        self.sm.t3 = delay_req(self.sm.tx_fxn)
        self.sm.timer_start()

    def exit(self):
        logger.debug(f"Exit: {self._name}")

    def process_evt(self, evt: PtpEvt) -> None:
        logger.debug(f"Proc: {self._name}, Evt: {evt}")

        if evt.signal == PtpSig.SIG_TIMEOUT:
            self.sm.cycle_count_decr()
            self.transition(StateSyncReq())
        elif evt.signal == PtpSig.SIG_DELAY_RESP:
            self.sm.timer_stop()
            self.sm.t4 = evt.payload_ts
            self.sm.timestamps.append((self.sm.t1, self.sm.t2, self.sm.t3, self.sm.t4))
            self.sm.cycle_count_decr()

            if self.sm.cycle_count() == 0:
                calculate_and_apply_offset(self.sm.timestamps)
                for cb in self.sm.sync_complete_cbs:
                    cb()

                self.transition(StateReady())
            else:
                self.transition(StateSyncReq())


class StateDelayResp(PtpStateBase):
    """PTP Delay Response state"""
    def __init__(self) -> None:
        super().__init__("DelayResp")

    def entry(self):
        logger.debug(f"Entry: {self._name}")
        delay_resp(self.sm.tx_fxn, self.sm.t4)

    def exit(self):
        logger.debug(f"Exit: {self._name}")

    def process_evt(self, evt: PtpEvt) -> None:
        logger.debug(f"Proc: {self._name}, Evt: {evt}")

        if evt.signal == PtpSig.SIG_SYNC_REQ:
            self.transition(StateSyncResp())
        else:
            logger.warning(f"{self._name}: rx'ed unhandled evt: {evt}")


################################################################################
#                           Public API
################################################################################
def cb_register_sync_start(cb: Callable[[], None]) -> None:
    """Register a callback to be invoked when PTP sync starts.

    Args:
        cb (Callable[[], None]): Callback

    Raises:
        RuntimeError: PTP state machine not yet initialized.
    """
    if not _ptp_sm:
        raise RuntimeError("PTP SM not yet initialized")

    _ptp_sm.sync_started_cbs.add(cb)


def cb_register_sync_complete(cb: Callable[[], None]) -> None:
    """Register a callback to be invoked when PTP sync is completed.

    Args:
        cb (Callable[[], None]): Callback

    Raises:
        RuntimeError: PTP state machine not yet initialized.
    """
    if not _ptp_sm:
        raise RuntimeError("PTP SM not yet initialized")

    _ptp_sm.sync_complete_cbs.add(cb)


def cb_unregister_sync_start(cb: Callable[[], None]) -> None:
    """Unregister a callback to be invoked when PTP sync starts.

    Args:
        cb (Callable[[], None]): Callback

    Raises:
        RuntimeError: PTP state machine not yet initialized.
    """
    if not _ptp_sm:
        raise RuntimeError("PTP SM not yet initialized")

    try:
        _ptp_sm.sync_started_cbs.remove(cb)
    except KeyError:
        logger.warning(f"Callback never registered: {cb.__name__}")


def cb_unregister_sync_complete(cb: Callable[[], None]) -> None:
    """Unregister a callback to be invoked when PTP sync is completed.

    Args:
        cb (Callable[[], None]): Callback

    Raises:
        RuntimeError: PTP state machine not yet initialized.
    """
    if not _ptp_sm:
        raise RuntimeError("PTP SM not yet initialized")

    try:
        _ptp_sm.sync_complete_cbs.remove(cb)
    except KeyError:
        logger.warning(f"Callback never registered: {cb.__name__}")


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


def process_packet(packet: PtpPacket) -> None:
    """Process received PTP packet and generate appropriate state machine event.

    Args:
        packet (PtpPacket): PTP packet received from PTP peer.
    """
    if not _ptp_sm:
        raise RuntimeError("PTP SM not yet initialized")

    if packet.cmd == PtpCmd.SYNC_REQ:
        _evt_sync_req.payload_ts = packet.payload
        _evt_sync_req.rx_ts = rtc.now()
        _ptp_sm.process_evt(_evt_sync_req)
    elif packet.cmd == PtpCmd.SYNC_RESP:
        _evt_sync_resp.payload_ts = packet.payload
        _evt_sync_resp.rx_ts = rtc.now()
        _ptp_sm.process_evt(_evt_sync_resp)
    elif packet.cmd == PtpCmd.DELAY_REQ:
        _evt_delay_req.payload_ts = packet.payload
        _evt_delay_req.rx_ts = rtc.now()
        _ptp_sm.process_evt(_evt_delay_req)
    elif packet.cmd == PtpCmd.DELAY_RESP:
        _evt_delay_resp.payload_ts = packet.payload
        _evt_delay_resp.rx_ts = rtc.now()
        _ptp_sm.process_evt(_evt_delay_resp)
    else:
        raise RuntimeError(f"Rx'ed unexpected PTP cmd: {packet.cmd}")


def state_machine_init(
    tx_fxn: Callable[[Any], bool],
    timeout_ms: int = DEFAULT_TIMEOUT_MSEC,
    num_sync_cycles: int = 1
) -> None:
    """Initialize PTP state machine.

    Args:
        tx_fxn (Callable[[Any], bool]): Function for sending PTP packets.
        timeout_ms (int, optional): PTP tx/rx timeout in msec. Defaults to DEFAULT_TIMEOUT_MSEC.
        num_sync_cycles (int, optional): Number of synchronization cycles performed per sync. Defaults to 1.
    """
    global _ptp_sm
    _ptp_sm = PtpSM("PTP SM", tx_fxn, timeout_ms, num_sync_cycles)
    _ptp_sm.register_state(StateReady())
    _ptp_sm.register_state(StateSyncReq())
    _ptp_sm.register_state(StateSyncResp())
    _ptp_sm.register_state(StateDelayReq())
    _ptp_sm.register_state(StateDelayResp())


def state_machine_start() -> None:
    """Start PTP state machine.

    NOTE: Must initialize state machine via `state_machine_init` before starting it.

    Raises:
        RuntimeError: State machine not initialized.
    """
    if not _ptp_sm:
        raise RuntimeError("PTP SM not yet initialized")

    _ptp_sm.start(StateReady())


def time_sync(
    is_async: bool = True,
    rx_fxn: Optional[Callable[[List], bool]] = None,
    timeout_ms: int = const(2000),
    force: bool = False
) -> bool:
    """Start PTP time sync process

    NOTE: Must initialize (`state_machine_init`) and start (`state_machine_start`) first.

    Args:
        is_async (bool, optional): Perform time sync asynchronously. Defaults to True.
        rx_fxn: (Optional[Callable[[List], bool]]): Network receive function. Only used if is_async is False.
        timeout_ms: (int): Timeout value when is_async is False. Defaults to 2000.
        force (bool, optional): Force a new sync regardless of current state. Defaults to False.

    Returns:
        bool: True if operation succeeded, False if failed.
    """
    if not _ptp_sm:
        logger.error("PTP SM not yet initialized")
        return False

    if not is_async and not rx_fxn:
        logger.error("Can't perform synchronous time sync without an rx_fxn")
        return False

    if _ptp_sm.current_state != StateReady() and force is True:
        _ptp_sm.start(StateReady())

    if _ptp_sm.current_state != StateReady():
        logger.warning("Skipping PTP time sync, SM not ready")
        return False

    if not is_async:
        sync_done = False

        def sync_cb():
            nonlocal sync_done
            sync_done = True
        cb_register_sync_complete(sync_cb)

    success = True
    _ptp_sm.process_evt(_evt_begin)

    if not is_async:
        rxed_data = []
        start = time.ticks_ms()

        while not sync_done:
            if time.ticks_diff(time.ticks_ms(), start) > timeout_ms:
                logger.error("Timed out attempting to perform PTP time sync")
                success = False
                break

            _ = rx_fxn(rxed_data)

        cb_unregister_sync_complete(sync_cb)

    return success


################################################################################
#                           Private API
################################################################################
_evt_begin = PtpEvt(PtpSig.SIG_BEGIN)
_evt_sync_req = PtpEvt(PtpSig.SIG_SYNC_REQ)
_evt_sync_resp = PtpEvt(PtpSig.SIG_SYNC_RESP)
_evt_delay_req = PtpEvt(PtpSig.SIG_DELAY_REQ)
_evt_delay_resp = PtpEvt(PtpSig.SIG_DELAY_RESP)
_evt_timeout = PtpEvt(PtpSig.SIG_TIMEOUT)
_ptp_sm: Optional["PtpSM"] = None


def calculate_and_apply_offset(timestamps: List[Tuple]) -> int:
    """Takes in a list of T1-T4 timestamp tuples, calculates and applies the average offset.

    Args:
        timestamps (List[Tuple]): List of T1-T4 timestamp tuples.

    Returns:
        int: Offset that was calculated and applied
    """
    # Sanitize timestamps - consider 0 an invalid timestamp value
    timestamps = [t for t in timestamps if 0 not in t]
    offsets = [calculate_offset(t1, t2, t3, t4) for t1, t2, t3, t4 in timestamps]

    if offsets:
        ave_offset = process_offsets(offsets)
        rtc.offset(ave_offset)

        logger.debug(f"timestamps: {timestamps}")
        logger.debug(f"offsets: {offsets}")
        logger.debug(f"ave offset: {ave_offset}")
        return ave_offset

    logger.warning("No PTP offsets calculated after sanitizing inputs")
    return 0


def calculate_delay(t1: int, t2: int, t3: int, t4: int) -> int:
    """Calculates the transmission delay value from t1-t4 timestamps.

    Args:
        t1 (int): SYNC_RESP TX timestamp.
        t2 (int): SYNC_RESP RX timestamp.
        t3 (int): DELAY_REQ TX timestamp.
        t4 (int): DELAY_REQ RX timestamp.

    Returns:
        int: Transmission delay value.
    """
    return ((t2 - t1) + (t4 - t3)) // 2


def calculate_offset(t1: int, t2: int, t3: int, t4: int) -> int:
    """Calculates the offset value from t1-t4 timestamps.

    Args:
        t1 (int): SYNC_RESP TX timestamp.
        t2 (int): SYNC_RESP RX timestamp.
        t3 (int): DELAY_REQ TX timestamp.
        t4 (int): DELAY_REQ RX timestamp.

    Returns:
        int: Offset value.
    """
    return ((t2 - t1) - (t4 - t3)) // 2


def delay_req(tx_fxn: Callable[[Any], bool], **kwargs) -> int:
    """Send DELAY_REQ packet.

    Args:
        tx_fxn (Callable[[Any], bool]): Send function to transmit message

    Returns:
        int: T3 timestamp.
    """
    logger.debug("Sending DELAY REQ")
    t3 = rtc.now()
    tx_fxn(PtpPacket(PtpCmd.DELAY_REQ, t3).serialize(), **kwargs)
    return t3


def delay_resp(tx_fxn: Callable[[Any], bool], ts: int, **kwargs) -> None:
    """Send DELAY_RESP packet.

    Args:
        tx_fxn (Callable[[Any], bool]): Send function to transmit data
        ts (int): T4 timestamp.
    """
    logger.debug("Sending DELAY RESP")
    tx_fxn(PtpPacket(PtpCmd.DELAY_RESP, ts).serialize(), **kwargs)


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


def sync_req(tx_fxn: Callable[[Any], bool], num_sync_cycles: int = 1, **kwargs) -> None:
    """Send SYNC_REQ packet.

    Args:
        tx_fxn (Callable[[Any], bool]): Send function to transmit message
        num_sync_cycles (int, optional): Number of PTP sync cycles to perform. Defaults to 1.
    """
    logger.debug("Sending SYNC REQ")
    tx_fxn(PtpPacket(PtpCmd.SYNC_REQ, num_sync_cycles).serialize(), **kwargs)


def sync_resp(tx_fxn: Callable[[Any], bool], **kwargs) -> int:
    """Send SYNC_RESP packet.

    Args:
        tx_fxn (Callable[[Any], bool]): Send function to transmit message

    Returns:
        int: T1 timestamp.
    """
    logger.debug("Sending SYNC RESP")
    t1 = rtc.now()
    tx_fxn(PtpPacket(PtpCmd.SYNC_RESP, t1).serialize(), **kwargs)
    return t1


def timeout_work(sm: PtpSM) -> None:
    """Inject timeout event to state machine.

    Args:
        sm (PtpSM): PTP state machine reference.
    """
    sm.process_evt(_evt_timeout)


def timeout_timer_cb(timer):
    """Timeout timer callback"""
    _ptp_sm.timer_stop()
    schedule(timeout_work, _ptp_sm)
