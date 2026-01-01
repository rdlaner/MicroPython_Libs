"""Mocks for the micropython's micropython module"""
# Standard imports

# Third party imports


def mock_schedule(callback, arg):
    """Mock implementation of micropython.schedule.

    In MicroPython, schedule() queues a callback to run at the next opportunity.
    For testing, we invoke it immediately to simulate the behavior.
    """
    if callback is not None:
        callback(arg)
