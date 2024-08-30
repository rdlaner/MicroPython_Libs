"""Memory Support Library

# TODO: Update rtc memory to support slicing
"""
# pylint: disable=c-extension-no-member
# pyright: reportGeneralTypeIssues=false
# Standard imports
import struct
from collections import OrderedDict
from machine import RTC
from micropython import const

# Third party imports
from mp_libs import logging

# Local imports
try:
    from config import config
except ImportError:
    config = {"logging_level": logging.INFO}

# Constants
DEF_RAM_OFFSET = const(0)
DEF_LIST_OFFSET = const(400)
MAGIC_NUM_OFFSET = const(0)
FREE_INDEX_OFFSET = const(4)
NUM_ELEMS_OFFSET = const(6)
ELEMENTS_OFFSET = const(8)
MAGIC_NUM = const(0xFEEDFACE)
ELEMENT_BYTE_ORDER = ">"
ELEMENT_FORMAT = "BBs%ds%s"  # name_len, data_len, data_type, name, data type str
ELEMENT_FORMAT_STR = ELEMENT_BYTE_ORDER + ELEMENT_FORMAT
ELEMENT_NAME_LEN_OFFSET = const(0)
ELEMENT_DATA_LEN_OFFSET = const(1)
ELEMENT_DATA_TYPE_OFFSET = const(2)
ELEMENT_NAME_OFFSET = const(3)
ELEMENT_MAX_DATA_LEN = const(255)
ELEMENT_MAX_NAME_LEN = const(255)

# Globals
logger = logging.getLogger("memory")
logger.setLevel(config["logging_level"])


