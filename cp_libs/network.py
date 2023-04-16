"""Network Support Library"""
# pylint: disable=no-name-in-module, import-error, disable=no-member, c-extension-no-member
# Standard imports
import microcontroller
import rtc
import socketpool
import ssl
import traceback
import wifi
from micropython import const

# Third party imports
import adafruit_logging as logging
import adafruit_minimqtt.adafruit_minimqtt as MQTT
import adafruit_ntp
from cp_libs.protocols import InterfaceProtocol
from cp_libs.protocols.min_iot_protocol import MinIotProtocol
from cp_libs.protocols.serial_protocols import SerialProtocol
from cp_libs.protocols.wifi_protocols import EspnowProtocol, MqttProtocol, WifiProtocol

# Local imports
from config import config
from secrets import secrets

# Constants
DEFAULT_MTU_SIZE_BYTES = const(250)
TZ_OFFSET_PACIFIC = const(-8)

# Globals
logger = logging.getLogger("network")
logger.setLevel(config["logging_level"])


class Network(InterfaceProtocol):
    """Generic network class for utilizing any protocol that adheres to the InterfaceProtocol.

    Extends InterfaceProtocol with NTP support, if requested.
    Provides factory classmethods for creating utilizing common protocol combinations.
    """
    def __init__(self, transport: InterfaceProtocol, ntp: adafruit_ntp.NTP = None):
        self.transport = transport
        self.ntp = ntp

    def connect(self, **kwargs) -> bool:
        return self.transport.connect(**kwargs)

    def disconnect(self, **kwargs) -> bool:
        return self.transport.disconnect(**kwargs)

    def is_connected(self) -> bool:
        return self.transport.is_connected()

    def ntp_time_sync(self) -> bool:
        success = True
        if self.ntp:
            try:
                rtc.RTC().datetime = self.ntp.datetime
            except OSError as exc:
                logger.error("NTP time sync failed:")
                logger.error(f"{''.join(traceback.format_exception(exc, chain=True))}")
                success = False
        else:
            logger.warning("NTP not enabled for this network")

        return success

    def receive(self, rxed_data: list, **kwargs) -> bool:
        return self.transport.receive(rxed_data, **kwargs)

    def recover(self, **kwargs) -> bool:
        return self.transport.recover(**kwargs)

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
        client_id = id_prefix + str(int.from_bytes(microcontroller.cpu.uid, 'little') >> 29)
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
        client_id = id_prefix + str(int.from_bytes(microcontroller.cpu.uid, 'little') >> 29)
        espnow_protocol = EspnowProtocol(config["epn_peer_mac"], hostname=client_id, channel=config["epn_channel"])
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
        client_id = id_prefix + str(int.from_bytes(microcontroller.cpu.uid, 'little') >> 29)
        socket_pool = socketpool.SocketPool(wifi.radio)
        ntp = adafruit_ntp.NTP(socket_pool, tz_offset=TZ_OFFSET_PACIFIC)

        client = MQTT.MQTT(
            client_id=client_id,
            broker=secrets["mqtt_broker"],
            port=secrets["mqtt_port"],
            username=secrets["mqtt_username"],
            password=secrets["mqtt_password"],
            socket_pool=socket_pool,
            ssl_context=ssl.create_default_context(),
            keep_alive=keep_alive_sec if keep_alive_sec else config["keep_alive_sec"],
            connect_retries=config["connect_retries"],
            recv_timeout=config["recv_timeout_sec"],
        )
        client.on_connect = on_connect_cb
        client.on_disconnect = on_disconnect_cb
        client.on_publish = on_publish_cb
        client.on_subscribe = on_sub_cb
        client.on_unsubscribe = on_unsub_cb
        client.on_message = on_message_cb
        client.enable_logger(logging, log_level=config["logging_level"])

        wifi_protocol = WifiProtocol(secrets["ssid"], secrets["password"], client_id, config["wifi_channel"])
        mqtt_protocol = MqttProtocol(wifi_protocol, client)

        return cls(mqtt_protocol, ntp)
