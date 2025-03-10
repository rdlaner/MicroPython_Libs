"""Network Support Library

# TODO: Don't rely on config/secrets module like this. Do something better.
"""
# pylint: disable=no-name-in-module, import-error, disable=no-member, c-extension-no-member
# pyright: reportGeneralTypeIssues=false
# Standard imports
import binascii
import machine
import ntptime
import socket
from micropython import const
try:
    from typing import Any, List
except ImportError:
    pass

# Third party imports
from mp_libs import logging
from mp_libs.adafruit_minimqtt import adafruit_minimqtt as MQTT
from mp_libs.protocols import InterfaceProtocol
from mp_libs.protocols.min_iot_protocol import MinIotProtocol
from mp_libs.protocols.serial_protocols import SerialProtocol
from mp_libs.protocols.espnow_protocol import EspnowProtocol
from mp_libs.protocols.wifi_protocols import MqttProtocol, WifiProtocol

# Local imports
try:
    from config import config
except ImportError:
    config = {"logging_level": logging.INFO}
from secrets import secrets

# Constants
DEFAULT_MTU_SIZE_BYTES = const(240)
TZ_OFFSET_PACIFIC = const(-8)

# Globals
logger = logging.getLogger("network")
logger.setLevel(config["logging_level"])


class Network(InterfaceProtocol):
    """Generic network class for utilizing any protocol that adheres to the InterfaceProtocol.

    Provides factory classmethods for creating utilizing common protocol combinations.
    """
    def __init__(self, transport: InterfaceProtocol):
        self.transport = transport
        self.rtc = machine.RTC()

    def connect(self, **kwargs) -> bool:
        return self.transport.connect(**kwargs)

    def disconnect(self, **kwargs) -> bool:
        return self.transport.disconnect(**kwargs)

    def is_connected(self) -> bool:
        return self.transport.is_connected()

    def ntp_time_sync(self) -> bool:
        """Performs time sync if the underlying transport has a wifi connection"""
        if isinstance(self.transport, (MqttProtocol, WifiProtocol)):
            try:
                ntptime.settime()
            except OSError as exc:
                logger.exception("Time sync failed", exc_info=exc)
                return False

        return True

    def receive(self, rxed_data: list, **kwargs) -> bool:
        return self.transport.receive(rxed_data, **kwargs)

    def recover(self, **kwargs) -> bool:
        return self.transport.recover(**kwargs)

    def scan(self, **kwargs) -> List[Any]:
        return self.transport.scan(**kwargs)

    def send(self, msg, **kwargs) -> bool:
        return self.transport.send(msg, **kwargs)

    def subscribe(self, topic, qos: int = 0) -> None:
        if getattr(self.transport, "subscribe", None):
            self.transport.subscribe(topic, qos)

    def unsubscribe(self, topic) -> None:
        if getattr(self.transport, "unsubscribe", None):
            self.transport.unsubscribe(topic)

    @classmethod
    def create_espnow(cls, id_prefix: str = "") -> "Network":
        """Creates and returns a Network instance configured to the ESPNow protocol.

        Utilizes the espnow protocol.

        Args:
            id_prefix (str, optional): Prefix string for client ID. Defaults to "".

        Returns:
            Network: Network instance.
        """
        client_id = id_prefix + binascii.hexlify(machine.unique_id()).decode("utf-8")
        espnow_protocol = EspnowProtocol(config["epn_peer_mac"], hostname=client_id, channel=config["epn_channel"])

        return cls(espnow_protocol)

    @classmethod
    def create_min_iot(cls, id_prefix: str = "") -> "Network":
        """Creates and returns a Network instance configured to the MinIoT protocol.

        Utilizes the espnow, serial, and MinIoT protocols.

        Args:
            id_prefix (str, optional): Prefix string for client ID. Defaults to "".

        Returns:
            Network: Network instance.
        """
        client_id = id_prefix + binascii.hexlify(machine.unique_id()).decode("utf-8")
        espnow_protocol = EspnowProtocol(config["epn_peer_mac"], hostname=client_id, channel=config["epn_channel"], timeout_ms=config["epn_timeout_ms"])
        serial_protocol = SerialProtocol(espnow_protocol, mtu_size_bytes=DEFAULT_MTU_SIZE_BYTES)
        min_iot_protocol = MinIotProtocol(serial_protocol)

        return cls(min_iot_protocol)

    @classmethod
    def create_mqtt(cls,
                    id_prefix: str = "",
                    keep_alive_sec: int = None,
                    on_connect_cb=None,
                    on_disconnect_cb=None,
                    on_publish_cb=None,
                    on_sub_cb=None,
                    on_unsub_cb=None,
                    on_message_cb=None) -> "Network":
        """Creates and returns a Network instance configured to the MQTT protocol.

        Utilizes the wifi and mqtt protocols.

        Args:
            id_prefix (str, optional): Prefix string for client ID. Defaults to "".
            keep_alive_sec (int, optional): Maximum period allowed for communication within single
                                            connection attempt, in seconds. Overrides config.
            on_connect_cb (calleable, optional): On connection callback. Defaults to None.
            on_disconnect_cb (calleable, optional): On disconnect callback. Defaults to None.
            on_publish_cb (calleable, optional): On msg publish callback. Defaults to None.
            on_sub_cb (calleable, optional): On topic subscribe callback. Defaults to None.
            on_unsub_cb (calleable, optional): On topic unsubscribe callback. Defaults to None.
            on_message_cb (calleable, optional): On msg received callback. Defaults to None.

        Returns:
            Network: Network instance.
        """
        client_id = id_prefix + binascii.hexlify(machine.unique_id()).decode("utf-8")

        client = MQTT.MQTT(
            client_id=client_id,
            broker=secrets["mqtt_broker"],
            port=secrets["mqtt_port"],
            username=secrets["mqtt_username"],
            password=secrets["mqtt_password"],
            socket_pool=socket,
            keep_alive=keep_alive_sec if keep_alive_sec else config["keep_alive_sec"],
            connect_retries=config["connect_retries"],
            recv_timeout=config["recv_timeout_sec"],
            socket_timeout=config["socket_timeout_sec"]
        )
        client.on_connect = on_connect_cb
        client.on_disconnect = on_disconnect_cb
        client.on_publish = on_publish_cb
        client.on_subscribe = on_sub_cb
        client.on_unsubscribe = on_unsub_cb
        client.on_message = on_message_cb
        client.enable_logger(logging, log_level=config["logging_level"], logger_name="mqtt")

        wifi_protocol = WifiProtocol(secrets["ssid"], secrets["password"], client_id)
        mqtt_protocol = MqttProtocol(wifi_protocol, client)

        return cls(mqtt_protocol)

    @classmethod
    def create_wifi(cls, id_prefix: str = "") -> "Network":
        """Creates and returns a Network instance configured to the Wifi protocol.

        Args:
            id_prefix (str, optional): Prefix string for hostname. Defaults to "".

        Returns:
            Network: Network instance.
        """
        client_id = id_prefix + binascii.hexlify(machine.unique_id()).decode("utf-8")

        return cls(WifiProtocol(secrets["ssid"], secrets["password"], client_id))
