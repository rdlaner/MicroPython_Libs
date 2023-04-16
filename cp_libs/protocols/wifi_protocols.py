"""All InterfaceProtocol implementations for Wifi-capable hardware"""
# pylint: disable=c-extension-no-member, disable=no-member
# Standard imports
import espnow
import gc
import ipaddress
import microcontroller
import time
import traceback
import wifi
from espidf import IDFError
from micropython import const

# Third party imports
import adafruit_logging as logging
import adafruit_minimqtt.adafruit_minimqtt as MQTT
from cp_libs.protocols import InterfaceProtocol

# Local imports
try:
    from config import config
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants

# Globals
logger = logging.getLogger("wifi-protocols")
logger.setLevel(config["logging_level"])

# TODO: Metrics don't persist for espnow when using deep sleep mode...
# TODO: Add support for using a static IP address w/ wifi. This should help with connection times.
# TODO: Add retry attempts to espnow send?


class EspnowProtocol(InterfaceProtocol):
    """InterfaceProtocol implementation for sending and receiving espnow packets."""

    # Constants
    ESPNOW_BUFFER_SIZE_BYTES = const(8192)

    def __init__(self, peer_macs, hostname: str = None, channel: int = 0) -> None:
        super().__init__()
        self.epn = espnow.ESPNow(buffer_size=self.ESPNOW_BUFFER_SIZE_BYTES)
        self.hostname = hostname

        if isinstance(peer_macs, list):
            for mac in peer_macs:
                peer = espnow.Peer(mac=mac, channel=channel)
                self.epn.peers.append(peer)
        else:
            peer = espnow.Peer(mac=peer_macs, channel=channel)
            self.epn.peers.append(peer)

        self._network_disable()

    def __repr__(self) -> str:
        return "ESPNOW"

    def _network_enable(self):
        wifi.radio.enabled = True

    def _network_disable(self):
        wifi.radio.enabled = False
        self._network_connected = False

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
        return wifi.radio.enabled

    def receive(self, rxed_data: list, **kwargs) -> bool:
        """Receives all available espnow packets and appends them to the `rxed_data` list.

        Args:
            rxed_data (list): Received espnow packets, if any.
            recover (bool, optional): Attempt recovery if loop function fails.

        Returns:
            bool: True if data was received, False if no data available.
        """
        data_available = False
        rxed_espnow_packets = []
        recover = kwargs.get("recover", False)

        # Read as many espnow packets as are available
        while True:
            if self.epn:
                data_available = True
                try:
                    rxed_espnow_packets.append(self.epn.read())
                except ValueError as exc:
                    logger.error("Failed receiving espnow packet")
                    logger.error(f"{''.join(traceback.format_exception(exc, chain=True))}")
                    data_available = False
                    if recover:
                        if not self.recover():
                            raise RuntimeError("Failed to recover after espnow receive failure.") from exc
                    else:
                        raise RuntimeError("Did not attempt recovery.") from exc
            else:
                break

        # Extract payload from all read espnow packets
        for packet in rxed_espnow_packets:
            rxed_data.append(packet.msg)
            logger.debug(f"espnow mac: {packet.mac}, time: {packet.time}, rssi: {packet.rssi}")

        return data_available

    def recover(self, **kwargs) -> bool:
        """Attempt to recover espnow protocol.

        Returns:
            bool: True if recovery succeeded, False if it failed.
        """
        logger.info("Attempting espnow recovery... ")
        peers = self.epn.peers
        self.epn.deinit()
        del self.epn
        self.epn = espnow.ESPNow(buffer_size=self.ESPNOW_BUFFER_SIZE_BYTES)
        self.epn.peers.append(peers)

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

        try:
            self.epn.send(msg)
        except (ValueError, RuntimeError, IDFError) as exc:
            logger.error("ESPNOW failed sending packet")
            logger.error(f"{''.join(traceback.format_exception(exc, chain=True))}")
            success = False

        return success

    def send_metrics(self, **kwargs) -> bool:
        # TODO: redo this fxn
        metrics = {}
        metrics["Header"] = "metrics"
        metrics["send_success"] = self.epn.send_success
        metrics["send_failure"] = self.epn.send_failure

        logger.info(f"EPN SEND SUCCESS: {self.epn.send_success}")
        logger.info(f"EPN SEND FAILURE: {self.epn.send_failure}")

        # try:
        #     self.epn.send(json.dumps(metrics))  # pylint: disable=too-many-function-args
        # except (ValueError, RuntimeError, IDFError) as exc:
        #     print(f"ESPNOW failed sending metrics\n{exc}")