class BackupRAM():
    """Backup RAM Abstraction

    For those boards that support Micropython's RTC.memory, this class provides easy access
    API for storing and retrieving data from RTC memory. RTC memory is essentially a contiguous
    array of data stored in battery-backed RAM that can persist across reboots. However, it is not
    non-volatile, so it will reset after a hard power cycle.

    BackupRAM's data structure looks like this in memory:
    -----------------------------------------------------------------
    | Meta Data (8 bytes) | Element 1 | Element 2 | ... | Element X |
    -----------------------------------------------------------------

    The first 8 bytes of RTC memory are reserved to hold the BackupRAM's meta data:
      * (4 byte) magic number - magic number used to validate data
      * (2 bytes) free index - marking next available location/index in memory.
      * (2 bytes) number of elements already stored in BackupRAM

    The rest of BackupRAM is composed of a series of elements that get added whenever a user adds
    data. Each element is composed of the following attributes and in this order:
    -------------------------------------------------
    | name_len | data_len | data_type | name | data |
    -------------------------------------------------
    The first 3 attributes act as a header to allow for parsing of the element name and data and
    to support variable sized elements.
    The element's 'name' and 'data' attributes are what the user interacts with and act just like
    a key/value pair in a dict:
      * Element name length - 1 byte
      * Element data length - 1 byte
      * Element data type - single char indicating how data is formatted
      * Element name - string of length 'name length'
      * Element data - of type 'data type' and of size 'data length'
    """
    def __init__(self, offset: int = DEF_RAM_OFFSET, size: int = None, reset: bool = False) -> None:
        self.offset = offset
        self.size = size
        self.rtc = RTC()

        valid_magic = self._check_magic_num()
        if not valid_magic:
            logger.warning("Invalid magic number. Corrupted backup ram.")

        if reset or not valid_magic:
            self.reset()

        # Initialize meta data
        free_index = self._get_free_index()
        num_elements = self._get_num_elems()
        if free_index < self.offset + ELEMENTS_OFFSET:
            self._set_free_index(self.offset + ELEMENTS_OFFSET)

        logger.debug(f"free_index: {free_index}")
        logger.debug(f"num_elements: {num_elements}")

        # Build up element name to RTC_memory index lookup table. Uses extra memory to speed up
        # add, get, and set element API.
        self._elements_lut = OrderedDict()
        index = self.offset + ELEMENTS_OFFSET
        for _ in range(num_elements):
            name = self._element_get_name(index)
            size = self._element_get_size(index)
            self._elements_lut[name] = index
            index += size

    def _check_magic_num(self) -> bool:
        return self._get_magic() == MAGIC_NUM

    def _element_get_data(self, start_byte: int):
        name_len = self._element_get_name_length(start_byte)
        data_len = self._element_get_data_len(start_byte)
        data_type = self._element_get_data_type(start_byte)
        offset = start_byte +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_NAME_LEN_OFFSET]) +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_DATA_LEN_OFFSET]) +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_DATA_TYPE_OFFSET]) +\
            name_len
        byte_data = bytearray()

        for i in range(data_len):
            byte_data.append(self.rtc[offset + i])

        if data_type == "s":
            data_type = f"{data_len}s"

        return struct.unpack(f">{data_type}", byte_data)[0]

    def _element_get_data_len(self, start_byte: int) -> int:
        byte_data = bytearray([self.rtc[start_byte + ELEMENT_DATA_LEN_OFFSET]])
        return struct.unpack_from(">B", byte_data, 0)[0]

    def _element_get_data_type(self, start_byte: int) -> str:
        byte_data = bytearray([self.rtc[start_byte + ELEMENT_DATA_TYPE_OFFSET]])
        return struct.unpack_from(">s", byte_data, 0)[0].decode()

    def _element_get_name(self, start_byte: int) -> str:
        name_len = self._element_get_name_length(start_byte)
        offset = start_byte +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_NAME_LEN_OFFSET]) +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_DATA_LEN_OFFSET]) +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_DATA_TYPE_OFFSET])
        byte_data = bytearray()

        for i in range(name_len):
            byte_data.append(self.rtc[offset + i])

        return struct.unpack(f">{name_len}s", byte_data)[0].decode()

    def _element_get_name_length(self, start_byte: int) -> int:
        byte_data = bytearray([self.rtc[start_byte + ELEMENT_NAME_LEN_OFFSET]])
        return struct.unpack_from(">B", byte_data, 0)[0]

    def _element_get_size(self, start_byte: int) -> int:
        name_len = self._element_get_name_length(start_byte)
        data_len = self._element_get_data_len(start_byte)
        size = struct.calcsize(ELEMENT_FORMAT[ELEMENT_NAME_LEN_OFFSET]) +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_DATA_LEN_OFFSET]) +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_DATA_TYPE_OFFSET]) +\
            name_len +\
            data_len
        return size

    def _get_free_index(self) -> int:
        return self._get_rtc_memory_data(self.offset + FREE_INDEX_OFFSET, self.offset + FREE_INDEX_OFFSET + 2, "H")

    def _get_magic(self) -> int:
        return self._get_rtc_memory_data(self.offset + MAGIC_NUM_OFFSET, self.offset + MAGIC_NUM_OFFSET + 4, "I")

    def _get_num_elems(self) -> int:
        return self._get_rtc_memory_data(self.offset + NUM_ELEMS_OFFSET, self.offset + NUM_ELEMS_OFFSET + 2, "H")

    def _get_rtc_memory_data(self, start_byte: int, end_byte: int, data_type: str):
        # rtc memory doesn't support slicing, so have to iterate
        byte_data = bytearray()
        for i in range(start_byte, end_byte):
            byte_data.append(self.rtc[i])

        return struct.unpack(f">{data_type}", byte_data)[0]

    def _set_free_index(self, value) -> None:
        self._set_rtc_memory_data(self.offset + FREE_INDEX_OFFSET, "H", value)

    def _set_magic(self) -> None:
        self._set_rtc_memory_data(self.offset + MAGIC_NUM_OFFSET, "I", MAGIC_NUM)

    def _set_num_elems(self, value) -> None:
        self._set_rtc_memory_data(self.offset + NUM_ELEMS_OFFSET, "H", value)

    def _set_rtc_memory_data(self, start_byte: int, data_type: str, data) -> None:
        byte_data = struct.pack(f">{data_type}", data)
        for i, byte in enumerate(byte_data):
            self.rtc[start_byte + i] = byte

    @staticmethod
    def reset_rtc() -> None:
        """Reset all of rtc memory"""
        rtc = RTC()
        for i in range(len(rtc)):
            rtc[i] = 0

    def add_element(self, name: str, data_type: str, data, clear_if_full: bool = False) -> None:
        """Adds a new name/data element to backup RAM.

        Args:
            name (str): Name of new element. Used as a key for lookup.
            data_type (str): Data type as defined by struct format characters.
            data : Data of type `data_type`.
            clear_if_full (bool): Clear memory if not enough room for new element.
        """
        # Handle string data type
        if "s" in data_type:
            if len(data) > ELEMENT_MAX_DATA_LEN:
                data = data[0:ELEMENT_MAX_DATA_LEN]
            data = data.encode()
            data_type = "s"
            data_type_fmt = f"{len(data)}s"
        else:
            data_type_fmt = data_type

        # Ensure name isn't too long
        if len(name) > ELEMENT_MAX_NAME_LEN:
            name = name[0:ELEMENT_MAX_NAME_LEN]

        # Pack up the element: name_len, data_len, data_type, name, data
        packed_data = struct.pack(
            ELEMENT_FORMAT_STR % (len(name), data_type_fmt),
            len(name),
            struct.calcsize(data_type_fmt),
            data_type.encode(),
            name.encode(),
            data
        )

        # Make sure there is enough room for the new element
        index = self._get_free_index()
        if self.size and (index + len(packed_data) >= self.offset + self.size):
            msg = (
                "Attempted to write beyond size of backup ram instance\n" +
                f"Offset: {self.offset}" +
                f"Max size: {self.size} bytes\n" +
                f"Overran by: {(index + len(packed_data) - (self.offset + self.size))} bytes"
            )

            if clear_if_full:
                self.reset(clear=True, verbose=False)
                logger.warning(msg)
                logger.warning("Cleared memeory")
                index = self._get_free_index()
            else:
                raise RuntimeError(msg)
        if index + len(packed_data) >= self.rtc.MEM_SIZE:
            msg = (
                "Attempted to write beyond the max size of rtc.memory\n" +
                f"Offset: {self.offset}" +
                f"Max size: {self.rtc.MEM_SIZE}\n" +
                f"Overran by: {(index + len(packed_data) - self.rtc.MEM_SIZE)}"
            )

            if clear_if_full:
                self.reset(clear=True, verbose=False)
                logger.error(msg)
                logger.error("Cleared memeory")
                index = self._get_free_index()
            else:
                raise RuntimeError(msg)

        # Append element to next available index in rtc bytearray
        self._elements_lut[name] = index
        for byte in packed_data:
            self.rtc[index] = byte
            index += 1

        # Update free index and num elements
        self._set_free_index(index)
        self._set_num_elems(self._get_num_elems() + 1)

    def get_element(self, name: str):
        """Return the element's data from backup RAM.

        Args:
            name (str): Name of element to retrieve data

        Returns:
            Element data
        """
        return self._element_get_data(self._elements_lut[name])

    def print_elements(self) -> None:
        """Print contents of backup RAM."""
        print(f"Magic: {self._get_magic()}")
        print(f"Free index: {self._get_free_index()}")
        print(f"Num elems: {self._get_num_elems()}")

        print("Backup RAM elements:")
        for name in self._elements_lut:
            print(f"{name}: {self.get_element(name)}")

    def reset(self, clear: bool = False, verbose: bool = True):
        """Reset backup RAM. All existing data will be lost."""
        if verbose:
            logger.warning(f"Resetting nvram memory at offset: {self.offset}...")

        if clear:
            index = self.offset + ELEMENTS_OFFSET
            for _ in range(self._get_num_elems()):
                size = self._element_get_size(index)
                index += size

            for i in range(self.offset + ELEMENTS_OFFSET, index):
                self.rtc[i] = 0

        self._set_magic()
        self._set_free_index(self.offset + ELEMENTS_OFFSET)
        self._set_num_elems(0)
        self._elements_lut = OrderedDict()

    def set_element(self, name: str, data):
        """Write the element's data to backup RAM.

        Args:
            name (str): Name of element to update.
            data : Data to set. Must be of type defined when element was added.
        """
        start_byte = self._elements_lut[name]
        data_type = self._element_get_data_type(start_byte)

        if "s" in data_type:
            data_len = self._element_get_data_len(start_byte)
            if len(data) != data_len:
                msg = (
                    "String data length must match that of original string\n" +
                    f"Original len: {data_len}\n" +
                    f"New len: {len(data)}"
                )
                raise RuntimeError(msg)

            data = data.encode()
            data_type = "s"
            data_type_fmt = f"{len(data)}s"
        else:
            data_type_fmt = data_type

        # Rebuild packed struct w/ new data
        packed_data = struct.pack(
            ELEMENT_FORMAT_STR % (len(name), data_type_fmt),
            len(name),
            struct.calcsize(data_type_fmt),
            data_type.encode(),
            name.encode(),
            data
        )

        # Update element in memory
        for i, byte in enumerate(packed_data):
            self.rtc[start_byte + i] = byte


class BackupList(BackupRAM):
    """
    NOTE: Don't use logger in this class since BackupList can be used as a logger handler
    """
    def __init__(self, offset: int = DEF_LIST_OFFSET, reset: bool = False) -> None:
        super().__init__(offset, reset)
        self._list = []

        for index in self._elements_lut.values():
            self._list.append(self._element_get_data(index).decode())

    def __bool__(self):
        return len(self._list) > 0

    def __getitem__(self, index):
        return self._list[index]

    def __len__(self):
        return len(self._list)

    def __setitem__(self, index, value):
        name = f"l{index}"
        if name not in self._elements_lut:
            raise RuntimeError(f"Invalid index: {index}")

        self.set_element(name, value)
        self._list[index] = value

    def append(self, value):
        if isinstance(value, int):
            fmt_char = "i"
        elif isinstance(value, str):
            fmt_char = "s"
        else:
            raise RuntimeError(f"Unsupported value type for {value}: {type(value)}")

        index = self._get_num_elems() + 1
        self.add_element(f"l{index}", fmt_char, value, clear_if_full=True)
        self._list.append(value)

    def clear(self):
        self._list.clear()
        self.reset()

    def copy(self) -> list:
        return self._list.copy()
