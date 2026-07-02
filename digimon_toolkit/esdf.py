"""
ESDF Text Format Parser for Digimon Adventure PSP.
ESDF is CRI's text format used for dialog and UI text.
"""
import struct
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field


@dataclass
class ESDFTextEntry:
    """A single text entry from an ESDF block."""
    index: int
    text: str
    offset: int = 0
    length: int = 0
    raw_bytes: Optional[bytes] = None
    speaker_id: int = 0  # speaker group ID from binary record table (0 = narrator/unknown)


@dataclass
class ESDFTextBlock:
    """Parsed ESDF text block with all entries."""
    entries: List[ESDFTextEntry] = field(default_factory=list)
    raw_data: bytes = b''

    @property
    def text_count(self) -> int:
        return len(self.entries)


def _extract_speaker_ids(esdf_data: bytes, text_start: int, entries: List[ESDFTextEntry]) -> None:
    """
    Assign speaker_id to each entry by reading the main speaker record table.

    Record table layout (32 bytes per record):
      [+5:+9]  0xFF 0xFF 0xFF 0xFF  — always 0xFF in both extra and parsed records
      [+13]    speaker group ID (1 byte)  <- what we want
      [+28]    0xFF in extra (pre-English) records; 0x00 in parsed (English) records

    The table starts with some "extra" records for pre-text strings (Japanese dialog,
    timing cues, etc.); then the parsed-entry records follow. We find the boundary
    between the two by looking for the first record with +28 == 0x00.

    To locate the table: scan forward at 32-byte-aligned positions for the first
    position with +5..+8 == 0xFF (start of extra-record block), then walk until
    +28 flips from 0xFF to 0x00.
    """
    n = len(entries)
    if n == 0:
        return

    record_size = 32

    # Find the start of the extra-records block: first 32-byte-aligned position
    # (starting from offset 0) where bytes +5..+8 are all 0xFF.
    extra_start = -1
    for pos in range(0, text_start - record_size + 1, record_size):
        d = esdf_data
        if (d[pos + 5] == 0xFF and d[pos + 6] == 0xFF and
                d[pos + 7] == 0xFF and d[pos + 8] == 0xFF):
            extra_start = pos
            break

    if extra_start < 0:
        return

    # Walk forward from extra_start to find the first parsed record (+28 == 0x00).
    base_record = -1
    pos = extra_start
    while pos + record_size <= text_start:
        if esdf_data[pos + 28] == 0x00:
            base_record = pos
            break
        pos += record_size

    if base_record < 0:
        return

    # Walk the text region counting ALL strings with len >= 2 (valid + filtered).
    # Filtered strings ('...', single words, etc.) still have a record in the table.
    # We build a map: byte-offset of string → its sequential index in the ALL-strings
    # count, so we can find the exact record for each parsed entry.
    entry_by_offset = {e.offset: e for e in entries}
    all_count = 0  # index into the record table (past base_record)
    remaining = len(entries)

    pos = text_start
    while pos < len(esdf_data) and remaining > 0:
        null_end = esdf_data.find(b'\x00', pos)
        if null_end == -1 or null_end == pos:
            pos += 1
            continue
        if null_end - pos < 2:
            pos = null_end + 1
            continue
        # This string has a record at base_record + all_count * record_size
        if pos in entry_by_offset:
            rec = base_record + all_count * record_size
            if rec + 14 <= len(esdf_data):
                entry_by_offset[pos].speaker_id = esdf_data[rec + 13]
            remaining -= 1
        all_count += 1
        pos = null_end + 1


def extract_esdf_bin(data: bytes) -> Optional[bytes]:
    """Extract BIN ESDF data from a pBin container."""
    count = struct.unpack('<I', data[16:20])[0]
    pos = 32
    for i in range(count):
        if pos + 32 > len(data):
            break
        tag = data[pos:pos+4]
        off = struct.unpack('<I', data[pos+8:pos+12])[0]
        sz = struct.unpack('<I', data[pos+12:pos+16])[0]
        name = data[pos+16:pos+32]
        if tag == b'BIN ' and b'ESDF' in name:
            if 0 < off < len(data) and sz <= len(data) - off:
                return data[off:off+sz]
        pos += 32
    return None


