"""
pBin Container Format Parser for Digimon Adventure PSP.
pBin is a container format that holds sub-resources (PLYT, PIMG, PANM, BIN).
"""
import struct
from typing import List, Dict, Optional, Tuple, BinaryIO, Any
from dataclasses import dataclass, field


@dataclass
class PbinEntry:
    """A single entry in a pBin container."""
    tag: str          # 4-char type tag (PLYT, PIMG, PANM, BIN )
    flags: int        # entry flags (2=ESDF text, 3=UI layout)
    offset: int       # data offset from start of pBin
    size: int         # data size
    name: str         # 16-byte name field

    @property
    def is_esdf_text(self) -> bool:
        """Check if this entry contains ESDF text data."""
        return self.tag == 'BIN ' and 'ESDF' in self.name

    @property
    def is_layout(self) -> bool:
        return self.tag == 'PLYT'

    @property
    def is_image(self) -> bool:
        return self.tag == 'PIMG'

    @property
    def is_animation(self) -> bool:
        return self.tag == 'PANM'


@dataclass
class PbinFile:
    """Represents a parsed pBin container file."""
    entries: List[PbinEntry] = field(default_factory=list)
    raw_data: bytes = b''
    file_id: str = ''

    @property
    def esdf_entry(self) -> Optional[PbinEntry]:
        """Get the ESDF text entry if present."""
        for e in self.entries:
            if e.is_esdf_text:
                return e
        return None

    @property
    def layout_entry(self) -> Optional[PbinEntry]:
        for e in self.entries:
            if e.is_layout:
                return e
        return None


def parse_pbin(data: bytes, file_id: str = '') -> PbinFile:
    """
    Parse a pBin container file.
    
    Format:
    - Bytes 0-3: 'pBin' signature
    - Bytes 4-5: major version (LE) 
    - Bytes 6-7: minor version (LE)
    - Bytes 8-11: info_offset (usually 1)
    - Bytes 12-15: info_size (usually 0)
    - Bytes 16-19: entry_count
    - Bytes 20-23: unk1 (2 or 3)
    - Bytes 24-27: data_start_offset
    - Bytes 28-31: unk2 (56 or 72)
    - Bytes 32+: entries (32 bytes each)
    
    Each entry (32 bytes):
    - Bytes 0-3: tag (4 ASCII chars)
    - Bytes 4-7: flags/type
    - Bytes 8-11: data offset (from start of pBin)
    - Bytes 12-15: data size
    - Bytes 16-31: name (null-padded, 16 bytes)
    """
    result = PbinFile(raw_data=data, file_id=file_id)

    if data[:4] != b'pBin':
        return result  # Not a pBin file

    count = struct.unpack('<I', data[16:20])[0]
    pos = 32

    for i in range(count):
        if pos + 32 > len(data):
            break

        tag = data[pos:pos+4].decode('ascii', errors='replace')
        flags = struct.unpack('<I', data[pos+4:pos+8])[0]
        offset = struct.unpack('<I', data[pos+8:pos+12])[0]
        size = struct.unpack('<I', data[pos+12:pos+16])[0]
        name_raw = data[pos+16:pos+32]
        name = name_raw.rstrip(b'\x00').decode('ascii', errors='replace')

        # Sanity check
        if 0 < offset < len(data) and size <= len(data) - offset:
            entry = PbinEntry(tag=tag, flags=flags, offset=offset,
                              size=size, name=name)
            result.entries.append(entry)
        elif offset == 0xFFFFFFFF and size == 0xFFFFFFFF:
            # Sentinel entry (end marker)
            pass

        pos += 32

    return result


def build_pbin(entries: List[Tuple[str, int, bytes, str]]) -> bytes:
    """
    Build a pBin container from entries.
    
    Args:
        entries: List of (tag, flags, data, name) tuples
    
    Returns:
        Complete pBin file as bytes
    """
    # Build pBin header
    header_size = 32 + len(entries) * 32
    # Align data start
    data_start = (header_size + 0x7F) & ~0x7F  # Align to 128

    # Build entry table
    entry_table = b''
    current_offset = data_start
    for tag, flags, data, name in entries:
        entry_table += tag.encode('ascii', errors='replace').ljust(4, b' ')
        entry_table += struct.pack('<I', flags)
        entry_table += struct.pack('<I', current_offset)
        entry_table += struct.pack('<I', len(data))
        if isinstance(name, bytes):
            name_bytes = name.ljust(16, b'\x00')[:16]
        else:
            name_bytes = name.encode('ascii', errors='replace').ljust(16, b'\x00')[:16]
        entry_table += name_bytes
        current_offset += len(data)

    # Build pBin header
    header = b'pBin'
    header += struct.pack('<H', 1)  # major version
    header += struct.pack('<H', 0)  # minor version
    header += struct.pack('<I', 1)  # info_offset
    header += struct.pack('<I', 0)  # info_size
    header += struct.pack('<I', len(entries))
    header += struct.pack('<I', 2)  # unk1
    header += struct.pack('<I', data_start)
    header += struct.pack('<I', 56)  # unk2

    # Pad to data_start
    raw = header + entry_table
    raw += b'\x00' * (data_start - len(raw))

    # Append data
    for _, _, d, _ in entries:
        raw += d

    return raw
