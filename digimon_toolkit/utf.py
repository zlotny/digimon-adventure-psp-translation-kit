"""
@UTF Table Parser for CRI CPK Archives.
Based on CriPakTools by esperknight (Falo, Nanashi3).
"""
import struct
from typing import Dict, List, Any, Optional, Tuple


STORAGE_NAMES = {0: 'NONE', 1: 'ZERO', 3: 'CONSTANT', 5: 'PERROW'}
TYPE_NAMES = {
    0: 'U8', 1: 'S8', 2: 'U16', 3: 'S16', 4: 'U32', 5: 'S32',
    6: 'U64', 7: 'S64', 8: 'FLOAT', 0xA: 'STRING', 0xB: 'DATA'
}


class UTFColumn:
    """A column definition in a @UTF table."""
    def __init__(self, index: int, flags: int, name: str):
        self.index = index
        self.flags = flags
        self.name = name
        self.storage = (flags >> 4) & 0xF
        self.data_type = flags & 0xF

    @property
    def type_name(self) -> str:
        return TYPE_NAMES.get(self.data_type, f'0x{self.data_type:x}')

    @property
    def storage_name(self) -> str:
        return STORAGE_NAMES.get(self.storage, f'0x{self.storage:x}')

    @property
    def is_perrow(self) -> bool:
        return self.storage == 5

    @property
    def byte_size(self) -> int:
        """Size of this column's data in a row."""
        if not self.is_perrow:
            return 0
        if self.data_type in (0, 1):
            return 1
        elif self.data_type in (2, 3):
            return 2
        elif self.data_type in (4, 5, 8, 0xA):
            return 4
        elif self.data_type in (6, 7):
            return 8
        elif self.data_type == 0xB:  # DATA: int32 offset + int32 size
            return 8
        return 0


