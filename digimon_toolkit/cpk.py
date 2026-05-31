"""
CRI CPK Archive Reader/Writer for PSP games.
Supports extracting, listing, and repacking CPK archives.
Based on CriPakTools by esperknight.
"""
import struct
import os
from typing import List, Dict, Optional, BinaryIO, Any
from dataclasses import dataclass, field
try:
    from .utf import UTFTable, parse_utf_table
except ImportError:
    from utf import UTFTable, parse_utf_table


@dataclass
class CPKFileEntry:
    """Represents a single file within the CPK archive."""
    dir_name: Optional[str] = None
    file_name: Optional[str] = None
    file_offset: int = 0
    file_size: int = 0
    extract_size: Optional[int] = None
    file_offset_pos: int = 0
    file_size_pos: int = 0
    extract_size_pos: int = 0
    file_offset_type: str = 'U64'
    file_size_type: str = 'U64'
    user_string: Optional[str] = None
    file_id: Optional[int] = None
    toc_name: str = 'TOC'

    @property
    def full_path(self) -> str:
        parts = []
        if self.dir_name:
            parts.append(self.dir_name)
        if self.file_name:
            parts.append(str(self.file_name))
        return '/'.join(parts)


class CPKArchive:
    """Read and write CRI CPK archives."""

    # CPK XOR encryption parameters
    XOR_M = 0x0000655f
    XOR_T = 0x00004115

    def __init__(self, filepath: str = None):
        self.filepath = filepath
        self.files: List[CPKFileEntry] = []
        self.content_offset: int = 0
        self.align: int = 2048
        self.total_files: int = 0

        # Raw packet data for rewriting
        self.cpk_packet: bytes = b''
        self.toc_packet: bytes = b''
        self.itoc_packet: bytes = b''
        self.etoc_packet: bytes = b''
        self.gtoc_packet: bytes = b''

        self.toc_encrypted: bool = False
        self.itoc_encrypted: bool = False
        self.toc_offset: int = 0
        self.itoc_offset: int = 0
        self.etoc_offset: int = 0
        self.gtoc_offset: int = 0

    @staticmethod
    def _decrypt_utf(encrypted: bytes) -> bytes:
        """XOR-decrypt @UTF data using CriPakTools algorithm."""
        result = bytearray(len(encrypted))
        m = CPKArchive.XOR_M
        t = CPKArchive.XOR_T
        # Use signed 32-bit arithmetic matching C#
        for i in range(len(encrypted)):
            m_signed = m if m < 0x80000000 else m - 0x100000000
            d = encrypted[i] ^ (m_signed & 0xff)
            result[i] = d
            m = (m * t) & 0xFFFFFFFF
        return bytes(result)

    @staticmethod
    def _encrypt_utf(plaintext: bytes) -> bytes:
        """XOR-encrypt @UTF data (same algorithm, XOR is reversible)."""
        return CPKArchive._decrypt_utf(plaintext)  # XOR is its own inverse

    def _read_utf_packet(self, data: bytes, offset: int) -> bytes:
        """Read a UTF packet from the CPK at the given offset.
        Returns decrypted @UTF data. Also returns whether it was encrypted."""
        packet_sig = data[offset:offset+4].decode('ascii', errors='replace')
        unk1 = struct.unpack('<i', data[offset+4:offset+8])[0]
        utf_size = struct.unpack('<Q', data[offset+8:offset+16])[0]
        utf_packet = data[offset+16:offset+16+utf_size]

        # Check if encrypted
        if utf_packet[:4] != b'@UTF':
            utf_packet = self._decrypt_utf(utf_packet)

        return utf_packet, unk1, utf_size

    def load(self, filepath: str = None) -> None:
        """Load and parse a CPK archive."""
        if filepath:
            self.filepath = filepath

        with open(self.filepath, 'rb') as f:
            data = f.read()

        # Parse CPK header
        sig = data[0:4]
        if sig != b'CPK ':
            raise ValueError(f"Not a valid CPK file: {sig!r}")

        # Read CPK-level UTF (header metadata)
        cpk_utf, cpk_unk1, cpk_utf_size = self._read_utf_packet(data, 0)

        # Parse CPK header @UTF
        cpk_table = UTFTable.parse(cpk_utf, base_offset=16)
        row0 = cpk_table.get_row(0, cpk_utf)

        self.content_offset = row0.get('ContentOffset', 0)
        self.align = row0.get('Align', 2048)
        self.total_files = row0.get('Files', 0)

        def _safe_int(v, default=0xFFFFFFFFFFFFFFFF):
            if v is None:
                return default
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        self.toc_offset = _safe_int(row0.get('TocOffset'))
        self.itoc_offset = _safe_int(row0.get('ItocOffset'))
        self.etoc_offset = _safe_int(row0.get('EtocOffset'))
        self.gtoc_offset = _safe_int(row0.get('GtocOffset'))
        self.cpk_packet = cpk_utf

        # Determine add_offset for TOC (same as CriPakTools)
        add_offset = 0
        if self.toc_offset != 0xFFFFFFFFFFFFFFFF and self.toc_offset < self.content_offset:
            add_offset = self.toc_offset
        else:
            add_offset = self.content_offset

        # Read TOC if present
        if self.toc_offset != 0xFFFFFFFFFFFFFFFF:
            self._read_toc(data, self.toc_offset, add_offset)

        # Read ITOC if present
        if self.itoc_offset != 0xFFFFFFFFFFFFFFFF:
            self._read_itoc(data, self.itoc_offset)

        # Read ETOC if present
        if self.etoc_offset != 0xFFFFFFFFFFFFFFFF:
            self._read_etoc(data, self.etoc_offset)

    def _read_toc(self, data: bytes, toc_offset: int, add_offset: int) -> None:
        """Read the TOC (Table of Contents) section."""
        toc_utf, unk1, utf_size = self._read_utf_packet(data, toc_offset)
        self.toc_packet = toc_utf

        table = UTFTable.parse(toc_utf, base_offset=toc_offset + 16)

        for row_idx in range(table.num_rows):
            row = table.get_row(row_idx, toc_utf)
            entry = CPKFileEntry()
            entry.toc_name = 'TOC'
            entry.dir_name = row.get('DirName', None)
            entry.file_name = row.get('FileName', None)
            entry.file_size = int(row.get('FileSize', 0))
            entry.extract_size = int(row.get('ExtractSize', 0)) if row.get('ExtractSize') else None
            entry.file_offset = int(row.get('FileOffset', 0)) + add_offset
            entry.file_id = int(row.get('ID', 0)) if row.get('ID') else None
            entry.user_string = row.get('UserString', None)
            self.files.append(entry)

    def _read_itoc(self, data: bytes, itoc_offset: int) -> None:
        """Read the ITOC (Index TOC) section."""
        itoc_utf, unk1, utf_size = self._read_utf_packet(data, itoc_offset)
        self.itoc_packet = itoc_utf

        table = UTFTable.parse(itoc_utf, base_offset=itoc_offset + 16)

        # Get DataL and DataH columns
        for row_idx in range(table.num_rows):
            row = table.get_row(row_idx, itoc_utf)

        # Find the DataL and DataH columns
        data_l_col = None
        data_h_col = None
        for col in table.columns:
            if col.name == 'DataL' and col.is_perrow:
                data_l_col = col
            elif col.name == 'DataH' and col.is_perrow:
                data_h_col = col

        # DataL and DataH contain sub-UTF tables with file size info
        row0 = table.get_row(0, itoc_utf)
        data_l_raw = row0.get('DataL')
        data_h_raw = row0.get('DataH')

        # Parse sub-tables from DataL
        base = itoc_offset + 16
        sub_tables = {}

        if data_l_raw and len(data_l_raw) > 0:
            sub_table = UTFTable.parse(data_l_raw, base_offset=base)
            for r_idx in range(sub_table.num_rows):
                sr = sub_table.get_row(r_idx, data_l_raw)
                fid = sr.get('ID', r_idx)
                fsize = sr.get('FileSize', 0)
                sub_tables[int(fid)] = {
                    'file_size': fsize,
                    'extract_size': sr.get('ExtractSize', fsize),
                }

        if data_h_raw and len(data_h_raw) > 0:
            sub_table = UTFTable.parse(data_h_raw, base_offset=base)
            for r_idx in range(sub_table.num_rows):
                sr = sub_table.get_row(r_idx, data_h_raw)
                fid = sr.get('ID', r_idx)
                fsize = sr.get('FileSize', 0)
                if int(fid) not in sub_tables:
                    sub_tables[int(fid)] = {}
                sub_tables[int(fid)]['file_size'] = fsize
                sub_tables[int(fid)]['extract_size'] = sr.get('ExtractSize', fsize)

        # Build file entries from ITOC
        # Files are stored sequentially after content_offset
        current_offset = self.content_offset
        for idx in sorted(sub_tables.keys()):
            info = sub_tables[idx]
            entry = CPKFileEntry()
            entry.toc_name = 'ITOC'
            entry.file_name = f"{idx:04d}"
            entry.file_id = idx
            entry.file_size = info.get('file_size', 0)
            entry.extract_size = info.get('extract_size', entry.file_size)
            entry.file_offset = current_offset
            self.files.append(entry)

            # Advance offset with alignment
            if entry.file_size > 0:
                current_offset += entry.file_size
                if current_offset % self.align > 0:
                    current_offset += self.align - (current_offset % self.align)

    def _read_etoc(self, data: bytes, etoc_offset: int) -> None:
        """Read the ETOC (Extended TOC) section - provides LocalDir for files."""
        etoc_utf, unk1, utf_size = self._read_utf_packet(data, etoc_offset)
        self.etoc_packet = etoc_utf

        table = UTFTable.parse(etoc_utf, base_offset=etoc_offset + 16)

        for row_idx in range(min(table.num_rows, len(self.files))):
            row = table.get_row(row_idx, etoc_utf)
            local_dir = row.get('LocalDir', None)
            if local_dir and row_idx < len(self.files):
                self.files[row_idx].dir_name = local_dir

    def extract_file(self, data: bytes, entry: CPKFileEntry) -> bytes:
        """Extract a single file from the CPK data."""
        if entry.file_offset >= len(data):
            raise ValueError(f"File offset {entry.file_offset} beyond data size {len(data)}")

        chunk = data[entry.file_offset:entry.file_offset + entry.file_size]

        # Check for CRILAYLA compression
        if chunk[:8] == b'CRILAYLA':
            chunk = self._decompress_crilayla(chunk, entry.extract_size or entry.file_size)

        return chunk

    def _decompress_crilayla(self, compressed: bytes, uncompressed_size: int) -> bytes:
        """Decompress CRILAYLA-compressed data."""
        # Skip "CRILAYLA" header (8 bytes)
        us = struct.unpack('>I', compressed[8:12])[0]
        header_offset = struct.unpack('>I', compressed[12:16])[0]

        result = bytearray(uncompressed_size + 0x100)

        # Copy uncompressed 0x100 header
        src_start = header_offset + 0x10
        result[:0x100] = compressed[src_start:src_start + 0x100]

        input_end = len(compressed) - 0x100 - 1
        input_offset = input_end
        output_end = 0x100 + uncompressed_size - 1
        bit_pool = 0
        bits_left = 0
        bytes_output = 0
        vle_lens = [2, 3, 5, 8]

        def get_next_bits(bit_count):
            nonlocal input_offset, bit_pool, bits_left
            out_bits = 0
            num_bits_produced = 0

            while num_bits_produced < bit_count:
                if bits_left == 0:
                    bit_pool = compressed[input_offset]
                    bits_left = 8
                    input_offset -= 1

                bits_this_round = min(bit_count - num_bits_produced, bits_left)
                out_bits <<= bits_this_round
                out_bits |= (bit_pool >> (bits_left - bits_this_round)) & ((1 << bits_this_round) - 1)
                bits_left -= bits_this_round
                num_bits_produced += bits_this_round

            return out_bits

        while bytes_output < uncompressed_size:
            if get_next_bits(1) > 0:
                backreference_offset = output_end - bytes_output + get_next_bits(13) + 3
                backreference_length = 3

                for vle_level in range(len(vle_lens)):
                    this_level = get_next_bits(vle_lens[vle_level])
                    backreference_length += this_level
                    if this_level != (1 << vle_lens[vle_level]) - 1:
                        break
                else:
                    while True:
                        this_level = get_next_bits(8)
                        backreference_length += this_level
                        if this_level != 255:
                            break

                for i in range(backreference_length):
                    result[output_end - bytes_output] = result[backreference_offset]
                    backreference_offset -= 1
                    bytes_output += 1
            else:
                result[output_end - bytes_output] = get_next_bits(8) & 0xFF
                bytes_output += 1

        return bytes(result[:uncompressed_size + 0x100])

    def extract_all(self, output_dir: str) -> None:
        """Extract all files from the CPK archive."""
        with open(self.filepath, 'rb') as f:
            data = f.read()

        os.makedirs(output_dir, exist_ok=True)

        for entry in self.files:
            if entry.toc_name != 'FILE' and entry.toc_name != 'ITOC' and entry.toc_name != 'TOC':
                continue

            if not entry.file_name or entry.file_size == 0:
                continue

            # Build output path
            rel_path = []
            if entry.dir_name and entry.dir_name != '':
                rel_path.append(entry.dir_name)
            rel_path.append(str(entry.file_name))
            out_path = os.path.join(output_dir, *rel_path)

            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            try:
                chunk = self.extract_file(data, entry)
                with open(out_path, 'wb') as f_out:
                    f_out.write(chunk)
                print(f"  Extracted: {entry.full_path} ({len(chunk)} bytes)")
            except Exception as e:
                print(f"  Failed: {entry.full_path}: {e}")

    def list_files(self) -> List[CPKFileEntry]:
        """List all files in the archive."""
        return self.files
