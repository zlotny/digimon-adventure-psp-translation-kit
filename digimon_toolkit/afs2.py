"""
AFS2/AWB (CRI Atom Wave Bank) reader — Digimon Adventure PSP.

BGM tracks in the CPK are stored inside AFS2 archives: a flat table of
(track_id -> byte range) followed by the tracks themselves, each a
self-contained RIFF file wrapping raw ATRAC3+ frames (same codec/framing
convention as PSMF audio, but without the PSP movie-specific 8-byte frame
wrapper — this is the "plain" Sony WAVE-for-ATRAC3+ format, decodable by
ffmpeg directly).

Header layout confirmed against FFmpeg's vgmstream reference reader
(src/meta/awb.c, https://github.com/vgmstream/vgmstream):
  +0x00  signature          4 bytes  "AFS2"
  +0x04  version            u8
  +0x05  offset_size        u8       byte width of each offset table entry (4 or 2)
  +0x06  waveid_alignment   u16 LE   byte width of each id table entry (usually 2)
  +0x08  total_subsongs     s32 LE
  +0x0C  offset_alignment   u16 LE   offsets are rounded up to this boundary
  +0x0E  subkey             u16 LE
  +0x10  id table           total_subsongs * waveid_alignment bytes
  ...    offset table       (total_subsongs + 1) * offset_size bytes
                             (last entry = end of the last track)

Some tracks carry a 'smpl' RIFF chunk with an explicit loop (start/end
sample, not necessarily sample 0) — see loop_points().
"""
import struct
import subprocess

AFS2_SIG = b'AFS2'


def is_afs2(data: bytes) -> bool:
    return data[:4] == AFS2_SIG


def parse_afs2(data: bytes):
    """Return [{'id', 'start', 'end', 'size'}, ...] for every track."""
    offset_size = data[5]
    waveid_alignment = struct.unpack('<H', data[6:8])[0]
    total_subsongs = struct.unpack('<i', data[8:12])[0]
    offset_alignment = struct.unpack('<H', data[12:14])[0]

    pos = 0x10
    ids = []
    for _ in range(total_subsongs):
        ids.append(struct.unpack('<H', data[pos:pos + waveid_alignment])[0])
        pos += waveid_alignment

    offsets = []
    for _ in range(total_subsongs + 1):
        if offset_size == 4:
            off = struct.unpack('<I', data[pos:pos + 4])[0]
        else:
            off = struct.unpack('<H', data[pos:pos + 2])[0]
        offsets.append(off)
        pos += offset_size

    def align(v):
        rem = v % offset_alignment
        return v + (offset_alignment - rem) if rem else v

    entries = []
    for i in range(total_subsongs):
        start = align(offsets[i])
        end = align(offsets[i + 1])
        entries.append({'id': ids[i], 'start': start, 'end': end, 'size': end - start})
    return entries


def extract_track(data: bytes, track_id: int) -> bytes:
    """Return the raw RIFF/ATRAC3+ bytes for one track."""
    for e in parse_afs2(data):
        if e['id'] == track_id:
            return data[e['start']:e['end']]
    raise ValueError(f"track id {track_id} not found")


def splice_track_into_archive(archive: bytes, track_id: int, new_riff: bytes) -> bytes:
    """
    Replace one track's bytes within an AFS2 archive, padding with zeros to
    exactly fill its original slot (RIFF/WAVE parsers stop at the chunk
    sizes they declare, so trailing zero padding within the slot is always
    safe — the same trick this game's own archive already uses). Leaves the
    offset table and every other track untouched.

    Raises ValueError if the new content is bigger than the original slot —
    that needs the archive's offset table rebuilt (to grow this slot and
    shift every later track), which this does not attempt.
    """
    entries = parse_afs2(archive)
    target = next((e for e in entries if e['id'] == track_id), None)
    if target is None:
        raise ValueError(f"track id {track_id} not found")

    slot_size = target['size']
    if len(new_riff) > slot_size:
        raise ValueError(f"new track ({len(new_riff)} bytes) exceeds its slot ({slot_size} bytes) — "
                          f"needs the archive resized, not supported")
    padded = new_riff + b'\x00' * (slot_size - len(new_riff))

    result = bytearray(archive)
    result[target['start']:target['end']] = padded
    return bytes(result)


def loop_points(riff_bytes: bytes):
    """Return (start_sample, end_sample) from a 'smpl' chunk, or None."""
    pos = 12
    n = len(riff_bytes)
    while pos < n - 8:
        cid = riff_bytes[pos:pos + 4]
        csz = int.from_bytes(riff_bytes[pos + 4:pos + 8], 'little')
        if cid == b'smpl' and csz >= 60:
            body = riff_bytes[pos + 8:pos + 8 + csz]
            start, end = struct.unpack('<2I', body[44:52])
            return start, end
        pos += 8 + csz + (csz % 2)
    return None


def decode_riff_to_wav(riff_bytes: bytes, out_path: str) -> None:
    """Decode a RIFF/ATRAC3+ track to plain PCM WAV via ffmpeg."""
    proc = subprocess.run(
        ['ffmpeg', '-y', '-i', '-', out_path],
        input=riff_bytes, capture_output=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode('utf-8', errors='replace')[-500:])