class WifiProtocol(InterfaceProtocol):
    """InterfaceProtocol implementation for sending and receiving data via wifi"""

    # Constants
    GOOGLE_IP_ADDRESS = ipaddress.ip_address("8.8.4.4")
    DEFAULT_CONNECTION_ATTEMPTS = const(3)

    def __init__(self, ssid: str, password: str, hostname: str = None, channel: int = 0) -> None:
        super().__init__()
        self._ssid = ssid
        self._password = password
        self._channel = channel
        self._network_connected = False

        if hostname:
            self._hostname = hostname
        else:
            self._hostname = str(int.from_bytes(microcontroller.cpu.uid, 'little') >> 29)

        wifi.radio.hostname = self._hostname
        self._network_disable()

    def __repr__(self) -> str:
        return "WIFI"

    def _connect_wifi(self, **kwargs) -> bool:
        max_connect_attempts = kwargs.get("connect_attempts", 3)
        success = True

        if not self._network_connected:
            self._network_enable()
            attempt = 1

            while not self._network_connected:
                logger.debug(f"Connecting to AP: {self._ssid}")
                networks = []
                for network in wifi.radio.start_scanning_networks():
                    networks.append(network)

                wifi.radio.stop_scanning_networks()
                networks = sorted(
                    networks, key=lambda net: net.rssi, reverse=True)

                for network in networks:
                    logger.debug(f"ssid: {network.ssid}, rssi: {network.rssi}")

                try:
                    wifi.radio.connect(self._ssid, self._password, channel=self._channel)
                except (RuntimeError, ConnectionError) as exc:
                    logger.error(f"Could not connect to wifi AP: {self._ssid}")
                    logger.error(f"{''.join(traceback.format_exception(exc, chain=True))}")

                if not wifi.radio.ipv4_address:
                    self._network_connected = False
                    if attempt >= max_connect_attempts:
                        break
                    logger.warning("Retrying in 3 seconds...")
                    attempt += 1
                    time.sleep(3)
                else:
                    self._network_connected = True

                gc.collect()

            if not self._network_connected:
                logger.error(f"Failed to connect to Wifi after {max_connect_attempts} attempts!")
                success = False
            else:
                logger.info(f"Wifi is connected: {wifi.radio.ipv4_address}")
        else:
            logger.info("Wifi is already connected")

        return success

    def _network_enable(self):
        wifi.radio.enabled = True

    def _network_disable(self):
        wifi.radio.enabled = False
        self._network_connected = False

    @property
    def hostname(self):
        """Get hostname for device's wifi interface"""
        return self._hostname

    @hostname.setter
    def hostname(self, value):
        """Set device's wifi interface hostname"""
        self._hostname = value
        wifi.radio.hostname = value

    def connect(self, **kwargs) -> bool:
        """Connect to given wifi ssid.

        Args:
            connect_attempts (dict, optional): Max number of connect attempts. Default is 3.

        Returns:
            bool: True if connected, False if failed to connect.
        """
        logger.info("Connecting wifi...")
        connect_attempts = kwargs.get("connect_attempts", self.DEFAULT_CONNECTION_ATTEMPTS)
        return self._connect_wifi(connect_attempts=connect_attempts)

    def disconnect(self, **kwargs) -> bool:
        """Disconnect from given wifi ssid.

        Just powers off wifi radio and calls it good.

        Returns:
            bool: True if disconnected, False if failed to disconnect.
        """
        logger.info("Disconnecting wifi...")
        self._network_disable()

        return True

    def is_connected(self) -> bool:
        return self._network_connected

    def receive(self, rxed_data: list, **kwargs) -> bool:
        # TBD
        pass

    def recover(self, **kwargs) -> bool:
        """Attempts to recover the wifi connection.

        Args:
            force (bool, optional): Force recovery even if wifi is already connected.

        Returns:
            bool: True if recovery succeeded, False if it failed.
        """
        logger.info("Attempting wifi recovery...")
        success = True
        force = kwargs.get("force", False)

        if force or (self._network_connected and not wifi.radio.ping(self.GOOGLE_IP_ADDRESS)):
            # Reset wifi connection if ping is NOT successful or force is True
            self._network_disable()
            time.sleep(1)
            self._network_enable()

            success = self._connect_wifi()
        elif not self._network_connected:
            # Reconnect wifi
            success = self._connect_wifi()

        return success

    def send(self, msg: str, **kwargs) -> bool:
        # TBD
        pass


