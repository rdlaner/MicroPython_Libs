"""ESP-Now Protocol Implementation

TODO: Metrics don't persist for espnow when using deep sleep mode...
TODO: Add retry attempts to espnow send?
"""
# pylint: disable=c-extension-no-member, disable=no-member, logging-fstring-interpolation, raise-missing-from

# Standard imports
import espnow
import io
import struct
import sys
import time
from collections import namedtuple
from micropython import const
try:
    from typing import List, Optional, Self, Union
except ImportError:
    pass

# Third party imports
from mp_libs import logging
from mp_libs.enum import Enum
from mp_libs.protocols import InterfaceProtocol
from mp_libs.protocols.wifi_protocols import WifiProtocol

# Local imports
try:
    from config import config  # type: ignore
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants
DEFAULT_TIMEOUT_MS = const(1000)
DEFAULT_SCAN_RESP_TIMEOUT_MS = const(500)
EPN_PACKET_MAX_SIZE = espnow.MAX_DATA_LEN
EPN_PACKET_DELIM = b"<EPN>"
EPN_PACKET_HDR_FORMAT_STR = f"<{len(EPN_PACKET_DELIM)}sBB"
EPN_PACKET_HDR_SIZE_BYTES = struct.calcsize(EPN_PACKET_HDR_FORMAT_STR)

# Globals
logger: logging.Logger = logging.getLogger("espnow-protocol")
logger.setLevel(config["logging_level"])
EspnowPacketHeader = namedtuple("EPNHeader",
                                (
                                    "delim",
                                    "cmd",
                                    "payload_size"
                                ))


class EpnCmds(Enum):
    CMD_SCAN_REQ = const(0)
    CMD_SCAN_RESP = const(1)
    CMD_PASS = const(2)
    _to_str_lut = {
        CMD_SCAN_REQ: "SCAN_REQ",
        CMD_SCAN_RESP: "SCAN_RESP",
        CMD_PASS: "PASS"
    }

    @classmethod
    def to_str(cls, cmd: "EpnCmds") -> str:
        return cls._to_str_lut[cmd]


class EspnowPacketError(Exception):
    pass


class TimeoutError(Exception):
    pass


class ScanError(Exception):
    pass


class EspnowPacket():
    """Packet object for all espnow transmissions

    A EspnowPacket is composed of a header and a payload:
    ----------------------------------------
    | <EPN> | Cmd | Payload Size | Payload |
    ----------------------------------------

    If the Cmd is EpnCmds.CMD_PASS, the payload contents will be routed up the upper layers.
    Otherwise, the packet is meant for processing at the espnow_protocol layer.
    """
    def __init__(self, cmd: Union[EpnCmds, int], payload: bytes = b"") -> None:
        self.header = EspnowPacketHeader(
            delim=EPN_PACKET_DELIM,
            cmd=cmd,
            payload_size=len(payload)
        )
        self.cmd = cmd
        self.payload = payload
        self._serialized_packet = b""

        self._serialize()

    def __len__(self) -> int:
        return len(self._serialized_packet)

    def _serialize(self) -> None:
        """Serializes this packet instance and saves it to self._serialized_packet"""
        if self.payload:
            format_str = EPN_PACKET_HDR_FORMAT_STR + f"{len(self.payload)}s"
            self._serialized_packet = struct.pack(
                format_str,
                self.header.delim,
                self.header.cmd,
                self.header.payload_size,
                self.payload
            )
        else:
            format_str = EPN_PACKET_HDR_FORMAT_STR
            self._serialized_packet = struct.pack(
                format_str,
                self.header.delim,
                self.header.cmd,
                self.header.payload_size
            )

    @classmethod
    def deserialize(cls, data: bytes) -> Self:
        """Deserializes a bytes object into an EspnowPacket instance.

        Args:
            data (bytes): bytes object produced by EspnowPacket.serialize()

        Raises:
            EspnowPacketError: Failed to deserialize packet
            EspnowPacketError: Invalid packet header delim
            EspnowPacketError: Invalid payload size
            EspnowPacketError: Invalid cmd

        Returns:
            Self: New instance of EspnowPacket.
        """
        # Extract header
        header_data = data[:EPN_PACKET_HDR_SIZE_BYTES]
        try:
            header = EspnowPacketHeader(*struct.unpack(EPN_PACKET_HDR_FORMAT_STR, header_data))
        except (ValueError, TypeError) as exc:
            buf = io.StringIO()
            sys.print_exception(exc, buf)  # type: ignore
            raise EspnowPacketError(
                f"Failed to deserialize packet header: {header_data}\nexc: {buf.getvalue()}")

        # Validate header
        if header.delim != EPN_PACKET_DELIM:
            raise EspnowPacketError(f"Invalid packet header delim: {header.delim}")
        if header.payload_size != len(data) - EPN_PACKET_HDR_SIZE_BYTES:
            raise EspnowPacketError(f"Packet payload size mismatch. Expected: {header.payload_size}. Actual: {len(data) - EPN_PACKET_HDR_SIZE_BYTES}")
        if not EpnCmds.contains(header.cmd):
            raise EspnowPacketError(f"Packet contains invalid cmd: {header.cmd}")

        # Build packet
        return cls(header.cmd, data[EPN_PACKET_HDR_SIZE_BYTES:])

    def serialize(self) -> bytes:
        """Serializes this packet into a bytes object.

        Returns:
            bytes: Serialized bytes object representing this packet instance.
        """
        return self._serialized_packet