def parse_english_esdf_texts(data: bytes) -> ESDFTextBlock:
    """
    Parse English text from ESDF block by finding all meaningful 
    null-terminated ASCII strings.
    
    The ESDF block has:
    - 0x0000-0x23xx: Binary record table (skip)
    - 0x2400+: English text strings (null-terminated)
    
    We auto-detect the text region boundary by looking for 
    a cluster of readable ASCII strings.
    """
    result = ESDFTextBlock()
    result.raw_data = data
    
    # Find where the English text region starts
    # Look for the first occurrence of "During" or a cluster of long text
    text_start = 0
    for i in range(0, min(len(data) - 80, 0x4000)):
        chunk = data[i:i+60]
        # Check if this could be the start of a long English string
        readable = sum(1 for b in chunk if 0x20 <= b < 0x7f or b == 0x0A)
        null_term = data.find(b'\x00', i, i+80)
        if readable > 30 and null_term > i + 20:
            # Found start of text region
            text_start = i
            break
    
    # Collect all null-terminated strings from text region
    pos = text_start
    index = 0
    while pos < len(data):
        null_end = data.find(b'\x00', pos)
        if null_end == -1 or null_end == pos:
            pos += 1
            continue
        
        chunk = data[pos:null_end]
        if len(chunk) < 2:
            pos = null_end + 1
            continue
        
        try:
            text = chunk.decode('shift-jis', errors='replace')
            text = text.strip()
            
            # Filter: must have enough alphabetic characters
            letters = sum(1 for c in text if c.isalpha())
            if letters >= 2 and len(text) >= 2:
                entry = ESDFTextEntry(
                    index=index,
                    text=text,
                    offset=pos,
                    length=len(chunk),
                    raw_bytes=data[pos:null_end+1]
                )
                result.entries.append(entry)
                index += 1
        except:
            pass
        
        pos = null_end + 1

    _extract_speaker_ids(data, text_start, result.entries)
    return result


def parse_japanese_esdf_texts(data: bytes) -> ESDFTextBlock:
    """
    Parse Japanese text from ESDF block.
    
    Japanese ESDF has:
    - 8-byte tag records (0xB3, 0xB4, etc.)
    - Text region after the tag table containing Shift-JIS strings
    """
    result = ESDFTextBlock()
    result.raw_data = data
    
    pos = 0
    index = 0
    while pos < len(data):
        # Skip zeros, FF padding, and binary data
        if data[pos] == 0x00:
            pos += 1
            continue
        
        # Skip 0xFF padding blocks
        if data[pos] == 0xFF:
            # Check if it's a run of 0xFF
            ff_end = pos
            while ff_end < len(data) and data[ff_end] == 0xFF:
                ff_end += 1
            pos = ff_end
            continue
        
        null_end = data.find(b'\x00', pos)
        if null_end == -1 or null_end - pos > 1000:
            pos += 1
            continue
        
        if null_end > pos:
            chunk = data[pos:null_end]
            try:
                text = chunk.decode('shift-jis', errors='replace')
                text = text.strip()
                if len(text) >= 2:
                    entry = ESDFTextEntry(
                        index=index,
                        text=text,
                        offset=pos,
                        length=len(chunk),
                        raw_bytes=data[pos:null_end+1]
                    )
                    result.entries.append(entry)
                    index += 1
            except:
                pass
        
        pos = null_end + 1
    
    return result


def extract_text_from_file(filepath: str) -> Optional[ESDFTextBlock]:
    """Extract text from a file (pBin ESDF or raw)."""
    with open(filepath, 'rb') as f:
        data = f.read()
    
    esdf_data = extract_esdf_bin(data)
    if esdf_data:
        return parse_english_esdf_texts(esdf_data)
    
    return parse_english_esdf_texts(data)


def extract_text_from_raw(data: bytes) -> ESDFTextBlock:
    """Extract text from raw data."""
    return parse_english_esdf_texts(data)


def texts_to_json(texts: ESDFTextBlock, file_id: str,
                  jp_texts: Optional[ESDFTextBlock] = None) -> Dict:
    """
    Convert extracted texts to translation JSON format.
    """
    result = {
        "file_id": file_id,
        "text_count": texts.text_count,
        "dialog": []
    }
    
    max_count = max(texts.text_count, jp_texts.text_count if jp_texts else 0)
    
    for i in range(max_count):
        entry = {}
        if i < texts.text_count:
            entry["index"] = texts.entries[i].index
            entry["english"] = texts.entries[i].text
            entry["_offset"] = texts.entries[i].offset
            entry["_length"] = texts.entries[i].length
        
        if jp_texts and i < jp_texts.text_count:
            entry["japanese"] = jp_texts.entries[i].text
        
        if entry:
            entry["speaker_id"] = texts.entries[i].speaker_id if i < texts.text_count else 0
            entry["translation"] = ""
            result["dialog"].append(entry)
    
    return result


