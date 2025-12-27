"""Mocks for the protocol drivers"""
# Standard imports
from typing import Any, List, Optional, Tuple

# Local imports
from mp_libs.protocols import InterfaceProtocol


class MockWifiProtocol(InterfaceProtocol):
    def __init__(self, ssid: str, password: str, hostname: str = None, channel: int = None) -> None:
        super().__init__()
        self._ssid = ssid
        self._password = password
        self._channel = channel
        self._connected = None

        if hostname:
            self._hostname = hostname
        else:
            # self._hostname = binascii.hexlify(machine.unique_id()).decode("utf-8")
            pass

    def connect(self, **kwargs) -> bool:
        self._connected = True
        return True

    def disconnect(self, **kwargs) -> bool:
        self._connected = False
        return True

    def is_connected(self):
        return self._connected

    def receive(self, rxed_data: List, **kwargs) -> bool:
        return True

    def recover(self, **kwargs) -> bool:
        return True

    def scan(self, **kwargs) -> List[Any]:
        return []

    def send(self, msg, **kwargs) -> bool:
        return True


class MockESPNow(InterfaceProtocol):
    _peers = []

    def __init__(self, mac: bytes = b"123456789", transport: Optional[InterfaceProtocol] = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._mac = mac
        self._transport = transport
        self._active = False
        self._rx_exc = False
        self._rxbuf_size = 526
        self._timeout_ms = 300_000
        self._config_call_count = 0
        self._sent_msgs = []
        self._received_msgs = []

    def active(self, flag: Optional[Any] = None):
        if flag is None:
            return self._active

        self._active = bool(flag)

        # Clear peers when deactivating to simulate what happens w/ hardware
        if flag is False:
            self._peers = []
            if self._transport is not None:
                self._transport.disconnect()
        else:
            if self._transport is not None:
                self._transport.connect()

    def add_peer(self, mac):
        if mac in self._peers:
            raise OSError(0, "ESP_ERR_ESPNOW_EXIST")
        self._peers.append(mac)

    def any(self) -> bool:
        if self._transport is not None:
            self._transport.receive(self._received_msgs)
            return len(self._received_msgs) > 0

        return len(self._sent_msgs) > 0

    def config(self, rxbuf: int = 526, timeout_ms: int = 300_000, rate: Optional[int] = None) -> None:
        self._rxbuf_size = rxbuf
        self._timeout_ms = timeout_ms
        self._config_call_count += 1
        self._rx_exc = False  # Allows recover to clear forced exception

    def get_peers(self) -> Tuple[Tuple]:
        if not self._peers:
            return None

        return ((peer, None) for peer in self._peers)

    def recv(self, timeout_ms: Optional[int] = None, **kwargs) -> Tuple:
        if self._rx_exc is True:
            raise OSError("Forced RX exception")

        if self._transport is not None:
            self._transport.receive(self._received_msgs, **kwargs)
            next_msg = self._received_msgs.pop(0)
        else:
            next_msg = self._sent_msgs.pop(0)

        return (self._mac, next_msg)

    def send(self, msg, **kwargs) -> bool:
        if self._transport is not None:
            return self._transport.send(msg, **kwargs)

        self._sent_msgs.append(msg)
        return True

    def set_rx_exc(self, force_exc: bool):
        self._rx_exc = force_exc

    @classmethod
    def clear_peers(cls):
        cls._peers = []
