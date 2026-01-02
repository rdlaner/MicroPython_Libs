# %%micropython

"""MinIoT <-> MQTT Gateway

Any supported transport/protocol from mp_libs.protocols technically can be used to connect to the MQTT
gateway. However, MinIoT is used explicitly here due to its topic/msg format and low overhead.

For now all transport API is synchronous. However, async support can/should be added to InterfaceProtocol
as micropython supports an async espnow and we can likely create a async mqtt API.

ESPNow and Wifi:
It turns out you can receive ESPNow messages while actively connected to a wifi AP, but it has some
caveats. First attempts at testing showed that I can do both protocols simultaneously if both
devices use the same wifi channel AND the device connected to an AP also has AP mode turned on in
order to disable power savings mode.
https://docs.micropython.org/en/latest/library/espnow.html#espnow-and-wifi-operation
"""
# pylint: disable=no-name-in-module, wrong-import-order

# Standard imports
import asyncio
import json
import io
import sys

# Third party imports
from mp_libs import logging
from mp_libs.adafruit_minimqtt import adafruit_minimqtt as MQTT
from mp_libs.async_primitives.queue import AsyncQueue
from mp_libs.network import Network
from mp_libs.protocols.espnow_protocol import EspnowError
from mp_libs.protocols.min_iot_protocol import MinIotMessage
from mp_libs.time import time

# Local imports
from config import config  # pylint: disable=import-error

# Constants
TIMEOUT_MSEC = const(5000)

# Globals
logger = logging.getLogger("Gateway")
logger.setLevel(config["logging_level"])
downlink_queue = AsyncQueue()
uplink_queue = AsyncQueue()
miniot_send_event = asyncio.Event()


# MQTT Callbacks
# pylint: disable=unused-argument
def mqtt_connected(client: MQTT.MQTT, user_data, flags: int, return_code: int) -> None:
    """Callback for when when MQTT client is connected to the broker"""
    logger.debug("MQTT connected callback")


def mqtt_disconnected(client: MQTT.MQTT, user_data, return_code: int) -> None:
    """Callback for when MQTT client is disconnected from the broker"""
    logger.debug("MQTT disconnected callback")


def mqtt_message(client: MQTT.MQTT, topic: str, message: str) -> None:
    """Callback for when MQTT client's subscribed topic receives new data"""
    logger.info(f"New message on topic {topic}: {message}")
    downlink_queue.put_nowait(MinIotMessage(topic, message))


def reset(msg: str = "", exc_info=None) -> None:
    """Reset device.

    Should be used for attempting to recover a device due to unrecoverable failures.

    Instead of resetting directly here, we will throw an exception that will get caught by main.py.
    main.py will write the optional message to the file system and then clean up before rebooting.

    Args:
        msg (str, optional): Optional reboot message.
        exc_info (Exception, optional): Optional exception instance.
    """
    logger.warning("Rebooting...")

    if exc_info:
        buf = io.StringIO()
        sys.print_exception(exc_info, buf)
        msg = f"{msg}\n{buf.getvalue()}"

    raise RuntimeError(msg)


# Async tasks
async def miniot_receive(net: Network) -> None:
    """Async task to read incoming MinIoT messages.

    All received messages are loaded into the async event queue.
    Also sets miniot_send_event so that the miniot_send function can send any data it may have in
    the downlink queue while the device is (hopefully) awake and listening.

    Args:
        net (Network): Network interface protocol implementing MinIotProtocol
    """
    while True:
        msgs = []
        try:
            data_rxed = net.receive(msgs)
        except (EspnowError) as exc:
            logger.exception("Handled exception in receiving min iot msg", exc_info=exc)
            data_rxed = False

        # Parse rx'ed packets
        for packet in msgs:
            logger.info(f"Miniot received {packet}")
            miniot_send_event.set()  # Set event first so miniot_send runs before mqtt_send
            miniot_send_event.clear()
            uplink_queue.put_nowait(packet)

        await asyncio.sleep_ms(0)


async def miniot_send(net: Network) -> None:
    """Async task to send MinIoT messages from broker to device.

    Receives all messages to send from downlink_queue.
    Blocks on miniot_send_event and not downlink_queue because the receiving device is only
    available to receive data infrequently and the only way we know it is available is if we just
    received data from it. So the miniot_receive task will set this send event unblocking this
    task to send all data collected in the downlink queue.

    Args:
        net (Network): Network interface protocol implementing MinIotProtocol.
    """
    while True:
        await miniot_send_event.wait()

        logger.info("Got event...")
        while miniot_msg := downlink_queue.get_nowait():
            try:
                logger.info("Miniot sending data...")
                success = net.send(miniot_msg)
            except Exception as exc:
                logger.exception("MinIoT send failed", exc_info=exc)
                success = False

            if not success:
                logger.error("MinIoT send failed")


