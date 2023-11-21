"""Time Support Library"""
# Standard imports
import time

# Third party imports

# Local imports

# Constants
TIME_FMT_STR = "%d:%02d:%02d"
DATA_FMT_STR = "%d/%d/%d"


def get_fmt_time(epoch_time: int = None) -> str:
    """Get formatted time string

    Args:
        epoch_time (int, optional): Create format str from this epoch timestamp.
                                    If None, will use current time.
    Returns:
        str: Formatted time string
    """
    if epoch_time:
        now = time.localtime(epoch_time)
    else:
        now = time.localtime()
    return TIME_FMT_STR % (now[3], now[4], now[5])


def get_fmt_date(epoch_time: int = None) -> str:
    """Get formatted date string

    Args:
        epoch_time (int, optional): Create format str from this epoch timestamp.
                                    If None, will use current date.
    Returns:
        str: Formatted date string
    """
    if epoch_time:
        now = time.localtime(epoch_time)
    else:
        now = time.localtime()
    return DATA_FMT_STR % (now[1], now[2], now[0])