class MqttProtocol(InterfaceProtocol):
    """InterfaceProtocol implementation for sending and receiving MQTT messages

    This protocol will send and receive MQTT via the provided transport protocol. In this case,
    the transport must be a WifiProtocol instance.
    """
    def __init__(self, transport: WifiProtocol, mqtt_client: MQTT) -> None:
        super().__init__()
        self.transport = transport
        self.mqtt_client = mqtt_client

        self.transport.disconnect()

    def __repr__(self) -> str:
        return "MQTT"

    def connect(self, **kwargs) -> bool:
        """Connects mqtt client (device) to mqtt broker.

        Args:
            force (bool, optional): Force connection attempt even if already connected.

        Returns:
            bool: True if connected, False if failed to connect.
        """
        # Connect transport first
        success = self.transport.connect()
        if not success:
            logger.error("Failed to connect MQTT: transport failed to connect")
            return success

        # Now connect MQTT
        logger.info("Connecting mqtt...")
        force = kwargs.get("force", False)

        if not self.mqtt_client.is_connected() or force is True:
            try:
                self.mqtt_client.connect()
            except (OSError, ValueError, RuntimeError, MQTT.MMQTTException) as exc:
                logger.error("Failed to connect MQTT!")
                logger.error(f"{''.join(traceback.format_exception(exc, chain=True))}")
                success = False
            else:
                logger.info("MQTT is connected!")
        else:
            logger.info("MQTT is already connected")

        return success

    def disconnect(self, **kwargs) -> bool:
        """Disconnects mqtt client (device) from mqtt broker.

        Args:
            force (bool, optional): Force disconnect attempt even if already disconnected.

        Returns:
            bool: True if disconnected, False if failed to disconnect.
        """
        logger.info("Disconnecting mqtt...")
        success = True
        force = kwargs.get("force", False)

        # Disconnect MQTT first
        if self.mqtt_client.is_connected() or force is True:
            try:
                self.mqtt_client.disconnect()
            except (OSError, RuntimeError, MQTT.MMQTTException) as exc:
                logger.error("Failed to disconnect MQTT!")
                logger.error(f"{''.join(traceback.format_exception(exc, chain=True))}")
                success = False
            else:
                logger.info("MQTT disconnected!")
        else:
            logger.info("MQTT is already disconnected")

        # Disconnect transport next
        if success:
            success = self.transport.disconnect()

        return success

    def is_connected(self) -> bool:
        return self.mqtt_client.is_connected()

    def receive(self, rxed_data: list, **kwargs) -> bool:
        """Exercises the MQTT loop function.

        Any received messages during the loop function will be forwarded to the user via MQTT
        callbacks. This function should be called to exercise the loop regardless of whether
        data is expected to be received or not.

        Args:
            rxed_data (list): Not used.
            recover (bool, optional): Attempt recovery if loop function fails.

        Raises:
            RuntimeError: Failed running loop function and failed to recover connection.
            RuntimeError: Failed running loop function, but did not attempt recovery.

        Returns:
            bool: Not used. Rely on MQTT callbacks.
        """
        data_available = True
        recover = kwargs.get("recover", False)

        try:
            self.mqtt_client.loop()
        except (BrokenPipeError, ValueError, RuntimeError, OSError, MQTT.MMQTTException) as exc:
            logger.error("MQTT loop failure")
            logger.error(f"{''.join(traceback.format_exception(exc, chain=True))}")
            data_available = False
            if recover:
                if not self.recover():
                    raise RuntimeError("Failed to recover after MQTT loop failure.") from exc
            else:
                raise RuntimeError("Did not attempt recovery.") from exc

        return data_available

    def recover(self, **kwargs) -> bool:
        """Attempts to recover the MQTT connection.

        Returns:
            bool: True if recovery succeeded, False if it failed.
        """
        logger.info("Attempting MQTT recovery...")

        # Attempt to recover MQTT first
        success = self.disconnect(force=True)
        if success:
            success = self.connect(force=True)

        # If unable to recover MQTT, try to recover transport and then retrying MQTT
        if not success:
            success = self.transport.recover(force=True)

            if success:
                success = self.connect(force=True)

        return success

    def send(self, msg: str, **kwargs) -> bool:
        """Synchronously sends msg and topic to MQTT broker.

        Args:
            msg (str): MQTT message
            topic (str): MQTT topic
            retain (bool, optional): Set retain flag or not. Default is False.
            qos (int, optional): Set qos level. Default is 0.
            recover (bool, optional): Attempt recovery if send fails.

        Raises:
            RuntimeError: Failed to send message and failed to recover MQTT connection.
            RuntimeError: Failed to send message, but did not attempt recovery.

        Returns:
            bool: True if successful, False if failed.
        """
        success = True
        topic = kwargs["topic"]
        retain = kwargs.get("retain", False)
        qos = kwargs.get("qos", 0)
        recover = kwargs.get("recover", False)

        try:
            self.mqtt_client.publish(topic, msg, retain=retain, qos=qos)
        except (BrokenPipeError, ValueError, RuntimeError, MQTT.MMQTTException) as exc:
            logger.error("MQTT send failed.")
            logger.error(f"{''.join(traceback.format_exception(exc, chain=True))}")
            success = False
            if recover:
                if not self.recover():
                    raise RuntimeError("Failed to recover after MQTT send failure.") from exc
            else:
                raise RuntimeError("Did not attempt recovery.") from exc

        return success

    def subscribe(self, topic, qos: int = 0) -> None:
        self.mqtt_client.subscribe(topic, qos)

    def unsubscribe(self, topic) -> None:
        self.mqtt_client.unsubscribe(topic)