class UTFTable:
    """A @UTF table from a CRI CPK archive."""

    def __init__(self):
        self.columns: List[UTFColumn] = []
        self.num_columns: int = 0
        self.num_rows: int = 0
        self.row_length: int = 0
        self.table_name: int = 0

        # File offsets
        self.base_offset: int = 0
        self.rows_offset: int = 0
        self.strings_offset: int = 0
        self.data_offset: int = 0

        # Raw data
        self._raw_data: bytes = b''

    @staticmethod
    def parse(data: bytes, base_offset: int = 0) -> 'UTFTable':
        """
        Parse a @UTF table from raw bytes (starting at @UTF signature).
        base_offset is the absolute file offset where data[0] is located.
        """
        table = UTFTable()
        table._raw_data = data
        table.base_offset = base_offset

        pos = 0
        sig = data[pos:pos+4]
        if sig != b'@UTF':
            raise ValueError(f"Not a @UTF table: {sig!r}")

        pos += 4
        table_size = struct.unpack('>i', data[pos:pos+4])[0]
        pos += 4
        rows_rel = struct.unpack('>i', data[pos:pos+4])[0]
        pos += 4
        strings_rel = struct.unpack('>i', data[pos:pos+4])[0]
        pos += 4
        data_rel = struct.unpack('>i', data[pos:pos+4])[0]
        pos += 4
        table.table_name = struct.unpack('>i', data[pos:pos+4])[0]
        pos += 4
        table.num_columns = struct.unpack('>h', data[pos:pos+2])[0]
        pos += 2
        table.row_length = struct.unpack('>h', data[pos:pos+2])[0]
        pos += 2
        table.num_rows = struct.unpack('>i', data[pos:pos+4])[0]
        pos += 4

        # Absolute offsets
        abs_base = base_offset + 8  # @UTF + 8 for the offset base
        table.rows_offset = abs_base + rows_rel
        table.strings_offset = abs_base + strings_rel
        table.data_offset = abs_base + data_rel

        # Read column definitions
        for i in range(table.num_columns):
            flags = data[pos]
            pos += 1
            if flags == 0:
                pos += 3  # skip padding
                flags = data[pos]
                pos += 1

            name_off = struct.unpack('>i', data[pos:pos+4])[0]
            pos += 4

            # Read name from string table
            name_abs = table.strings_offset - base_offset + name_off
            if 0 <= name_abs < len(data):
                end = data.find(b'\x00', name_abs)
                if end > name_abs:
                    try:
                        name = data[name_abs:end].decode('shift-jis', errors='replace')
                    except:
                        name = repr(data[name_abs:end])
                else:
                    name = f"<offset_{name_off}>"
            else:
                name = f"<offset_{name_off}>"

            col = UTFColumn(i, flags, name)
            table.columns.append(col)

        return table

    def _read_value_at(self, data: bytes, abs_file_offset: int) -> Any:
        """Read a single value from an absolute file offset within this table."""
        local_off = abs_file_offset - self.base_offset

        # We need to know which column this is. Instead, read per-row.
        pass

    def get_row(self, row_index: int, raw_data: bytes) -> Dict[str, Any]:
        """Get row data as a dictionary of column_name -> value."""
        row_abs = self.rows_offset
        row_start = row_abs - self.base_offset + row_index * self.row_length

        result = {}
        pos_in_row = row_start

        for col in self.columns:
            if not col.is_perrow:
                result[col.name] = None
                continue

            if col.data_type in (0, 1):  # 1 byte
                val = raw_data[pos_in_row]
                pos_in_row += 1
            elif col.data_type in (2, 3):  # 2 bytes
                val = struct.unpack('>H', raw_data[pos_in_row:pos_in_row+2])[0]
                pos_in_row += 2
            elif col.data_type in (4, 5):  # 4 bytes
                val = struct.unpack('>I', raw_data[pos_in_row:pos_in_row+4])[0]
                pos_in_row += 4
            elif col.data_type in (6, 7):  # 8 bytes
                val = struct.unpack('>Q', raw_data[pos_in_row:pos_in_row+8])[0]
                pos_in_row += 8
            elif col.data_type == 8:  # FLOAT
                val = struct.unpack('>f', raw_data[pos_in_row:pos_in_row+4])[0]
                pos_in_row += 4
            elif col.data_type == 0xA:  # STRING
                str_off = struct.unpack('>i', raw_data[pos_in_row:pos_in_row+4])[0]
                abs_str = self.strings_offset + str_off
                local_off = abs_str - self.base_offset
                end_s = raw_data.find(b'\x00', local_off)
                if 0 <= local_off < len(raw_data) and end_s > local_off:
                    try:
                        val = raw_data[local_off:end_s].decode('shift-jis', errors='replace')
                    except:
                        val = repr(raw_data[local_off:end_s])
                else:
                    val = f"<str_off_{str_off}>"
                pos_in_row += 4
            elif col.data_type == 0xB:  # DATA (offset + size)
                d_off = struct.unpack('>i', raw_data[pos_in_row:pos_in_row+4])[0]
                d_size = struct.unpack('>i', raw_data[pos_in_row+4:pos_in_row+8])[0]
                abs_d = self.data_offset + d_off
                local_d = abs_d - self.base_offset
                if 0 <= local_d < len(raw_data):
                    val = raw_data[local_d:min(local_d+d_size, len(raw_data))]
                else:
                    val = b''
                pos_in_row += 8
            else:
                val = None
                pos_in_row += col.byte_size

            result[col.name] = val

        return result

    def get_value(self, row_index: int, column_name: str, raw_data: bytes) -> Any:
        """Get a single value from a specific row and column."""
        return self.get_row(row_index, raw_data).get(column_name)

    def get_column_position(self, row_index: int, column_name: str, raw_data: bytes) -> int:
        """Get the absolute file position of a column value within a row."""
        row_abs = self.rows_offset
        row_start = row_abs - self.base_offset + row_index * self.row_length
        pos_in_row = row_start

        for col in self.columns:
            if not col.is_perrow:
                continue
            if col.name == column_name:
                return pos_in_row + self.base_offset  # absolute
            pos_in_row += col.byte_size
        return -1


def parse_utf_table(data: bytes, base_offset: int = 0) -> UTFTable:
    """Convenience function to parse a @UTF table."""
    return UTFTable.parse(data, base_offset)
