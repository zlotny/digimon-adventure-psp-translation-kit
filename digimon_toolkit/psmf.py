"""
PSMF (PSP Movie Format) demuxer — Digimon Adventure PSP.

Cutscenes in the CPK are Sony PSMF containers (magic "PSMF", e.g. "PSMF0015"),
not CRI Sofdec. The payload after the header is a standard MPEG Program
Stream: video is PES stream_id 0xE0 (H.264), which ffmpeg's generic "mpeg"
demuxer reads natively. Audio is PES stream_id 0xBD (private_stream_1,
ATRAC3+) — ffmpeg's generic demuxer never surfaces this as a stream, since
the sub-header/frame-wrapping convention is PSP-specific, not a DVD-style
private-stream layout ffmpeg knows about. Demuxing it needs two passes:

1. PES layer — after the standard MPEG-PS PES optional header, each 0xBD
   packet has a 1-byte channel id followed by a 3- or 4-byte sub-header
   (4 if channel is 0xB0-0xBF) before the payload proper. Format and byte
   count confirmed against PPSSPP's own working demuxer
   (Core/HW/MpegDemux.cpp, readPesHeader).
2. Frame layer — concatenating those payloads yields a stream of
   PSP-specific audio frame wrappers, each: 2-byte sync word (0x0F 0xD0) +
   2 code bytes encoding the wrapper's total size + 4 more bytes, then the
   raw ATRAC3+ frame itself. Wrapper size = (((code1&3)<<8) | code2*8) + 16;
   the actual codec frame is wrapper[8:] (confirmed against PPSSPP's
   MpegDemux::hasNextAudioFrame/getNextAudioFrame — same file).

The concatenated raw ATRAC3+ frames are wrapped in a minimal synthetic
Sony OMA (.oma) header so ffmpeg's built-in (non-proprietary, decode-only)
atrac3plus decoder can read them — see EA3_HEADER_SIZE/OMA_CODECID_ATRAC3P
in FFmpeg's libavformat/oma.h and omadec.c for the field layout. Every PSP
movie uses 44.1kHz stereo ATRAC3+ (PPSSPP hardcodes this in
Core/HW/MediaEngine.cpp — PSP_CODEC_AT3PLUS, no per-file codec detection).

Header layout (confirmed against this game's files):
  +0x00  signature    4 bytes  "PSMF"
  +0x04  version      4 bytes  ASCII digits, e.g. "0015"
  +0x08  data_offset  u32 BE   byte offset where the MPEG-PS payload starts
"""
import os
import struct
import subprocess
import tempfile

PSMF_SIG = b'PSMF'

_ATRAC3P_SYNC = b'\x0f\xd0'
_OMA_CHANNEL_ID_STEREO = 2
_OMA_SRATE_IDX_44100 = 1


def is_psmf(data: bytes) -> bool:
    return data[:4] == PSMF_SIG


def psmf_data_offset(data: bytes) -> int:
    return struct.unpack('>I', data[8:12])[0]


def _find_bd_regions(body: bytes):
    """Return [(audio_start, payload_end), ...] absolute byte ranges (into
    `body`) for every 0xBD (private_stream_1) PES packet's audio payload,
    stripping the standard PES header and the PSP audio channel sub-header."""
    n = len(body)
    i = 0
    regions = []
    while i < n - 9:
        if body[i] == 0 and body[i + 1] == 0 and body[i + 2] == 1 and body[i + 3] == 0xbd:
            pes_len = (body[i + 4] << 8) | body[i + 5]
            hdr_data_len = body[i + 8]
            payload_start = i + 9 + hdr_data_len
            payload_end = i + 6 + pes_len
            if payload_start >= payload_end or payload_end > n:
                i += 1
                continue
            channel = body[payload_start]
            sub_header = 4 if 0xb0 <= channel <= 0xbf else 3
            audio_start = payload_start + 1 + sub_header
            regions.append((audio_start, payload_end))
            i = payload_end
        else:
            i += 1
    return regions


