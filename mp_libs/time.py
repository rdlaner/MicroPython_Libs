"""Time Support Library

TODO: Update to use datetime module
"""
# Standard imports
import time
from micropython import const

# Third party imports

# Local imports

# Constants
TIME_FMT_STR = "%d:%02d:%02d"
DATA_FMT_STR = "%d/%d/%d"
UTC_TO_PACIFIC = const(-8)


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

    pacific_hour = now[3] + UTC_TO_PACIFIC
    if pacific_hour <= 0:
        pacific_hour += 12

    return TIME_FMT_STR % (pacific_hour, now[4], now[5])


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

    months_ending_in_31 = [1, 3, 5, 7, 8, 10, 12]
    months_ending_in_30 = [4, 6, 9, 11]
    pacific_hour = now[3] + UTC_TO_PACIFIC
    pacific_day = now[2]
    pacific_month = now[1]
    pacific_year = now[0]

    # Handle hour rollback
    if pacific_hour <= 0:
        pacific_day -= 1
        pacific_hour += 12

    # Handle day rollback
    if pacific_day <= 0:
        pacific_month -= 1

        if now[1] in months_ending_in_31:
            pacific_day = 31
        elif now[1] in months_ending_in_30:
            pacific_day = 30
        else:
            pacific_day = 28

    # Handle month rollback
    if pacific_month <= 0:
        pacific_month = 12
        pacific_year -= 1

    return DATA_FMT_STR % (pacific_month, pacific_day, pacific_year)
