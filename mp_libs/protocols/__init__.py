"""Protocols Module"""
try:
    from typing import Any, List
except ImportError:
    pass


class InterfaceProtocol():
    """Pure virtual interface to be implemented by inheriting protocol class"""
    def __init__(self) -> None:
        pass

    def connect(self, **kwargs) -> bool:
        """Connect using implementing protocol.

        Returns:
            bool: True if connected, False if failed to connect.
        """
        raise RuntimeError("Must be implemented by inheriting class")

    def disconnect(self, **kwargs) -> bool:
        """Disconnect using implementing protocol.

        Returns:
            bool: True if disconnected, False if failed to disconnect.
        """
        raise RuntimeError("Must be implemented by inheriting class")

    def is_connected(self) -> bool:
        """Checks if protocol is connected or not.

        Returns:
            bool: True if connected, False if disconnected.
        """
        raise RuntimeError("Must be implemented by inheriting class")

    def receive(self, rxed_data: List, **kwargs) -> bool:
        """Receive data using implementing protocol.

        Args:
            rxed_data (List): Out variable to hold all received data.

        Returns:
            bool: True if data was received, False if no data available.
        """
        raise RuntimeError("Must be implemented by inheriting class")

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
        """Send data using implementing protocol.

        Args:
            msg (generic): Data to send.

        Returns:
            bool: True if send succeeded, False if it failed.
        """
        raise RuntimeError("Must be implemented by inheriting class")
