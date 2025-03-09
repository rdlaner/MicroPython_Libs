"""Mocks for the micropython's machine module"""
# Standard imports
import time
from typing import Tuple

# Third party imports


class MockRtc():
    def __init__(self, rtc_id: int = 0, datetime: Tuple = ()):
        self._id = rtc_id
        self._datetime = datetime

    def datetime(self) -> Tuple:
        t = time.localtime()
        return t

    def now(self) -> int:
        return int(time.time() * 1_000_000)  # microseconds

    def offset(self, offset: bytes):
        ...
