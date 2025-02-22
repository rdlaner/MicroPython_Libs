# Standard imports
import pytest
import sys
import time
import traceback
from unittest import mock

# Mock machine module
mock_machine = mock.MagicMock()

# Mock micropython module
mock_micropython = mock.MagicMock()
mock_micropython.const.side_effect = lambda x: x

# Add mocked modules to the global modules dict
sys.modules["machine"] = mock_machine  # type: ignore
sys.modules["micropython"] = mock_micropython  # type: ignore

# Mocks
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
