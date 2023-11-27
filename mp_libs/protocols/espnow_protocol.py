"""ESP-Now Protocol Implementation"""
# pylint: disable=c-extension-no-member, disable=no-member, logging-fstring-interpolation
# pyright: reportGeneralTypeIssues=false
# Standard imports
import binascii
import espnow
import network
import time
from micropython import const

# Third party imports
from mp_libs import logging
from mp_libs.protocols import InterfaceProtocol
from mp_libs.protocols.wifi_protocols import WifiProtocol

# Local imports
try:
    from config import config
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants

# Globals
logger = logging.getLogger("espnow-protocol")
logger.setLevel(config["logging_level"])
stream_handler = logging.StreamHandler()
stream_handler.setLevel(config["logging_level"])
stream_handler.setFormatter(logging.Formatter("%(mono)d %(name)s-%(levelname)s:%(message)s"))
logger.addHandler(stream_handler)

# TODO: Metrics don't persist for espnow when using deep sleep mode...
# TODO: Add retry attempts to espnow send?


class EspnowProtocol(InterfaceProtocol):
    """InterfaceProtocol implementation for sending and receiving espnow packets."""

    # Constants
    ESPNOW_BUFFER_SIZE_BYTES = const(8192)

    def __init__(self, peers, hostname: str = None, channel: int = 0) -> None:
        super().__init__()
        self.wifi = None
        self.epn = None
        self.hostname = None
        self.channel = None
        self._configure(peers, hostname, channel)

    def __repr__(self) -> str:
        return "ESPNOW"

    def _configure(self, peers, hostname, channel):
        self.hostname = hostname
        self.channel = channel

        # Create a wifi instance just to enable the station interface, not used otherwise
        self.wifi = WifiProtocol(ssid=None, password=None, hostname=hostname, channel=channel)
        self.wifi.disconnect(wait=False)

        self.epn = espnow.ESPNow()
        self.epn.active(True)
        self.epn.config(rxbuf=self.ESPNOW_BUFFER_SIZE_BYTES)

        if isinstance(peers, list):
            for mac in peers:
                self.epn.add_peer(mac, channel=channel)
        else:
            self.epn.add_peer(peers, channel=channel)

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
                try:
                    for data in self.epn:
                        rxed_data.append(data)
                except (OSError, ValueError) as exc:
                    logger.exception("Failed receiving espnow packet", exc_info=exc)
                    data_available = False
                    if recover:
                        if not self.recover():
                            raise RuntimeError(f"Failed to recover after espnow receive failure.\nexc={exc}")
                    else:
                        raise RuntimeError(f"Did not attempt recovery.\nexc={exc}")
            else:
                break

        for info in self.epn.peers_table:
            logger.debug(f"Peer MAC: {info['peer']}, time: {info['time_ms']}, rssi: {info['rssi']}")

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
        self._configure(peers, self.hostname, self.channel)

        return True

    def send(self, msg, **kwargs) -> bool:
        """Sends user provided message as payload in an espnow packet.

        Message size must be less than or equal to the max espnow payload size: 255 bytes

        Args:
            msg (generic): Data to send.

        Returns:
            bool: True if send succeeded, False if it failed.
        """
        success = True

        if len(msg) > espnow.MAX_DATA_LEN:
            raise RuntimeError(f"espnow msg len is greater than {espnow.MAX_DATA_LEN} bytes: {len(msg)}")

        try:
            self.epn.send(msg)
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