_SJIS_SYMBOLS = {
    '○': b'\x81\x9b',
    '×': b'\x81\x7e',
    '□': b'\x81\xa0',
}


def _encode_game_text(text: str) -> bytes:
    """Encode a translation string for the ESDF binary.
    Accent proxies are already single-byte ASCII at this point.
    SJIS symbols (○×□) become their 2-byte Shift-JIS sequences.
    Everything else encodes as Latin-1.
    """
    parts = []
    for ch in text:
        if ch in _SJIS_SYMBOLS:
            parts.append(_SJIS_SYMBOLS[ch])
        else:
            parts.append(ch.encode('latin-1', errors='replace'))
    return b''.join(parts)


def build_esdf_with_texts(original_esdf: bytes, new_texts: List[str],
                         parsed_block: Optional[ESDFTextBlock] = None) -> bytes:
    """
    Rebuild an ESDF block replacing text strings using their byte offsets.
    
    Args:
        original_esdf: The original ESDF binary data
        new_texts: List of replacement strings (same order as parsed entries)
        parsed_block: Pre-parsed text block (parsed again if None)
    """
    if parsed_block is None:
        parsed_block = parse_english_esdf_texts(original_esdf)
    
    result = bytearray(original_esdf)
    
    for i, entry in enumerate(parsed_block.entries):
        if i >= len(new_texts):
            break
        
        new_text = new_texts[i]
        old_offset = entry.offset
        old_length = entry.length
        
        if old_offset <= 0 or old_offset >= len(original_esdf):
            continue
        
        # Detect leading 0xFF bytes. The game has two records pointing into this
        # slot: one at old_offset and one at old_offset+skip. The 0xFF prefix is
        # preserved so the first record sees it (matching original behaviour).
        # We write the translation at old_offset+skip (past the 0xFF prefix).
        # Padding uses spaces instead of nulls when a 0xFF prefix is present:
        # null-padding moves the string terminator earlier, which causes the game's
        # sequential scanner to consume phantom record slots and shift all dialogs.
        skip = 0
        while skip < old_length and original_esdf[old_offset + skip] == 0xFF:
            skip += 1
        actual_offset = old_offset + skip
        actual_length = old_length - skip

        if actual_length <= 0:
            continue

        new_bytes = _encode_game_text(new_text)
        new_len = len(new_bytes)
        pad_byte = b' ' if skip > 0 else b'\x00'

        if new_len <= actual_length:
            result[actual_offset:actual_offset + new_len] = new_bytes
            if new_len < actual_length:
                result[actual_offset + new_len:actual_offset + actual_length] = pad_byte * (actual_length - new_len)
        else:
            result[actual_offset:actual_offset + actual_length] = new_bytes[:actual_length]
    
    return bytes(result)


def replace_text_in_pbin(pbin_data: bytes, new_texts: List[str]) -> bytes:
    """
    Replace text strings inside a pBin container's BIN ESDF entry.

    Also handles raw TXTD files (no pBin wrapper): detected by a 'TXTD'
    magic header, in which case text is patched directly via offsets.

    CRITICAL: Works in-place within the original pBin to preserve
    the exact binary layout. Only the ESDF text bytes are changed.
    The pBin header, entry table, and all other sub-resources remain
    bit-identical to the original.
    """
    if pbin_data[:4] == b'TXTD':
        return build_esdf_with_texts(pbin_data, new_texts)

    result = bytearray(pbin_data)
    
    # Find the BIN ESDF entry manually to avoid any parsing loss
    count = struct.unpack('<I', pbin_data[16:20])[0]
    pos = 32
    for i in range(count):
        if pos + 32 > len(pbin_data):
            break
        tag = pbin_data[pos:pos+4]
        off = struct.unpack('<I', pbin_data[pos+8:pos+12])[0]
        sz = struct.unpack('<I', pbin_data[pos+12:pos+16])[0]
        name = pbin_data[pos+16:pos+32]
        if tag == b'BIN ' and b'ESDF' in name:
            if 0 < off < len(pbin_data) and sz <= len(pbin_data) - off:
                esdf_data = pbin_data[off:off+sz]
                parsed_block = parse_english_esdf_texts(esdf_data)
                new_esdf = build_esdf_with_texts(esdf_data, new_texts, parsed_block)
                # Replace in-place (sizes match due to padding/truncation)
                result[off:off+sz] = new_esdf
        pos += 32
    
    return bytes(result)
