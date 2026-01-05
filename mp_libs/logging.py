"""
logging.py

# TODO: Update BufferHandler to support fixed size buffer
"""
import io
import sys
import time
from collections import namedtuple
from machine import RTC
from micropython import const

CRITICAL = const(50)
ERROR = const(40)
WARNING = const(30)
INFO = const(20)
DEBUG = const(10)
NOTSET = const(0)
_DEFAULT_LEVEL = const(WARNING)
_IS_RTC_SET_THRESH = const(779_658_124)

_level_dict = {
    CRITICAL: "CRITICAL",
    ERROR: "ERROR",
    WARNING: "WARNING",
    INFO: "INFO",
    DEBUG: "DEBUG",
    NOTSET: "NOTSET",
}

_loggers = {}
_stream = sys.stderr
# _default_fmt = "%(mono)d %(levelname)s-%(name)s:%(message)s"
_default_fmt = "%(asctime)s.%(msecs)d %(levelname)s-%(name)s:%(message)s"
_default_datefmt = "%Y-%m-%d %H:%M:%S"


LogRecord = namedtuple(
    "LogRecord", ("name", "levelno", "levelname", "message", "dt", "mono", "msecs", "is_time_sync")
)


def _log_record_factory(name: str, level: int, msg: str) -> LogRecord:
    if time.time() < _IS_RTC_SET_THRESH:
        is_time_sync = False
        dt = time.localtime()
        msecs = time.ticks_ms()
    else:
        rtc = RTC()
        dt = rtc.datetime()
        now = rtc.now()
        msecs = now - ((now // 1_000_000) * 1_000_000)
        is_time_sync = True

    return LogRecord(name, level, _level_dict[level], msg, dt, time.ticks_ms(), msecs, is_time_sync)


class Handler:
    def __init__(self, level=NOTSET):
        self.level = level
        self.formatter = None

    def close(self):
        pass

    def emit(self, record):
        pass

    def setLevel(self, level):
        self.level = level

    def setFormatter(self, formatter):
        self.formatter = formatter

    def format(self, record):
        return self.formatter.format(record)


class StreamHandler(Handler):
    def __init__(self, stream=None):
        self.stream = _stream if stream is None else stream
        self.terminator = "\n"

    def close(self):
        if self.stream and hasattr(self.stream, "flush"):
            try:
                self.stream.flush()
            except ValueError:
                pass

        if self.stream and hasattr(self.stream, "close"):
            try:
                self.stream.close()
            except ValueError:
                pass

        self.stream = None

    def emit(self, record):
        if record.levelno >= self.level and self.stream:
            self.stream.write(self.format(record) + self.terminator)


class FileHandler(StreamHandler):
    def __init__(self, filename, mode="a", encoding="UTF-8"):
        super().__init__(stream=open(filename, mode=mode, encoding=encoding))


class BufferHandler(Handler):
    def __init__(self, buffer: list = None):
        self.buffer = buffer if buffer is not None else []

    def emit(self, record):
        if record.levelno >= self.level:
            self.buffer.append(self.format(record))


class Formatter:
    def __init__(self, fmt=None, datefmt=None):
        self.fmt = _default_fmt if fmt is None else fmt
        self.datefmt = _default_datefmt if datefmt is None else datefmt

    def formatTime(self, datefmt, record):
        if hasattr(time, "strftime"):
            return time.strftime(datefmt, record.dt)

        if record.is_time_sync:
            return f"{record.dt[0]}-{record.dt[1]:02d}-{record.dt[2]:02d} {record.dt[4]:02d}:{record.dt[5]:02d}:{record.dt[6]:02d}"

        return f"{record.dt[0]}-{record.dt[1]:02d}-{record.dt[2]:02d} {record.dt[3]:02d}:{record.dt[4]:02d}:{record.dt[5]:02d}"

    def format(self, record):
        if "{asctime}" in self.fmt or "%(asctime)s" in self.fmt:
            asctime = self.formatTime(self.datefmt, record)
        else:
            asctime = ""

        return self.fmt % {
            "name": record.name,
            "message": record.message,
            "msecs": record.msecs,
            "asctime": asctime,
            "levelname": record.levelname,
            "mono": record.mono,
        }


class Logger:
    def __init__(self, name, level=NOTSET):
        self.name = name
        self.level = level
        self.handlers = []

    def setLevel(self, level):
        self.level = level

    def isEnabledFor(self, level):
        return level >= self.getEffectiveLevel()

    def getEffectiveLevel(self):
        return self.level or getLogger().level or _DEFAULT_LEVEL

    def log(self, level, msg, *args):
        if self.isEnabledFor(level):
            if args:
                if isinstance(args[0], dict):
                    args = args[0]
                msg = msg % args
            record = _log_record_factory(self.name, level, msg)

            # Call any root handlers
            for h in getLogger().handlers:
                h.emit(record)

            # Call any local handlers
            for h in self.handlers:
                h.emit(record)

    def debug(self, msg, *args):
        self.log(DEBUG, msg, *args)

    def info(self, msg, *args):
        self.log(INFO, msg, *args)

    def warning(self, msg, *args):
        self.log(WARNING, msg, *args)

    def error(self, msg, *args):
        self.log(ERROR, msg, *args)

    def critical(self, msg, *args):
        self.log(CRITICAL, msg, *args)

    def exception(self, msg, *args, exc_info=True):
        self.log(ERROR, msg, *args)
        tb = None
        if isinstance(exc_info, BaseException):
            tb = exc_info
        elif hasattr(sys, "exc_info"):
            tb = sys.exc_info()[1]
        if tb:
            buf = io.StringIO()
            sys.print_exception(tb, buf)
            self.log(ERROR, buf.getvalue())

    def addHandler(self, handler):
        self.handlers.append(handler)

    def hasHandlers(self):
        return len(self.handlers) > 0


def getLogger(name=None):
    if name is None:
        name = "root"
    if name not in _loggers:
        _loggers[name] = Logger(name)
        if name == "root":
            basicConfig()
    return _loggers[name]


def log(level, msg, *args):
    getLogger().log(level, msg, *args)


def debug(msg, *args):
    getLogger().debug(msg, *args)


def info(msg, *args):
    getLogger().info(msg, *args)


def warning(msg, *args):
    getLogger().warning(msg, *args)


def error(msg, *args):
    getLogger().error(msg, *args)


def critical(msg, *args):
    getLogger().critical(msg, *args)


def exception(msg, *args):
    getLogger().exception(msg, *args)


def shutdown():
    for logger in _loggers.values():
        for h in logger.handlers:
            h.close()
        logger.handlers = []

    _loggers.clear()


def addLevelName(level, name):
    _level_dict[level] = name


def basicConfig(
    filename=None,
    filemode="a",
    fmt=_default_fmt,
    datefmt=_default_datefmt,
    level=NOTSET,
    stream=None,
    encoding="UTF-8",
    force=False,
):
    if "root" not in _loggers:
        _loggers["root"] = Logger("root")

    logger = _loggers["root"]

    if force or not logger.handlers:
        for h in logger.handlers:
            h.close()
        logger.handlers = []

        if filename is None:
            handler = StreamHandler(stream)
        else:
            handler = FileHandler(filename, filemode, encoding)

        handler.setLevel(level)
        handler.setFormatter(Formatter(fmt, datefmt))

        logger.setLevel(level)
        logger.addHandler(handler)


# Add root logger if not already
if "root" not in _loggers:
    _loggers["root"] = Logger("root")
    basicConfig()


if hasattr(sys, "atexit"):
    sys.atexit(shutdown)