def _extract_private_stream_1(body: bytes) -> bytes:
    """Concatenate the payload of every 0xBD (private_stream_1) PES packet."""
    return b''.join(body[s:e] for s, e in _find_bd_regions(body))


def _read_wav_atrac3p_frames(riff_bytes: bytes):
    """Parse a RIFF/ATRAC3+ WAV (plain, no PSP frame wrapper — the format
    external encoders like at3tool produce). Returns (frames, block_align)."""
    if riff_bytes[:4] != b'RIFF' or riff_bytes[8:12] != b'WAVE':
        raise ValueError("not a RIFF/WAVE file")
    pos = 12
    fmt = audio = None
    n = len(riff_bytes)
    while pos < n - 8:
        cid = riff_bytes[pos:pos + 4]
        csz = int.from_bytes(riff_bytes[pos + 4:pos + 8], 'little')
        body = riff_bytes[pos + 8:pos + 8 + csz]
        if cid == b'fmt ':
            fmt = body
        if cid == b'data':
            audio = body
        pos += 8 + csz + (csz % 2)
    if fmt is None or audio is None:
        raise ValueError("missing fmt or data chunk")
    block_align = struct.unpack('<H', fmt[12:14])[0]
    if len(audio) % block_align != 0:
        raise ValueError(f"data chunk ({len(audio)} bytes) isn't a whole number of {block_align}-byte frames")
    n_frames = len(audio) // block_align
    frames = [audio[i * block_align:(i + 1) * block_align] for i in range(n_frames)]
    return frames, block_align


def splice_audio_into_psmf(original: bytes, new_riff: bytes) -> bytes:
    """
    Replace a PSMF's audio with a new RIFF/ATRAC3+ track, keeping every
    other byte (video, pack/PES headers, timing) untouched. Rewraps the new
    track's raw frames in the PSP-specific 8-byte frame wrapper and refills
    the existing 0xBD PES packet regions in place, padding with zeros —
    the total file size never changes, so this drops straight into the
    CPK's existing fixed-size slot.

    Raises ValueError if the new audio doesn't fit the original's byte
    budget, or its frame size can't be expressed in the wrapper's size code
    (only same-size-as-original frames are supported — see module docstring;
    reusing the original's own code1/code2 bytes verbatim would be wrong for
    a different frame size).
    """
    if not is_psmf(original):
        raise ValueError("not a PSMF file")
    data_offset = psmf_data_offset(original)
    body = bytearray(original[data_offset:])

    regions = _find_bd_regions(bytes(body))
    if not regions:
        raise ValueError("original PSMF has no audio to replace")
    total_region_bytes = sum(e - s for s, e in regions)

    frames, block_align = _read_wav_atrac3p_frames(new_riff)
    wrapper_size = block_align + 8
    # Reuses this game's own fixed code1/code2 bytes, which only encode the
    # right wrapper size for 744-byte (752-byte wrapped) frames — the same
    # frame size every ATRAC3+ track in this game happens to use. A track
    # encoded at a different bitrate would need code1/code2 solved for its
    # own wrapper_size instead of assuming these constants.
    code1, code2 = 0x28, 0x5c
    if (((code1 & 0x03) << 8) | (code2 * 8)) + 0x10 != wrapper_size:
        raise ValueError(f"unsupported frame size {block_align} bytes (only 744-byte frames, "
                          f"this game's standard ATRAC3+ config, are supported)")
    wrapper = bytes([0x0f, 0xd0, code1, code2, 0, 0, 0, 0])
    new_es = b''.join(wrapper + f for f in frames)

    pad = total_region_bytes - len(new_es)
    if pad < 0:
        raise ValueError(f"new audio ({len(new_es)} bytes) exceeds original's budget ({total_region_bytes} bytes)")
    new_es = new_es + b'\x00' * pad

    pos = 0
    for start, end in regions:
        n = end - start
        body[start:end] = new_es[pos:pos + n]
        pos += n

    result = bytearray(original)
    result[data_offset:] = body
    return bytes(result)