async def mqtt_receive(net: Network) -> None:
    """Async task to run the MQTT loop.

    Will attempt to recover MQTT if loop failure occurs. However, if recovery fails,
    this function will reboot the device as a last effort to recover.

    Args:
        net (Network): Network interface protocol implementing MqttProtocol
    """
    while True:
        await asyncio.sleep(1)

        try:
            logger.info("MQTT loop...")
            net.receive(rxed_data=None, recover=True)
        except Exception as exc:
            reset("MQTT Loop failed. Rebooting.", exc_info=exc)


async def mqtt_send(net: Network) -> None:
    """Async task to send received MinIoT messages to MQTT broker.

    Blocks on uplink event queue to receive messages to send.
    Will attempt to recover MQTT if an error occurs on send. However, if recovery fails,
    this function will reboot the device as a last effort to recover.

    Also looks for cmd topics defined by device so that we can subscribe to them in order to
    forward messages from the broker to the device.

    Args:
        net (Network): Network interface protocol implementing MqttProtocol
    """
    while True:
        msg = await uplink_queue.get()

        try:
            logger.info("MQTT sending data...")
            success = net.send(msg=msg.msg, topic=msg.topic, retain=True, qos=1, recover=True)
        except Exception as exc:
            reset("MQTT send failed. Rebooting.", exc_info=exc)

        if not success:
            logger.error("MQTT send failed")

        # Check for topics to subscribe to. Our device will be telling Home Assistant which
        # topics it will be listening on for HA -> device communication. These are typically
        # cmd topics. So look for those when the device is sending HA discovery info.
        if success:
            # Only check config topics
            if not msg.topic.endswith("config"):
                continue

            # A subscribable topic will be defined as a cmd topic, so only look for those
            msg_dict = json.loads(msg.msg)
            if ("~" not in msg_dict) or ("cmd_t" not in msg_dict):
                continue

            # Check if already subscribed to this topic
            cmd_topic = msg_dict["~"] + msg_dict["cmd_t"].split("~")[1]
            if cmd_topic in net.transport._mqtt_client._subscribed_topics:
                continue

            # If we made it this far, then subscribe to topic
            net.subscribe(cmd_topic)


async def time_sync(net: Network, sync_interval_secs: float) -> None:
    """Async time synchronization task. Periodically runs ntp time sync.

    Args:
        net (Network): Network interface protocol with ntp implementation.
        sync_interval_secs (float): Time sync interval in seconds.
    """
    while True:
        net.ntp_time_sync()
        logger.info(f"Time: {time.get_fmt_time()}")
        logger.info(f"Date: {time.get_fmt_date()}")

        await asyncio.sleep(sync_interval_secs)


async def main_loop() -> None:
    """Main Loop - Runs all async tasks."""
    logger.debug("Staring main")

    mqtt_network = Network.create_mqtt("GTY",
                                       on_connect_cb=mqtt_connected,
                                       on_disconnect_cb=mqtt_disconnected,
                                       on_message_cb=mqtt_message)
    miniot_network = Network.create_min_iot("GTY")

    # Work-around: disabling the power-saving mode on the STA_IF interface
    epn = miniot_network.transport.transport._transport
    epn.wifi._sta.config(pm=epn.wifi._sta.PM_NONE)
    # mqtt_network.transport._transport._sta.config(pm=mqtt_network.transport._transport._sta.PM_NONE)

    if not mqtt_network.connect():
        reset("Failed to connect to MQTT network. Rebooting...")

    if not miniot_network.connect():
        reset("Failed to connect to MinIOT network. Rebooting...")

    try:
        miniot_receive_task = asyncio.create_task(miniot_receive(miniot_network))
        miniot_send_task = asyncio.create_task(miniot_send(miniot_network))
        mqtt_receive_task = asyncio.create_task(mqtt_receive(mqtt_network))
        mqtt_send_task = asyncio.create_task(mqtt_send(mqtt_network))
        time_sync_task = asyncio.create_task(time_sync(mqtt_network, config["time_sync_rate_sec"]))

        await asyncio.gather(miniot_receive_task,
                             miniot_send_task,
                             mqtt_receive_task,
                             mqtt_send_task,
                             time_sync_task,
                             )
    except Exception as exc:
        reset("Caught unexpected exception. Rebooting.", exc_info=exc)


def main():
    """Run async main loop"""
    asyncio.run(main_loop())
