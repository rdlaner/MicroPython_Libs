"""All InterfaceProtocol implementations for Wifi-capable hardware"""
# pylint: disable=c-extension-no-member, disable=no-member, logging-fstring-interpolation
# pyright: reportGeneralTypeIssues=false
# Standard imports
import binascii
import gc
import io
import machine
import network
import sys
import time
from micropython import const

# Third party imports
from mp_libs import logging
from mp_libs.protocols import InterfaceProtocol
from mp_libs.adafruit_minimqtt import adafruit_minimqtt as MQTT

# Local imports
try:
    from config import config
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants

# Globals
logger = logging.getLogger("wifi-protocols")
logger.setLevel(config["logging_level"])

# TODO: Wifi protocol only supports station, consider adding support for AP
# TODO: Add support for using a static IP address w/ wifi. This should help with connection times.


class WifiProtocol(InterfaceProtocol):
    """InterfaceProtocol implementation for sending and receiving data via wifi"""

    # Constants
    DEFAULT_CONNECTION_ATTEMPTS = const(3)

    def __init__(self, ssid: str, password: str, hostname: str = None, channel: int = 0) -> None:
        super().__init__()
        self._ssid = ssid
        self._password = password
        self._channel = channel
        self._sta = network.WLAN(network.STA_IF)

        if hostname:
            self._hostname = hostname
        else:
            self._hostname = binascii.hexlify(machine.unique_id()).decode("utf-8")

        self._network_enable()
        self._sta.config(channel=channel)
        network.hostname(hostname)  # Apparently _sta.config is deprecated...

    def __repr__(self) -> str:
        return "WIFI"

    def _connect_wifi(self, **kwargs) -> bool:
        max_connect_attempts = kwargs.get("connect_attempts", 3)
        success = True

        if not self._sta.isconnected():
            attempt = 1

            while not self._sta.isconnected():
                logger.debug(f"Connecting to AP: {self._ssid}")
                networks = self._sta.scan()

                # Each network is a tuple with the following data:
                # (ssid, bssid, channel, RSSI, security, hidden)
                networks = sorted(
                    networks, key=lambda net: net[3], reverse=True)

                for net in networks:
                    logger.debug(f"ssid: {net[0]}, rssi: {net[3]}")

                try:
                    self._sta.connect(self._ssid, self._password)
                except (RuntimeError, OSError) as exc:
                    logger.exception(f"Could not connect to wifi AP: {self._ssid}", exc_info=exc)

                try:
                    self._wait_for(self._sta.isconnected)
                except RuntimeError as exc:
                    logger.exception(f"Timed out connecting to wifi AP: {self._ssid}", exc_info=exc)

                if not self._sta.isconnected():
                    if attempt >= max_connect_attempts:
                        break
                    logger.warning("Retrying in 3 seconds...")
                    attempt += 1
                    time.sleep(3)

                gc.collect()

            if not self._sta.isconnected():
                logger.error(f"Failed to connect to Wifi after {max_connect_attempts} attempts!")
                success = False
            else:
                logger.info(f"Wifi is connected: {self._sta.ifconfig()}")
        else:
            logger.info("Wifi is already connected")

        return success

    def _network_enable(self):
        self._sta.active(True)

    def _network_disable(self):
        self._sta.active(False)

    def _wait_for(self, func, timeout_secs=20):
        timeout_time = time.time() + timeout_secs
        while not func():
            if time.time() >= timeout_time:
                raise RuntimeError("noop")
            time.sleep_ms(10)

    @property
    def hostname(self):
        """Get hostname for device's wifi interface"""
        return self._hostname

    def connect(self, **kwargs) -> bool:
        """Connect to given wifi ssid.

        Args:
            connect_attempts (dict, optional): Max number of connect attempts. Default is 3.

        Returns:
            bool: True if connected, False if failed to connect.
        """
        logger.info("Connecting wifi...")
        self._network_enable()
        connect_attempts = kwargs.get("connect_attempts", self.DEFAULT_CONNECTION_ATTEMPTS)
        return self._connect_wifi(connect_attempts=connect_attempts)

    def disconnect(self, **kwargs) -> bool:
        """Disconnect from given wifi ssid.

        Just powers off wifi radio and calls it good.

        Returns:
            bool: True if disconnected, False if failed to disconnect.
        """
        logger.info("Disconnecting wifi...")
        self._sta.disconnect()

        if kwargs.get("wait", True):
            try:
                self._wait_for(lambda: not self._sta.isconnected())
            except RuntimeError:
                logger.error("Timeout trying to disconnect Wifi")
                return False

        return True

    def is_connected(self) -> bool:
        return self._sta.isconnected()

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

        if force or not self._sta.isconnected():
            self._network_disable()
            time.sleep(1)
            self._network_enable()

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
        self._transport = transport
        self._mqtt_client = mqtt_client

        self._transport.disconnect(force=True)

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
        success = self._transport.connect()
        if not success:
            logger.error("Failed to connect MQTT: transport failed to connect")
            return success

        # Now connect MQTT
        logger.info("Connecting mqtt...")
        force = kwargs.get("force", False)

        if not self._mqtt_client.is_connected() or force is True:
            try:
                self._mqtt_client.connect()
            except (OSError, ValueError, RuntimeError, MQTT.MMQTTException) as exc:
                logger.exception("Failed to connect MQTT!", exc_info=exc)
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
        if self._mqtt_client.is_connected() or force is True:
            try:
                self._mqtt_client.disconnect()
            except (OSError, ValueError, RuntimeError, MQTT.MMQTTException) as exc:
                logger.exception("Failed to disconnect MQTT!", exc_info=exc)
                success = False
            else:
                logger.info("MQTT disconnected!")
        else:
            logger.info("MQTT is already disconnected")

        # Disconnect transport next
        if success:
            success = self._transport.disconnect()

        return success

    def is_connected(self) -> bool:
        return self._mqtt_client.is_connected()

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
            self._mqtt_client.loop()
        except (ValueError, RuntimeError, OSError, MQTT.MMQTTException) as exc:
            logger.exception("MQTT loop failure", exc_info=exc)
            data_available = False
            buf = io.StringIO()
            sys.print_exception(exc, buf)
            if recover:
                if not self.recover():
                    raise RuntimeError(f"Failed to recover after MQTT loop failure.\n{buf.getvalue()}")
            else:
                raise RuntimeError(f"Did not attempt recovery.\n{buf.getvalue()}")

        return data_available

    def recover(self, **kwargs) -> bool:
        """Attempts to recover the MQTT connection.

        Returns:
            bool: True if recovery succeeded, False if it failed.
        """
        logger.info("Attempting MQTT recovery...")

        # Attempt to recover MQTT first
        self.disconnect(force=True)
        success = self.connect(force=True)

        # If unable to recover MQTT, try to recover transport and then retrying MQTT
        if not success:
            success = self._transport.recover(force=True)

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
            self._mqtt_client.publish(topic, msg, retain=retain, qos=qos)
        except (ValueError, RuntimeError, OSError, MQTT.MMQTTException) as exc:
            logger.exception("MQTT send failed.", exc_info=exc)
            success = False
            buf = io.StringIO()
            sys.print_exception(exc, buf)
            if recover:
                if not self.recover():
                    raise RuntimeError(f"Failed to recover after MQTT send failure.\n{buf.getvalue()}")
            else:
                raise RuntimeError(f"Did not attempt recovery.\n{buf.getvalue()}")

        return success

    def subscribe(self, topic, qos: int = 0) -> None:
        self._mqtt_client.subscribe(topic, qos)

    def unsubscribe(self, topic) -> None:
        self._mqtt_client.unsubscribe(topic)
