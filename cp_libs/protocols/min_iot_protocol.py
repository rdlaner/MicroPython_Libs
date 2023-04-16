"""Minimal IoT Protocol Implementation"""
# TODO: Update miniot and serial protocol receive functions to return True even if only partial msg
#       has been received, require the user to check for None to know if a full msg is returned.
#       This will allow users to know when to poll repeatedly which is important for those that
#       call receive infrequently.

# Standard imports
import json
import time
from micropython import const

# Third party imports
import adafruit_logging as logging
from cp_libs.protocols import InterfaceProtocol

# Local imports
try:
    from config import config
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants

# Globals
logger = logging.getLogger("miniot")
logger.setLevel(config["logging_level"])


class MinIotMessage():
    """Minimal IoT Message definition for use with the MinIotProtocol"""
    def __init__(self, topic: str, msg: str) -> None:
        self.data = {
            "topic": topic,
            "msg": msg,
            "sent_ts": None,
            "received_ts": None,
        }

    def __repr__(self) -> str:
        return self.serialize().decode()

    @property
    def msg(self):
        """Get msg attribute"""
        return self.data["msg"]

    @property
    def received_ts(self):
        """Get received timestamp attribute"""
        return self.data["received_ts"]

    @property
    def sent_timestamp(self):
        """Get sent timestamp attribute"""
        return self.data["sent_ts"]

    @property
    def topic(self):
        """Get topic attribute"""
        return self.data["topic"]

    @classmethod
    def deserialize(cls, data: bytes) -> "MinIotMessage":
        """Deserialize a bytes object into a MinIoTMessage.

        Args:
            data (bytes): Bytes object produced by MinIotMessage.serialize().

        Returns:
            MinIotMessage: New instance of MinIoTMessage.
        """
        msg = cls(None, None)
        msg_data = json.loads(data)
        msg.data = msg_data

        return msg

    def serialize(self) -> bytes:
        """Serialize this message into a bytes object.

        Returns:
            bytes: Serialized bytes object representing this packet instance.
        """
        return json.dumps(self.data).encode("utf-8")


class MinIotProtocol(InterfaceProtocol):
    """InterfaceProtocol implementation for sending and receiving MinIotMessages

    This protocol will send and receive MinIotMessages via the provided transport protocol.
    Users should create an instance of this class for sending and receiving any messages via the
    Minimal IoT Protocol and should not use instances of the MinIotMessages class directly.
    The recommended transport protocol is SerialProtocol.
    """
    MAX_PACKET_SIZE_BYTES = const(200)

    def __init__(self, transport: InterfaceProtocol) -> None:
        self.transport = transport

    def connect(self, **kwargs) -> bool:
        """Connects transport.

        Returns:
            bool: True if connected, False if failed to connect.
        """
        logger.info("Connecting MinIoT...")
        return self.transport.connect(**kwargs)

    def disconnect(self, **kwargs) -> bool:
        """Disconnects transport.

        Returns:
            bool: True if connected, False if failed to connect.
        """
        logger.info("Disconnecting MinIoT")
        return self.transport.disconnect(**kwargs)

    def is_connected(self) -> bool:
        return self.transport.is_connected()

    def receive(self, rxed_data: list, **kwargs) -> bool:
        """Attempts to construct and return a MinIotMessage payload.

        This function should be called in a polling fashion as each call will read in a piece of
        a MinIotMessage. Once enough pieces have been received, one or more MinIotMessages will
        be constructed, their payloads extracted and returned.

        Args:
            rxed_data (list): List of received MinIotMessage payloads, if any.

        Returns:
            bool: True if data is ready and returned. False if no data available.
        """
        data_available = False
        rxed_msgs = []

        if self.transport.receive(rxed_msgs):
            data_available = True

            for msg in rxed_msgs:
                iot_msg = MinIotMessage.deserialize(msg)
                iot_msg.data["received_ts"] = time.time()
                rxed_data.append(iot_msg.data)

        return data_available

    def send(self, msg, **kwargs) -> bool:
        """Synchronously send raw data via MinIoT protocol.

        Constructs a MinIotMessage with the given msg object as the payload and then sends that
        message via the provided transport.

        Args:
            msg (any): Msg payload. If not str or MinIotMessage, will convert to str.
            topic (str): MinIotMessage topic.

        Returns:
            bool: True if successful, False if failed.
        """
        miniot_msg = None
        topic = kwargs.get("topic", None)

        if isinstance(msg, str):
            miniot_msg = MinIotMessage(topic, msg)
        elif isinstance(msg, MinIotMessage):
            miniot_msg = msg
        else:
            miniot_msg = MinIotMessage(topic, str(msg))

        return self.send_miniot_msg(miniot_msg)

    def send_miniot_msg(self, msg: MinIotMessage) -> bool:
        """Synchronously send a MinIoTMessage via MinIoT protocol.

        Args:
            msg (MinIotMessage): MinIoTMessage to send.

        Returns:
            bool: True if successful, False if failed.
        """
        msg.data["sent_ts"] = time.time()

        return self.transport.send(msg.serialize())
