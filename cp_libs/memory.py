"""Memory Support Library"""
# pylint: disable=c-extension-no-member
# Standard imports
import alarm
import struct
from micropython import const

# Third party imports

# Local imports

# Constants
FREE_INDEX_OFFSET = const(0)
NUM_ELEMS_OFFSET = const(4)
ELEMENTS_OFFSET = const(8)
ELEMENT_BYTE_ORDER = ">"
ELEMENT_FORMAT = "BBs%ds%s"  # name_len, data_len, data_type, name, data type str
ELEMENT_FORMAT_STR = ELEMENT_BYTE_ORDER + ELEMENT_FORMAT
ELEMENT_NAME_LEN_OFFSET = const(0)
ELEMENT_DATA_LEN_OFFSET = const(1)
ELEMENT_DATA_TYPE_OFFSET = const(2)
ELEMENT_NAME_OFFSET = const(3)

# Globals


class BackupRAM():
    """Backup RAM Abstraction

    For those boards that support CircuitPython's sleep_memory, this class provides easy access
    API for storing and retrieving data from sleep memory. Sleep memory is essentially a contiguous
    array of data stored in battery-backed RAM that can persist across reboots. However, it is not
    non-volatile, so it will reset after a hard power cycle.

    BackupRAM's data structure looks like this in memory:
    -----------------------------------------------------------------
    | Meta Data (8 bytes) | Element 1 | Element 2 | ... | Element X |
    -----------------------------------------------------------------

    The first 8 bytes of sleep_memory are reserved to hold the BackupRAM's meta data:
      * free index - marking next available location/index in memory.
      * number of elements already stored in BackupRAM

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
    def __init__(self, reset: bool = False) -> None:
        if reset:
            self.reset()

        # Initialize meta data
        free_index = self._get_free_index()
        num_elements = self._get_num_elems()
        if free_index < ELEMENTS_OFFSET:
            self._set_free_index(ELEMENTS_OFFSET)

        # Build up element name to sleep_memory index lookup table. Uses extra memory to speed up
        # add, get, and set element API.
        self._elements_lut = {}
        index = ELEMENTS_OFFSET
        for _ in range(num_elements):
            name = self._element_get_name(index)
            size = self._element_get_size(index)
            self._elements_lut[name] = index
            index += size

    def _get_free_index(self) -> int:
        return self._get_sleep_memory_data(FREE_INDEX_OFFSET, FREE_INDEX_OFFSET + 4, "i")

    def _get_num_elems(self) -> int:
        return self._get_sleep_memory_data(NUM_ELEMS_OFFSET, NUM_ELEMS_OFFSET + 4, "i")

    def _set_free_index(self, value) -> int:
        self._set_sleep_memory_data(FREE_INDEX_OFFSET, "i", value)

    def _set_num_elems(self, value) -> int:
        self._set_sleep_memory_data(NUM_ELEMS_OFFSET, "i", value)

    def _element_get_name_length(self, start_byte: int) -> int:
        byte_data = bytearray([alarm.sleep_memory[start_byte + ELEMENT_NAME_LEN_OFFSET]])
        return struct.unpack_from(">B", byte_data, 0)[0]

    def _element_get_data_len(self, start_byte: int) -> int:
        byte_data = bytearray([alarm.sleep_memory[start_byte + ELEMENT_DATA_LEN_OFFSET]])
        return struct.unpack_from(">B", byte_data, 0)[0]

    def _element_get_data_type(self, start_byte: int) -> str:
        byte_data = bytearray([alarm.sleep_memory[start_byte + ELEMENT_DATA_TYPE_OFFSET]])
        return struct.unpack_from(">s", byte_data, 0)[0].decode()

    def _element_get_name(self, start_byte: int) -> str:
        name_len = self._element_get_name_length(start_byte)
        offset = start_byte +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_NAME_LEN_OFFSET]) +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_DATA_LEN_OFFSET]) +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_DATA_TYPE_OFFSET])
        byte_data = bytearray()

        for i in range(name_len):
            byte_data.append(alarm.sleep_memory[offset + i])

        return struct.unpack(f">{name_len}s", byte_data)[0].decode()

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
            byte_data.append(alarm.sleep_memory[offset + i])

        return struct.unpack(f">{data_type}", byte_data)[0]

    def _element_get_size(self, start_byte: int) -> int:
        name_len = self._element_get_name_length(start_byte)
        data_len = self._element_get_data_len(start_byte)
        size = struct.calcsize(ELEMENT_FORMAT[ELEMENT_NAME_LEN_OFFSET]) +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_DATA_LEN_OFFSET]) +\
            struct.calcsize(ELEMENT_FORMAT[ELEMENT_DATA_TYPE_OFFSET]) +\
            name_len +\
            data_len
        return size

    def _get_sleep_memory_data(self, start_byte: int, end_byte: int, data_type: str):
        # sleep_memory doesn't support slicing, so have to iterate
        byte_data = bytearray()
        for i in range(start_byte, end_byte):
            byte_data.append(alarm.sleep_memory[i])

        return struct.unpack(f">{data_type}", byte_data)[0]

    def _set_sleep_memory_data(self, start_byte: int, data_type: str, data):
        byte_data = struct.pack(f">{data_type}", data)
        for i, byte in enumerate(byte_data):
            alarm.sleep_memory[start_byte + i] = byte

    def add_element(self, name: str, data_type: str, data) -> None:
        """Adds a new name/data element to backup RAM.

        Args:
            name (str): Name of new element. Used as a key for lookup.
            data_type (str): Data type as defined by struct format characters.
            data : Data of type `data_type`.
        """
        # Pack up the element: name_len, data_len, data_type, name, data
        packed_data = struct.pack(
            ELEMENT_FORMAT_STR % (len(name), data_type),
            len(name),
            struct.calcsize(data_type),
            data_type.encode(),
            name.encode(),
            data
        )

        # Append element to next available index in sleep_memory bytearray
        index = self._get_free_index()
        num_elements = self._get_num_elems()
        self._elements_lut[name] = index
        for bite in packed_data:
            alarm.sleep_memory[index] = bite
            index += 1

        # Update free index and num elements
        self._set_free_index(index)
        self._set_num_elems(num_elements + 1)

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
        print(f"Free index: {self._get_free_index()}")
        print(f"Num elems: {self._get_num_elems()}")

        print("Backup RAM elements:")
        for name in self._elements_lut:
            print(f"{name}: {self.get_element(name)}")

    def reset(self):
        """Reset backup RAM. All existing data will be lost."""
        print("Resetting nv memory...")
        for i in range(len(alarm.sleep_memory)):
            alarm.sleep_memory[i] = 0

        self._set_free_index(ELEMENTS_OFFSET)
        self._set_num_elems(0)
        self._elements_lut = {}

    def set_element(self, name: str, data):
        """Write the element's data to backup RAM.

        Args:
            name (str): Name of element to update.
            data : Data to set. Must be of type defined when element was added.
        """
        start_byte = self._elements_lut[name]
        data_type = self._element_get_data_type(start_byte)

        # Rebuild packed struct w/ new data
        packed_data = struct.pack(
            ELEMENT_FORMAT_STR % (len(name), data_type),
            len(name),
            struct.calcsize(data_type),
            data_type.encode(),
            name.encode(),
            data
        )

        # Update element in memory
        for i, byte in enumerate(packed_data):
            alarm.sleep_memory[start_byte + i] = byte
