"""Statistics functions optimized for micropython"""

# Standard imports
import math
from micropython import const  # pylint: disable=import-error, wrong-import-order
try:
    from typing import List, Union
except ImportError:
    pass

# Third party imports
from mp_libs import logging
from mp_libs.mpy_decimal import DecimalNumber

# Local imports
try:
    from config import config  # type: ignore
except ImportError:
    config = {"logging_level": logging.INFO}

# Globals
logger: logging.Logger = logging.getLogger("PTP")
logger.setLevel(config["logging_level"])


def percentile(data: List[Union[DecimalNumber, int, float]], percent: int) -> Union[DecimalNumber, int, float]:
    """Calculate the value at the specified percentile.

    Args:
        data (List[Union[DecimalNumber, int, float]]): Data to analyze.
        percent (int): Percentile.

    Returns:
        DecimalNumber: Value at the specified percentile.
    """
    k = (len(data) - 1) * percent / 100
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return data[int(k)]

    if isinstance(data[0], DecimalNumber):
        d0 = data[f] * DecimalNumber(str(c - k))  # type: ignore
        d1 = data[c] * DecimalNumber(str(k - f))  # type: ignore
    else:
        d0 = data[f] * (c - k)  # type: ignore
        d1 = data[c] * (k - f)  # type: ignore

    return d0 + d1  # type: ignore


def remove_outliers_iqr(data: List, lower_percentile: int, upper_percentile: int) -> List:
    """Returns a copy of the given data with outliers removed via an interquartile range analysis.

    Args:
        data (List): Data to be analyzed.
        lower_percentile (int): Q1 percentile.
        upper_percentile (int): Q3 percentile.

    Returns:
        List: Data with outliers removed.
    """
    sorted_data = sorted(data)
    q1 = percentile(sorted_data, lower_percentile)
    q3 = percentile(sorted_data, upper_percentile)
    iqr = q3 - q1                                        # type: ignore

    if isinstance(sorted_data[0], DecimalNumber):
        lower_bound = q1 - (DecimalNumber("1.5") * iqr)  # type: ignore
        upper_bound = q3 + (DecimalNumber("1.5") * iqr)  # type: ignore
    else:
        lower_bound = q1 - (1.5 * iqr)                   # type: ignore
        upper_bound = q3 + (1.5 * iqr)                   # type: ignore

    return [x for x in sorted_data if lower_bound <= x <= upper_bound]