class EspnowProtocol(InterfaceProtocol):
    """InterfaceProtocol implementation for sending and receiving espnow packets."""

    # Constants
    ESPNOW_BUFFER_SIZE_BYTES = const(8192)

    def __init__(
        self,
        peers,
        hostname: Optional[str] = None,
        channel: int = 0,
        timeout_ms: int = DEFAULT_TIMEOUT_MS
    ) -> None:
        super().__init__()
        self.peers = []
        self.hostname = hostname
        self.channel = channel
        self.timeout_ms = timeout_ms
        self.wifi = WifiProtocol(ssid=None, password=None, hostname=hostname, channel=channel)
        self.epn = espnow.ESPNow()
        self._configure(peers, hostname, channel, timeout_ms)

    def __repr__(self) -> str:
        return "ESPNOW"

    def _configure(self, peers, hostname: Optional[str], channel: int, timeout_ms: int):
        self.peers = []
        self.hostname = hostname
        self.channel = channel
        self.timeout_ms = timeout_ms

        # Create a wifi instance just to enable the station interface, not used otherwise
        self.wifi = WifiProtocol(ssid=None, password=None, hostname=hostname, channel=channel)
        self.wifi.disconnect(wait=False)

        # Configure EPN
        self.epn.active(True)
        self.epn.config(rxbuf=self.ESPNOW_BUFFER_SIZE_BYTES, timeout_ms=timeout_ms)

        try:
            if isinstance(peers, list):
                self.peers = peers
                for mac in peers:
                    self.epn.add_peer(mac)
            else:
                self.peers.append(peers)
                self.epn.add_peer(peers)
        except OSError as exc:
            if len(exc.args) > 1 and exc.args[1] == "ESP_ERR_ESPNOW_EXIST":
                logger.warning(f"Peer has already been added, skipping. Peers: {peers}")

        logger.debug("espnow configured")

    def _network_enable(self):
        self.epn.active(True)

    def _network_disable(self):
        self.epn.active(False)

    def connect(self, **kwargs) -> bool:
        """Connect espnow.

        Not really needed as ESPNow is a connection-less protocol. So this function just ensures
        that the wifi radio is turned on.

        Returns:
            bool: True if connected, False if failed to connect.
        """
        logger.info("Connecting espnow...")
        self._network_enable()

        # If epn was previously disconnected, then we must re-configure since de-activating epn
        # causes all config data to be lost.
        if not self.epn.get_peers():
            self._configure(self.peers, self.hostname, self.channel, self.timeout_ms)

        return True

    def disconnect(self, **kwargs) -> bool:
        """Disconnect espnow.

        Not really needed as ESPNow is a connection-less protocol. So this function just ensures
        that the wifi radio is turned off.

        Returns:
            bool: True if connected, False if failed to connect.
        """
        logger.info("Disconnecting espnow...")
        self._network_disable()

        return True

    def is_connected(self) -> bool:
        """Not really needed as ESPNow is a connection-less protocol. Instead, this function will
        just return True if ESPNow is active and False if otherwise.

        Returns:
            bool: True if active, False if not.
        """
        return self.epn.active() is True

    def process_packet(self, packet: EspnowPacket) -> Union[EspnowPacket, bytes]:
        """Processes an EspnowPacket.

        For any local EpnCmds, this function will process them here.
        For a EpnCmds.CMD_PASS packet, this function will return the packet payload to be passed
        up to the upper layers.

        Args:
            packet (EspnowPacket): Packet to process.

        Raises:
            EspnowPacketError: Packet contains unsupported EpnCmd

        Returns:
            Union[EspnowPacket, bytes]: Either the packets bytes payload or the processed packet itself.
        """
        logger.debug(f"Processing packet: {packet}")
        result = b""

        if packet.cmd == EpnCmds.CMD_PASS:
            result = packet.payload
        elif packet.cmd == EpnCmds.CMD_SCAN_REQ:
            logger.debug("Sending SCAN RESP")
            scan_resp = EspnowPacket(EpnCmds.CMD_SCAN_RESP)
            self.send(scan_resp)
        elif packet.cmd == EpnCmds.CMD_SCAN_RESP:
            logger.debug("Rx'ed SCAN RESP")
            result = packet
        else:
            raise EspnowPacketError(f"Packet contains invalid cmd: {packet.cmd}")

        return result

    def receive(self, rxed_data: list, **kwargs) -> bool:
        """Receives all available espnow packets and appends them to the `rxed_data` list.

        Each element of received data added to the `rxed_data` list will be a tuple:
         * (Sender MAC address, Data)

        Args:
            rxed_data (list): Received espnow packets, if any.
            recover (bool, optional): Attempt recovery if loop function fails.

        Returns:
            bool: True if data was received, False if no data available.
        """
        data_available = False
        recover = kwargs.get("recover", False)

        # Read as many espnow packets as are available
        while True:
            if self.epn.any():
                data_available = True

                # Read out espnow msg
                try:
                    mac, msg = self.epn.recv()
                    if mac is None:
                        break
                except (OSError, ValueError) as exc:
                    logger.exception("Failed receiving espnow packet", exc_info=exc)
                    data_available = False
                    buf = io.StringIO()
                    sys.print_exception(exc, buf)  # type: ignore
                    if recover:
                        if not self.recover():
                            raise RuntimeError(f"Failed to recover after espnow receive failure.\n{buf.getvalue()}")
                    else:
                        raise RuntimeError(f"Did not attempt recovery.\n{buf.getvalue()}")

                # Process espnow msg
                packet = EspnowPacket.deserialize(msg)  # type: ignore , We protect against this by checking if mac is None.
                if payload := self.process_packet(packet):
                    rxed_data.append(payload)
            else:
                break

        return data_available

    def recover(self, **kwargs) -> bool:
        """Attempt to recover espnow protocol.

        Returns:
            bool: True if recovery succeeded, False if it failed.
        """
        logger.info("Attempting espnow recovery... ")
        peers = []
        for peer in self.epn.get_peers():
            peers.append(peer[0])

        del self.wifi
        del self.epn
        self._configure(peers, self.hostname, self.channel, self.timeout_ms)

        return True

    def scan(self, **kwargs) -> List:
        timeout_ms = kwargs.get("timeout", DEFAULT_SCAN_RESP_TIMEOUT_MS)
        channel_found = False
        channel = 0

        while channel <= 11 and not channel_found:
            channel += 1
            logger.debug(f"Changing channel to: {channel}")
            if not self.update_channel(channel):
                raise RuntimeError(f"Failed to update espnow/wifi channel to {channel}")

            # Send scan request
            logger.debug("Sending SCAN REQ")
            self.send(EspnowPacket(EpnCmds.CMD_SCAN_REQ))

            # Wait for response
            response = []
            start = time.ticks_ms()
            try:
                while True:
                    if timeout_ms is not None and time.ticks_diff(time.ticks_ms(), start) > timeout_ms:
                        raise TimeoutError()

                    data_available = self.receive(response)

                    if data_available and isinstance(response[0], EspnowPacket) and response[0].cmd == EpnCmds.CMD_SCAN_RESP:
                        channel_found = True
                        break
            except TimeoutError:
                pass

        if channel > 11:
            raise ScanError("No Scan Resp received on channels 1-11")

        return [channel]

    def send(self, msg, **kwargs) -> bool:
        """Sends user provided message as payload in an espnow packet.

        Message size must be less than or equal to the max espnow payload size: 255 bytes

        Args:
            msg (generic): Data to send.

        Returns:
            bool: True if send succeeded, False if it failed.
        """
        if isinstance(msg, EspnowPacket):
            if len(msg) > EPN_PACKET_MAX_SIZE:
                raise RuntimeError(f"espnow msg len is greater than {EPN_PACKET_MAX_SIZE} bytes: {len(msg)}")

            epn_packet = msg
        else:
            if len(msg) + EPN_PACKET_HDR_SIZE_BYTES > EPN_PACKET_MAX_SIZE:
                raise RuntimeError(
                    f"espnow msg len must be <= EPN_PACKET_MAX_SIZE - EPN_PACKET_HDR_SIZE_BYTES: {EPN_PACKET_MAX_SIZE - EPN_PACKET_HDR_SIZE_BYTES}")

            epn_packet = EspnowPacket(EpnCmds.CMD_PASS, msg)

        success = True
        try:
            self.epn.send(epn_packet.serialize())
        except (ValueError, OSError) as exc:
            logger.exception("ESPNOW failed sending packet", exc_info=exc)
            success = False

        return success

    def send_metrics(self, **kwargs) -> bool:
        pass
        # TODO: redo this fxn. Use ESPNow.stats
        # metrics = {}
        # metrics["Header"] = "metrics"
        # metrics["send_success"] = self.epn.send_success
        # metrics["send_failure"] = self.epn.send_failure

        # logger.info(f"EPN SEND SUCCESS: {self.epn.send_success}")
        # logger.info(f"EPN SEND FAILURE: {self.epn.send_failure}")

        # try:
        #     self.epn.send(json.dumps(metrics))  # pylint: disable=too-many-function-args
        # except (ValueError, RuntimeError, IDFError) as exc:
        #     print(f"ESPNOW failed sending metrics\n{exc}")

    def update_channel(self, channel: int) -> bool:
        # espnow must be deactivated/reset in order to change the underlying wifi channel
        self._network_disable()

        # Re-run configuration, this will re-enable espnow as well as update the wifi channel
        self._configure(self.peers, self.hostname, channel, self.timeout_ms)

        return self.wifi._sta.config("channel") == channel
