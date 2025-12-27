"""Minimal IoT Protocol Implementation

TODO: Update miniot and serial protocol receive functions to return True even if only partial msg
      has been received, require the user to check for None to know if a full msg is returned.
      This will allow users to know when to poll repeatedly which is important for those that
      call receive infrequently.
TODO: Add support for users to specify their own serializer/deserializer to improve on json.
"""
# pyright: reportGeneralTypeIssues=false

# Standard imports
import json
import time
from micropython import const
try:
    from typing import Dict, List, Optional, Union
except ImportError:
    pass

# Third party imports
from mp_libs import base64
from mp_libs import logging
from mp_libs.protocols import InterfaceProtocol

# Local imports
try:
    from config import config
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants

# Globals
logger: logging.Logger = logging.getLogger("miniot")
logger.setLevel(config["logging_level"])


class MinIotMessage():
    """Minimal IoT Message definition for use with the MinIotProtocol"""
    def __init__(
        self,
        topic: str,
        msg: Union[str, bytes, bytearray],
        sent_ts: Optional[int] = None,
        received_ts: Optional[int] = None
    ) -> None:
        self.data = {
            "topic": topic,
            "msg": msg,
            "sent_ts": sent_ts,
            "received_ts": received_ts,
        }

    def __repr__(self) -> str:
        return f"topic: {self.topic}, msg: {self.msg}, sent_ts: {self.sent_ts}, received_ts: {self.received_ts}"

    @property
    def msg(self) -> Union[str, bytes, bytearray]:
        """Get msg attribute"""
        return self.data["msg"]

    @msg.setter
    def msg(self, data: str) -> None:
        """Set msg attribute"""
        self.data["msg"] = data

    @property
    def received_ts(self) -> int:
        """Get received timestamp attribute"""
        return self.data["received_ts"]

    @received_ts.setter
    def received_ts(self, ts: int) -> None:
        """Set received timestamp value"""
        self.data["received_ts"] = ts

    @property
    def sent_ts(self):
        """Get sent timestamp attribute"""
        return self.data["sent_ts"]

    @sent_ts.setter
    def sent_ts(self, ts: int) -> None:
        """Set sent timestamp value."""
        self.data["sent_ts"] = ts

    @property
    def topic(self):
        """Get topic attribute"""
        return self.data["topic"]

    @classmethod
    def create_from_dict(cls, data: Dict) -> "MinIotMessage":
        return cls(
            topic=data["topic"],
            msg=data["msg"],
            sent_ts=data["sent_ts"],
            received_ts=data["received_ts"]
        )

    @classmethod
    def deserialize(cls, data: bytes) -> "MinIotMessage":
        """Deserialize a bytes object into a MinIoTMessage.

        Args:
            data (bytes): Bytes object produced by MinIotMessage.serialize().

        Returns:
            MinIotMessage: New instance of MinIoTMessage.
        """
        msg_data = json.loads(data)
        msg = MinIotMessage.create_from_dict(msg_data)

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

    def receive(self, rxed_data: List[MinIotMessage], **kwargs) -> bool:
        """Attempts to construct and return a MinIotMessage payload.

        This function should be called in a polling fashion as each call will read in a piece of
        a MinIotMessage. Once enough pieces have been received, one or more MinIotMessages will
        be constructed and returned.

        Args:
            rxed_data (list): List of received MinIotMessages, if any.

        Returns:
            bool: True if data is ready and returned. False if no data available.
        """
        data_available = False
        rxed_msgs = []

        if self.transport.receive(rxed_msgs):
            # If the received msg is a miniot msg, deserialize.
            # If it isn't, just pass it on up, let the upper layers handle it.
            data_available = True
            for msg in rxed_msgs:
                try:
                    iot_msg = MinIotMessage.deserialize(msg)
                except (ValueError, KeyError):
                    rxed_data.append(msg)
                    continue

                # Attempt to base64 decode the msg payload in case it is a bytes/bytearray payload
                try:
                    iot_msg.msg = base64.b64decode(iot_msg.msg, validate=True)
                except (base64.BinasciiError, TypeError, ValueError):
                    pass

                iot_msg.received_ts = time.time()
                logger.debug(f"rx'ed msg: {iot_msg}")
                rxed_data.append(iot_msg)

        return data_available

    def scan(self, **kwargs) -> List:
        """Performs scan operation.

        MinIotProtocol does not have an explicit scan operation, passes this req on to the transport instead.

        Returns:
            List: Result of scan operation.
        """
        return self.transport.scan(**kwargs)

    def send(self, msg, **kwargs) -> bool:
        """Synchronously send raw data via MinIoT protocol.

        Constructs a MinIotMessage with the given msg object as the payload and then sends that
        message via the provided transport.

        Args:
            msg (any): Msg payload.
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
        elif isinstance(msg, (bytes, bytearray)):
            miniot_msg = MinIotMessage(topic, base64.b64encode(msg).decode("utf-8"))
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
        msg.sent_ts = time.time()

        return self.transport.send(msg.serialize())