def _extract_atrac3plus_frames(es: bytes):
    """
    Walk the PSP audio-frame-wrapper layer (sync word + size code) inside a
    concatenated private_stream_1 byte stream. Returns (payload, frame_size)
    where payload is the concatenated raw ATRAC3+ frames (wrapper stripped),
    or (None, None) if no valid frames are found.
    """
    n = len(es)
    pos = 0
    frames = []
    frame_size = None
    while pos + 4 <= n:
        if es[pos:pos + 2] != _ATRAC3P_SYNC:
            nxt = es.find(_ATRAC3P_SYNC, pos, min(pos + 2000, n))
            if nxt < 0:
                break
            pos = nxt
        code1, code2 = es[pos + 2], es[pos + 3]
        wrapper_size = (((code1 & 0x03) << 8) | (code2 * 8)) + 0x10
        if wrapper_size <= 8 or pos + wrapper_size > n:
            pos += 2
            continue
        frames.append(es[pos + 8:pos + wrapper_size])
        frame_size = wrapper_size - 8
        pos += wrapper_size
    if not frames:
        return None, None
    return b''.join(frames), frame_size


def _build_ea3_header(frame_size: int, channel_id: int = _OMA_CHANNEL_ID_STEREO,
                       srate_idx: int = _OMA_SRATE_IDX_44100) -> bytes:
    """Minimal 96-byte Sony EA3/OMA header wrapping raw ATRAC3+ frames, per
    FFmpeg's libavformat/oma.h + omadec.c (OMA_CODECID_ATRAC3P layout)."""
    field = (frame_size - 8) // 8
    if not (0 <= field <= 0x3FF):
        raise ValueError(f"frame_size {frame_size} out of encodable range")
    codec_params = (srate_idx << 13) | (channel_id << 10) | field
    hdr = bytearray(96)
    hdr[0:3] = b'EA3'
    hdr[5] = 96
    hdr[6:8] = struct.pack('>h', -1)  # eid = -1 → unencrypted
    hdr[32] = 1  # OMA_CODECID_ATRAC3P
    hdr[33:36] = codec_params.to_bytes(3, 'big')
    return bytes(hdr)


def extract_psmf_to_mp4(data: bytes, out_path: str) -> None:
    """
    Strip the PSMF header and remux the underlying video (+ audio, if
    successfully demuxed) into an MP4 at out_path. Video is always
    stream-copied losslessly; audio (ATRAC3+) is decoded and re-encoded to
    AAC since ATRAC3+ isn't a valid MP4 audio codec. Falls back to
    video-only if no audio track is found or it fails to decode.
    """
    if not is_psmf(data):
        raise ValueError("not a PSMF file")
    body = data[psmf_data_offset(data):]

    oma_path = None
    try:
        es = _extract_private_stream_1(body)
        payload, frame_size = _extract_atrac3plus_frames(es) if es else (None, None)
        if payload:
            ea3 = _build_ea3_header(frame_size)
            fd, oma_path = tempfile.mkstemp(suffix='.oma')
            with os.fdopen(fd, 'wb') as f:
                f.write(ea3)
                f.write(payload)
    except Exception:
        oma_path = None

    if oma_path:
        proc = subprocess.run(
            ['ffmpeg', '-y', '-f', 'mpeg', '-i', '-', '-i', oma_path,
             '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
             '-shortest', out_path],
            input=body, capture_output=True, timeout=120,
        )
        os.remove(oma_path)
        if proc.returncode == 0:
            return
        # Audio mux failed for some reason — fall back to video-only below
        # rather than losing the video too.

    proc = subprocess.run(
        ['ffmpeg', '-y', '-f', 'mpeg', '-i', '-', '-c', 'copy', out_path],
        input=body, capture_output=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode('utf-8', errors='replace')[-500:])
