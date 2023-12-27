"""Time Support Library"""
# Standard imports
from datetime import datetime, timedelta, tzinfo


class USTimeZone(tzinfo):
    DSTSTART = datetime(1, 3, 8, 2)
    DSTEND = datetime(1, 11, 1, 2)
    ZERO = timedelta(0)
    HOUR = timedelta(hours=1)
    SECOND = timedelta(seconds=1)

    def __init__(self, hours, reprname, stdname, dstname):
        self.stdoffset = timedelta(hours=hours)
        self.reprname = reprname
        self.stdname = stdname
        self.dstname = dstname

    def __repr__(self):
        return self.reprname

    @staticmethod
    def first_sunday_on_or_after(dt):
        days_to_go = 6 - dt.weekday()
        if days_to_go:
            dt += timedelta(days_to_go)
        return dt

    @staticmethod
    def us_dst_range(year):
        start = USTimeZone.first_sunday_on_or_after(USTimeZone.DSTSTART.replace(year=year))
        end = USTimeZone.first_sunday_on_or_after(USTimeZone.DSTEND.replace(year=year))
        return start, end

    def tzname(self, dt):
        if self.dst(dt):
            return self.dstname
        return self.stdname

    def utcoffset(self, dt):
        return self.stdoffset + self.dst(dt)

    def dst(self, dt):
        if dt is None or dt.tzinfo is None:
            return self.ZERO
        assert dt.tzinfo is self
        start, end = USTimeZone.us_dst_range(dt.year)
        # Can't compare naive to aware objects, so strip the timezone from
        # dt first.
        dt = dt.replace(tzinfo=None)
        if start + self.HOUR <= dt < end - self.HOUR:
            # DST is in effect.
            return self.HOUR
        if end - self.HOUR <= dt < end:
            # Fold (an ambiguous hour): use dt.fold to disambiguate.
            return self.ZERO if dt.fold else self.HOUR
        if start <= dt < start + self.HOUR:
            # Gap (a non-existent hour): reverse the fold rule.
            return self.HOUR if dt.fold else self.ZERO
        # DST is off.
        return self.ZERO

    def fromutc(self, dt):
        assert dt.tzinfo is self
        start, end = USTimeZone.us_dst_range(dt.year)
        start = start.replace(tzinfo=self)
        end = end.replace(tzinfo=self)
        std_time = dt + self.stdoffset
        dst_time = std_time + self.HOUR
        if end <= dst_time < end + self.HOUR:
            # Repeated hour
            return std_time.replace(fold=1)
        if std_time < start or dst_time >= end:
            # Standard time
            return std_time
        if start <= std_time < end - self.HOUR:
            # Daylight saving time
            return dst_time


# US timezone implementations
tz_eastern = USTimeZone(-5, "Eastern", "EST", "EDT")
tz_central = USTimeZone(-6, "Central", "CST", "CDT")
tz_mountain = USTimeZone(-7, "Mountain", "MST", "MDT")
tz_pacific = USTimeZone(-8, "Pacific", "PST", "PDT")


def _get_time_tuple(timestamp: int = None, tz: tzinfo = None) -> tuple:
    if not tz:
        tz = tz_pacific

    if timestamp:
        now = datetime.fromtimestamp(timestamp, tz=tz)
    else:
        now = datetime.now(tz)

    return (now.year, now.month, now.day, now.hour, now.minute, now.second, now.weekday())


def get_fmt_date(timestamp: int = None, tz: tzinfo = None) -> str:
    """Get formatted date string

    Args:
        timestamp (int, optional): Create format str from this epoch timestamp.
                                   If None, will use current datetime.
        tz (tzinfo, optional): Timezone. Defaults to tz_pacific if None is passed.

    Returns:
        str: Formatted date string
    """
    data_fmt_str = "%d/%d/%d"
    now_tuple = _get_time_tuple(timestamp, tz)
    return data_fmt_str % (now_tuple[1], now_tuple[2], now_tuple[0])


def get_fmt_datetime(timestamp: int = None, tz: tzinfo = None) -> str:
    """Get formatted datetime string

    Args:
        timestamp (int, optional): Create format str from this epoch timestamp.
                                   If None, will use current time.
        tz (tzinfo, optional): Timezone. Defaults to tz_pacific if None is passed.

    Returns:
        str: Formatted datetime string
    """
    return f"{get_fmt_date(timestamp, tz)} - {get_fmt_time(timestamp, tz)}"


def get_fmt_time(timestamp: int = None, tz: tzinfo = None) -> str:
    """Get formatted time string

    Args:
        timestamp (int, optional): Create format str from this epoch timestamp.
                                   If None, will use current time.
        tz (tzinfo, optional): Timezone. Defaults to tz_pacific if None is passed.

    Returns:
        str: Formatted time string
    """
    time_fmt_str = "%d:%02d:%02d"
    now_tuple = _get_time_tuple(timestamp, tz)
    return time_fmt_str % (now_tuple[3], now_tuple[4], now_tuple[5])
