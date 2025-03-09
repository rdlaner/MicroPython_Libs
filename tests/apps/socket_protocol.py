"""Socket protocol
Primarily meant for use on host.
"""
# Standard imports
import select
import socket
from typing import Any, List

# Third party imports
from mp_libs import logging
from mp_libs.protocols import InterfaceProtocol

# Local imports
try:
    from config import config
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants
DEFAULT_MAX_RECV_BYTES = 1024

# Globals
logger: logging.Logger = logging.getLogger("socket-protocols")
logger.setLevel(config["logging_level"])


class SocketProtocol(InterfaceProtocol):
    def __init__(self, is_client: bool, ip: str = "127.0.0.1", port: int = 5080) -> None:
        super().__init__()
        self._is_client = is_client
        self._ip = ip
        self._port = port
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_data = {
            "cxn_socket": None,
            "client_addr": None
        }

    def connect(self, **kwargs) -> bool:
        # TODO: Probably need to do some check here if we are already connected and/or socket already has
        # been created
        if self._is_client:
            self._socket.connect((self._ip, self._port))
        else:
            self._socket.bind((self._ip, self._port))
            self._socket.listen(1)
            conn, addr = self._socket.accept()
            self._server_data["cxn_socket"] = conn
            self._server_data["client_addr"] = addr

    def disconnect(self, **kwargs) -> bool:
        # TODO: Check if sockets are actually connected first
        if not self._is_client and self._server_data["cxn_socket"] is not None:
            self._server_data["cxn_socket"].close()

        self._socket.close()

    def is_connected(self) -> bool:
        """Checks if protocol is connected or not.

        Returns:
            bool: True if connected, False if disconnected.
        """
        raise RuntimeError("Must be implemented by inheriting class")

    def receive(self, rxed_data: List, **kwargs) -> bool:
        max_rx_bytes = kwargs.get("max_rx_bytes", DEFAULT_MAX_RECV_BYTES)

        if self._is_client:
            cxn_socket = self._socket
        else:
            cxn_socket = self._server_data["cxn_socket"]

        readable, _, _ = select.select([cxn_socket], [], [], 0)
        if readable:
            data = cxn_socket.recv(max_rx_bytes)

            logger.debug(f"Received: {data}")
            rxed_data.append(data)

        return len(readable) > 0

    def recover(self, **kwargs) -> bool:
        """Perform recovery using implementing protocol

        Returns:
            bool: True if recovery succeeded, False if it failed.
        """
        raise RuntimeError("Must be implemented by inheriting class")

    def scan(self, **kwargs) -> List[Any]:
        """Perform a scan operation using implementing protocol.

        Returns:
            List[Any]: List of scan results
        """
        raise RuntimeError("Must be implemented by inheriting class")

    def send(self, msg, **kwargs) -> bool:
        # TODO: Probably check to ensure we have an actual connection
        logger.debug(f"Sending: {msg}")
        if self._is_client:
            self._socket.sendall(msg)
        else:
            self._server_data["cxn_socket"].sendall(msg)
        return True
