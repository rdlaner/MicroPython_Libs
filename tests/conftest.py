# TODO: Need to mock RTC, which is a class defined in the machine module

# Standard imports
import pytest
import random
import sys
import time
import traceback
from unittest import mock

# Local imports
from tests.mocks.mock_machine import MockRtc, MockTimer
from tests.mocks.mock_micropython import mock_schedule


# Mocked modules
mock_machine = mock.MagicMock()
mock_micropython = mock.MagicMock()
mock_espnow = mock.MagicMock()
mock_network = mock.MagicMock()
mock_ntptime = mock.MagicMock()
mock_secrets = mock.MagicMock()
mock_config = mock.MagicMock()


# Add mocked modules to the global modules dict
sys.modules["machine"] = mock_machine  # type: ignore
sys.modules["micropython"] = mock_micropython  # type: ignore
sys.modules["espnow"] = mock_espnow
sys.modules["network"] = mock_network
sys.modules["ntptime"] = mock_ntptime
sys.modules["secrets"] = mock_secrets
sys.modules["config"] = mock_config


# Mocks
@pytest.fixture(autouse=True)
def mock_machine_unique_id(mocker):
    def mocked_unique_id() -> bytes:
        return bytes([random.randint(0, 255) for _ in range(10)])

    mocker.patch("machine.unique_id", side_effect=mocked_unique_id)


@pytest.fixture(autouse=True)
def mock_sys_print_exception(mocker):
    def mocked_impl(exc, file=None):
        if file is None:
            file = sys.stdout

        traceback.print_exception(type(exc), exc, exc.__traceback__, file=file)

    # Ensure sys.print_exception exists so that we can mock it
    if not hasattr(sys, "print_exception"):
        sys.print_exception = lambda exc, file=None: None  # Placeholder function

    mocker.patch("sys.print_exception", side_effect=mocked_impl)


@pytest.fixture(autouse=True)
def mock_time_ticks_ms(mocker):
    def mocked_impl():
        return time.monotonic_ns() // 1_000_000

    if not hasattr(time, "ticks_ms"):
        time.ticks_ms = lambda: None

    mocker.patch("time.ticks_ms", side_effect=mocked_impl)


@pytest.fixture(autouse=True)
def mock_time_ticks_diff(mocker):
    def mocked_impl(t1, t2) -> int:
        return abs(t2 - t1)

    if not hasattr(time, "ticks_diff"):
        time.ticks_diff = lambda: None

    mocker.patch("time.ticks_diff", side_effect=mocked_impl)


def mock_time_sleep_ms(time_msec: int) -> int:
    time.sleep(time_msec / 1_000)


# Apply any global mocks that operate outside of a fixture
mock_micropython.const.side_effect = lambda x: x
mock_micropython.schedule = mock_schedule
mock_espnow.MAX_DATA_LEN = 250
mock_machine.RTC = MockRtc
mock_machine.Timer = MockTimer
time.sleep_ms = mock_time_sleep_ms


# Default config
from mp_libs import logging
mock_config = {
    "logging_level": logging.INFO,
}
sys.modules["config"].config = mock_config
