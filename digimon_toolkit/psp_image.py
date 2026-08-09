"""
PSP GIM Image Handler — Digimon Adventure PSP
==============================================

Implements the MIG.00.1PSP (GIM) format as used in CRI middleware PSP games.
Algorithm based on LibPSPThemes (GeofrontTeam) — verified against file 0156.

Block structure (16-byte header for all blocks):
  +0x00  block_type   u16
  +0x02  reserved     u16  = 0
  +0x04  block_size   u32  (total bytes from this header onwards)
  +0x08  next_block   u32  (offset from block start to next sibling; = block_size)
  +0x0C  data_offset  u32  (offset from block start to image-data-header)

Image-data-header (48 bytes, at block_start + data_offset):
  +0x00  structure_size   u16  = 0x30 (48)
  +0x02  reserved         u16
  +0x04  format           u16  (0=RGBA5650 1=RGBA5551 2=RGBA4444 3=RGBA8888 4=Index4 5=Index8)
  +0x06  pixel_order      u16  (0=linear 1=swizzled)
  +0x08  width            u16
  +0x0A  height           u16
  +0x0C  rsx_bpp          u16  (bits per pixel: 4, 8, 16, or 32)
  +0x0E  rsx_pitch_align  u16  (typically 16)
  +0x10  rsx_height_align u16  (typically 8)
  +0x12  unknown          u16  = 2
  +0x14  reserved         u32
  +0x18  next_index_block u32  (offset from header to index block; typically 48)
  +0x1C  frame_data_start u32  (offset from header to pixel data; typically 64)
  +0x20  frame_data_end   u32

Pixel data is at: image_data_header_start + frame_data_start

Palette block (type=5) uses the same image-data-header format with:
  format=3 (RGBA8888), width=n_colors, height=1, pixel_order=0 (never swizzled)

PSP swizzle (tile layout):
  tile_width  = 128 // rsx_bpp   pixels (= 32 for 4bpp, 16 for 8bpp)
  tile_height = 8                 rows
  Tiles are stored sequentially; within a tile, pixels are in row-major order.
  The swizzled data is read as a flat (over_w × over_h) array, then swap_tiles()
  remaps each pixel to its correct output position.

Index4 nibble order: high nibble = first pixel, low nibble = second pixel.
"""

import os
import re
import struct
from typing import Optional, List, Tuple, Dict, Any

GIM_SIG  = b'MIG.00.1PSP\x00'
BLK_PIX  = 0x04   # pixel data block
BLK_PAL  = 0x05   # palette block

FMT_RGBA5650 = 0
FMT_RGBA5551 = 1
FMT_RGBA4444 = 2
FMT_RGBA8888 = 3
FMT_INDEX4   = 4
FMT_INDEX8   = 5
FMT_INDEX16  = 6
FMT_INDEX32  = 7


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _overscan(value: int, tile: int) -> int:
    """Round value up to the next multiple of tile."""
    return value if value % tile == 0 else value + (tile - value % tile)


def _read_block_header(data: bytes, pos: int) -> Tuple[int, int, int, int]:
    """Read 16-byte block header. Returns (block_type, block_size, next_block, data_offset)."""
    if pos + 16 > len(data):
        return (0, 0, 0, 16)
    btype    = struct.unpack('<H', data[pos + 0:pos + 2])[0]
    bsize    = struct.unpack('<I', data[pos + 4:pos + 8])[0]
    next_blk = struct.unpack('<I', data[pos + 8:pos + 12])[0]
    doff     = struct.unpack('<I', data[pos + 12:pos + 16])[0]
    return (btype, bsize, next_blk, doff)


def _read_img_hdr(data: bytes, hdr_start: int) -> Optional[Dict[str, Any]]:
    """
    Read the 48-byte image-data-header at hdr_start.
    Returns dict with format, pixel_order, width, height, rsx_bpp,
    rsx_pitch_align, frame_data_start.
    Returns None if header is invalid.
    """
    if hdr_start + 48 > len(data):
        return None
    sz    = struct.unpack('<H', data[hdr_start + 0:hdr_start + 2])[0]
    if sz != 0x30:
        return None
    fmt   = struct.unpack('<H', data[hdr_start + 4:hdr_start + 6])[0]
    order = struct.unpack('<H', data[hdr_start + 6:hdr_start + 8])[0]
    w     = struct.unpack('<H', data[hdr_start + 8:hdr_start + 10])[0]
    h     = struct.unpack('<H', data[hdr_start + 10:hdr_start + 12])[0]
    bpp   = struct.unpack('<H', data[hdr_start + 12:hdr_start + 14])[0]
    pa    = struct.unpack('<H', data[hdr_start + 14:hdr_start + 16])[0]
    fds   = struct.unpack('<I', data[hdr_start + 28:hdr_start + 32])[0]
    fde   = struct.unpack('<I', data[hdr_start + 32:hdr_start + 36])[0]
    if w == 0 or h == 0 or bpp == 0:
        return None
    return {
        'format': fmt, 'pixel_order': order,
        'width': w, 'height': h, 'bpp': bpp,
        'pitch_align': pa if pa else 16,
        'frame_data_start': fds,
        'frame_data_end':   fde,
    }


# ─────────────────────────────────────────────────────────────
# Deswizzle / Reswizzle (LibPSPThemes swap_tiles algorithm)
# ─────────────────────────────────────────────────────────────

def _swap_tiles(flat: List[int], w: int, h: int, tile_w: int, tile_h: int) -> List[List[int]]:
    """
    Deswizzle: remap pixels from PSP tile layout to scanline order.

    flat      : pixel values read in row-major order from (over_w × over_h) swizzled data
    w, h      : actual output dimensions (unpadded)
    tile_w/h  : tile size in pixels (tile_w = 128//bpp, tile_h = 8)
    """
    over_w = _overscan(w, tile_w)
    over_h = _overscan(h, tile_h)

    out = [[0] * w for _ in range(h)]
    tile_origin_x = tile_origin_y = tile_pos = 0

    for y in range(over_h):
        for x in range(over_w):
            d_x = tile_origin_x + (tile_pos % tile_w)
            d_y = tile_origin_y + (tile_pos // tile_w)
            if d_x < w and d_y < h:
                out[d_y][d_x] = flat[y * over_w + x]
            tile_pos += 1
            if tile_pos == tile_w * tile_h:
                tile_pos = 0
                tile_origin_x += tile_w
                if tile_origin_x >= over_w:
                    tile_origin_x = 0
                    tile_origin_y += tile_h

    return out


def _inv_swap_tiles(pixels_2d: List[List[int]], w: int, h: int,
                    tile_w: int, tile_h: int) -> List[int]:
    """
    Reswizzle: reverse of _swap_tiles. Returns flat swizzled array.
    Used when injecting a modified image back.
    """
    over_w = _overscan(w, tile_w)
    over_h = _overscan(h, tile_h)

    flat = [0] * (over_w * over_h)
    tile_origin_x = tile_origin_y = tile_pos = 0

    for y in range(over_h):
        for x in range(over_w):
            d_x = tile_origin_x + (tile_pos % tile_w)
            d_y = tile_origin_y + (tile_pos // tile_w)
            if d_x < w and d_y < h:
                flat[y * over_w + x] = pixels_2d[d_y][d_x]
            tile_pos += 1
            if tile_pos == tile_w * tile_h:
                tile_pos = 0
                tile_origin_x += tile_w
                if tile_origin_x >= over_w:
                    tile_origin_x = 0
                    tile_origin_y += tile_h

    return flat


# ─────────────────────────────────────────────────────────────
# Pixel reading (nibble-aware for Index4)
# ─────────────────────────────────────────────────────────────

def _read_pixels(raw: bytes, img_hdr: Dict, over_w: int, over_h: int) -> List[int]:
    """
    Read pixel indices from raw bytes into a flat list for (over_w × over_h) pixels.
    Handles nibble packing for Index4 (high nibble = first pixel per LibPSPThemes).
    Applies row alignment after each row (rsx_pitch_align).
    """
    bpp        = img_hdr['bpp']
    pitch_align = img_hdr['pitch_align']
    flat = []
    pos = 0
    partial_bits = 0   # remaining bits from previous byte (for 4bpp)
    partial_val  = 0

    for y in range(over_h):
        row_start_pos = pos
        for x in range(over_w):
            if bpp == 4:
                if partial_bits == 0:
                    if pos >= len(raw):
                        flat.append(0)
                        continue
                    byte = raw[pos]; pos += 1
                    pixel = byte & 0xF               # low nibble first (PSP standard)
                    partial_val  = (byte >> 4) & 0xF  # save high nibble
                    partial_bits = 4
                else:
                    pixel = partial_val
                    partial_bits = 0
            elif bpp == 8:
                pixel = raw[pos] if pos < len(raw) else 0
                pos += 1
            elif bpp == 32:
                pixel = struct.unpack('<I', raw[pos:pos + 4])[0] if pos + 4 <= len(raw) else 0
                pos += 4
            else:  # 16-bpp variants
                pixel = struct.unpack('<H', raw[pos:pos + 2])[0] if pos + 2 <= len(raw) else 0
                pos += 2
            flat.append(pixel)

        # Align pos to pitch_align boundary after each row
        row_bytes = pos - row_start_pos
        remainder = row_bytes % pitch_align
        if remainder:
            pos += pitch_align - remainder
        partial_bits = 0  # reset nibble carry at row boundary

    return flat


def _pack_pixels(pixels_2d: List[List[int]], img_hdr: Dict,
                 over_w: int, over_h: int) -> bytes:
    """
    Pack pixels from 2D list back to bytes with row alignment.
    For Index4: high nibble = first pixel.
    """
    bpp         = img_hdr['bpp']
    pitch_align = img_hdr['pitch_align']
    out = bytearray()

    for row in pixels_2d:
        row_start = len(out)
        if bpp == 4:
            i = 0
            while i < over_w:
                lo = row[i] & 0xF if i < len(row) else 0         # low nibble = first pixel
                hi = row[i + 1] & 0xF if i + 1 < len(row) else 0 # high nibble = second pixel
                out.append((hi << 4) | lo)
                i += 2
        elif bpp == 8:
            for px in row:
                out.append(px & 0xFF)
        elif bpp == 32:
            for px in row:
                out.extend(struct.pack('<I', px))
        else:
            for px in row:
                out.extend(struct.pack('<H', px & 0xFFFF))
        # Pad row to pitch_align
        row_bytes = len(out) - row_start
        remainder = row_bytes % pitch_align
        if remainder:
            out.extend(b'\x00' * (pitch_align - remainder))

    return bytes(out)


# ─────────────────────────────────────────────────────────────
# GIM parsing
# ─────────────────────────────────────────────────────────────

def _palette_to_rgba8888(raw: bytes, fmt: int, n_colors: int) -> bytes:
    """
    Convert raw palette bytes (any GIM palette format) to RGBA8888 (4 bytes/color).
    GIM palette format codes match image format codes:
      0=RGBA5650  1=RGBA5551  2=RGBA4444  3=RGBA8888
    """
    out = bytearray(n_colors * 4)
    if fmt == FMT_RGBA8888:   # 4 bytes per color — already RGBA8888
        limit = min(n_colors * 4, len(raw))
        out[:limit] = raw[:limit]
    elif fmt in (FMT_RGBA5650, FMT_RGBA5551, FMT_RGBA4444):  # 2 bytes per color
        for i in range(min(n_colors, len(raw) // 2)):
            v = struct.unpack('<H', raw[i * 2:i * 2 + 2])[0]
            if fmt == FMT_RGBA5650:
                r = ((v >> 11) & 0x1F) * 8
                g = ((v >> 5)  & 0x3F) * 4
                b = (v & 0x1F) * 8
                a = 255
            elif fmt == FMT_RGBA5551:
                r = ((v >> 11) & 0x1F) * 8
                g = ((v >> 6)  & 0x1F) * 8
                b = ((v >> 1)  & 0x1F) * 8
                a = (v & 1) * 255
            else:  # RGBA4444
                r = ((v >> 12) & 0xF) * 17
                g = ((v >> 8)  & 0xF) * 17
                b = ((v >> 4)  & 0xF) * 17
                a = (v & 0xF) * 17
            out[i * 4:i * 4 + 4] = bytes([r, g, b, a])
    return bytes(out)


def _parse_gim_single(gim_data: bytes, base_abs: int = 0) -> Optional[Dict[str, Any]]:
    """
    Parse one GIM file (starts with MIG.00.1PSP\\x00).
    Returns image info dict or None on failure.
    base_abs: absolute offset of gim_data[0] in the outer file.
    """
    if not gim_data.startswith(GIM_SIG):
        return None

    # Block chain starts at offset 16 (after 16-byte preamble)
    # Structure: Root(type=2) → Picture(type=3) → Pixel(type=4) + Palette(type=5)
    # Walk blocks to find the pixel and palette blocks.
    pos = 16
    pixel_info = None
    palette_info = None

    while pos < len(gim_data) - 16:
        btype, bsize, next_blk, doff = _read_block_header(gim_data, pos)
        if bsize == 0:
            break

        if btype == BLK_PIX:
            hdr_start = pos + doff
            ih = _read_img_hdr(gim_data, hdr_start)
            if ih:
                pix_start = hdr_start + ih['frame_data_start']
                pix_end   = hdr_start + ih['frame_data_end']
                bpp = ih['bpp']
                tile_w = 128 // bpp
                tile_h = 8
                w, h = ih['width'], ih['height']
                over_w = _overscan(w, tile_w)
                over_h = _overscan(h, tile_h)

                raw = gim_data[pix_start:pix_end]
                flat = _read_pixels(raw, ih, over_w, over_h)

                if ih['pixel_order'] == 1:
                    pixels_2d = _swap_tiles(flat, w, h, tile_w, tile_h)
                else:
                    pixels_2d = [flat[y * w:(y + 1) * w] for y in range(h)]

                pixel_info = {
                    **ih,
                    'tile_w': tile_w, 'tile_h': tile_h,
                    'pixels_2d': pixels_2d,
                    'pix_raw_start_abs': base_abs + pix_start,
                    'pix_raw_end_abs':   base_abs + pix_end,
                    'pix_raw': raw,
                }

        elif btype == BLK_PAL:
            hdr_start = pos + doff
            ih = _read_img_hdr(gim_data, hdr_start)
            if ih:
                pal_start  = hdr_start + ih['frame_data_start']
                pal_end    = hdr_start + ih['frame_data_end']
                n_colors   = ih['width']    # palette width = number of colors
                pal_bpp    = ih['bpp']      # bits per palette entry (16 or 32)
                pal_fmt    = ih['format']   # 2=RGBA4444, 3=RGBA8888, etc.
                pal_raw    = gim_data[pal_start:pal_end]
                # Normalise palette to RGBA8888 regardless of source format
                pal_rgba8888 = _palette_to_rgba8888(pal_raw, pal_fmt, n_colors)
                palette_info = {
                    'n_colors': n_colors,
                    'raw':      pal_rgba8888,          # always RGBA8888 after normalisation
                    'raw_orig': pal_raw,               # original bytes (for inject)
                    'bpp':      pal_bpp,
                    'fmt':      pal_fmt,
                    'pal_raw_start_abs': base_abs + pal_start,
                    'pal_raw_end_abs':   base_abs + pal_end,
                }

        if next_blk == 0 or next_blk > len(gim_data) - pos:
            break
        pos += next_blk

    if pixel_info is None:
        return None

    return {
        'format':   pixel_info['format'],
        'width':    pixel_info['width'],
        'height':   pixel_info['height'],
        'bpp':      pixel_info['bpp'],
        'tile_w':   pixel_info['tile_w'],
        'tile_h':   pixel_info['tile_h'],
        'px_order': pixel_info['pixel_order'],
        'pixels_2d': pixel_info['pixels_2d'],
        'palette':   palette_info,
        'pix_raw_start_abs': pixel_info['pix_raw_start_abs'],
        'pix_raw_end_abs':   pixel_info['pix_raw_end_abs'],
        'pix_raw':   pixel_info['pix_raw'],
    }


def find_gim_segments(data: bytes, base_abs: int = 0) -> List[Tuple[int, bytes]]:
    """Find all MIG.00.1PSP\\x00 segments, returning (absolute_offset, gim_slice)."""
    results: List[Tuple[int, bytes]] = []
    pos = 0
    while True:
        idx = data.find(GIM_SIG, pos)
        if idx == -1:
            break
        nxt = data.find(GIM_SIG, idx + len(GIM_SIG))
        end = nxt if nxt != -1 else len(data)
        results.append((base_abs + idx, data[idx:end]))
        pos = idx + len(GIM_SIG)
    return results


def extract_all_gim(file_data: bytes) -> List[Dict[str, Any]]:
    """
    Find and parse all GIM images in a pBin file.
    Returns list of image dicts with 'idx' field.
    """
    results: List[Dict[str, Any]] = []
    idx = 0
    for gim_abs, gim_slice in find_gim_segments(file_data):
        info = _parse_gim_single(gim_slice, gim_abs)
        if info and info['width'] > 0 and info['height'] > 0:
            info['idx'] = idx
            results.append(info)
            idx += 1
    return results


# ─────────────────────────────────────────────────────────────
# PNG conversion
# ─────────────────────────────────────────────────────────────

def gim_info_to_png(info: Dict[str, Any]) -> Optional[bytes]:
    """Convert parsed GIM image to PNG bytes. Requires Pillow."""
    try:
        from PIL import Image
        from io import BytesIO
    except ImportError:
        return None

    fmt      = info['format']
    w        = info['width']
    h        = info['height']
    px2d     = info['pixels_2d']
    pal_info = info.get('palette')

    flat = [px2d[y][x] for y in range(h) for x in range(w)]

    if fmt in (FMT_INDEX4, FMT_INDEX8):
        if pal_info is None:
            return None
        pal_raw  = pal_info['raw']
        n_colors = pal_info['n_colors']

        # Build full RGBA palette for PIL (rawmode='RGBA' preserves alpha)
        pal_rgba = bytearray(256 * 4)
        for i in range(min(n_colors, len(pal_raw) // 4)):
            pal_rgba[i * 4 + 0] = pal_raw[i * 4 + 0]
            pal_rgba[i * 4 + 1] = pal_raw[i * 4 + 1]
            pal_rgba[i * 4 + 2] = pal_raw[i * 4 + 2]
            pal_rgba[i * 4 + 3] = pal_raw[i * 4 + 3]

        img = Image.new('P', (w, h))
        img.putpalette(bytes(pal_rgba), rawmode='RGBA')
        img.frombytes(bytes(flat))
        img = img.convert('RGBA')

    elif fmt in (FMT_INDEX16, FMT_INDEX32):
        # Wider palette indices than PIL's 'P' mode supports (max 256 entries) —
        # look up RGBA directly instead of going through a paletted image.
        if pal_info is None:
            return None
        pal_raw  = pal_info['raw']
        n_colors = pal_info['n_colors']
        out = bytearray(w * h * 4)
        for i, idx in enumerate(flat):
            if idx < n_colors:
                out[i * 4:i * 4 + 4] = pal_raw[idx * 4:idx * 4 + 4]
        img = Image.frombytes('RGBA', (w, h), bytes(out))

    elif fmt == FMT_RGBA8888:
        out = bytearray(w * h * 4)
        for i, px in enumerate(flat):
            out[i * 4:i * 4 + 4] = struct.pack('<I', px)
        img = Image.frombytes('RGBA', (w, h), bytes(out))

    elif fmt in (FMT_RGBA5650, FMT_RGBA5551, FMT_RGBA4444):
        out = bytearray(w * h * 4)
        for i, v in enumerate(flat):
            if fmt == FMT_RGBA5650:
                r = ((v >> 11) & 0x1F) << 3
                g = ((v >> 5)  & 0x3F) << 2
                b = (v & 0x1F) << 3
                a = 255
            elif fmt == FMT_RGBA5551:
                r = ((v >> 11) & 0x1F) << 3
                g = ((v >> 6)  & 0x1F) << 3
                b = ((v >> 1)  & 0x1F) << 3
                a = (v & 1) * 255
            else:  # RGBA4444
                r = ((v >> 12) & 0xF) << 4
                g = ((v >> 8)  & 0xF) << 4
                b = ((v >> 4)  & 0xF) << 4
                a = (v & 0xF) << 4
            out[i * 4:i * 4 + 4] = bytes([r, g, b, a])
        img = Image.frombytes('RGBA', (w, h), bytes(out))

    else:
        return None

    buf = BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def png_to_gim_pixels(png_data: bytes, info: Dict[str, Any]) -> Tuple[bytes, bytes]:
    """
    Convert PNG to GIM pixel bytes + palette bytes for in-place injection.
    Returns (raw_pixel_bytes, raw_palette_bytes).
    """
    try:
        from PIL import Image
        from io import BytesIO
    except ImportError:
        return b'', b''

    fmt  = info['format']
    w    = info['width']
    h    = info['height']
    bpp  = info['bpp']
    tile_w = info['tile_w']
    tile_h = info['tile_h']
    order  = info['px_order']
    pal_info = info.get('palette')
    n_colors = pal_info['n_colors'] if pal_info else (16 if fmt == FMT_INDEX4 else 256)

    img = Image.open(BytesIO(png_data)).convert('RGBA').resize((w, h), Image.LANCZOS)

    if fmt in (FMT_INDEX4, FMT_INDEX8):
        rgb = img.convert('RGB')
        quantized = rgb.quantize(colors=n_colors, dither=Image.Dither.FLOYDSTEINBERG)

        # Pixel 2D array
        pix_flat = list(quantized.tobytes())
        pixels_2d = [pix_flat[y * w:(y + 1) * w] for y in range(h)]

        # Reswizzle if original was swizzled
        if order == 1:
            over_w = _overscan(w, tile_w)
            over_h = _overscan(h, tile_h)
            flat_swizzle = _inv_swap_tiles(pixels_2d, w, h, tile_w, tile_h)
            swizzle_2d = [flat_swizzle[y * over_w:(y + 1) * over_w] for y in range(over_h)]
        else:
            swizzle_2d = pixels_2d
            over_w, over_h = w, h

        ih_mock = {'bpp': bpp, 'pitch_align': 16}
        raw_pixels = _pack_pixels(swizzle_2d, ih_mock, over_w, over_h)

        # Build palette
        pal_rgb = quantized.getpalette() or []
        pal_rgba = bytearray(n_colors * 4)
        for i in range(n_colors):
            pal_rgba[i * 4]     = pal_rgb[i * 3]     if i * 3     < len(pal_rgb) else 0
            pal_rgba[i * 4 + 1] = pal_rgb[i * 3 + 1] if i * 3 + 1 < len(pal_rgb) else 0
            pal_rgba[i * 4 + 2] = pal_rgb[i * 3 + 2] if i * 3 + 2 < len(pal_rgb) else 0
            pal_rgba[i * 4 + 3] = 255

        return raw_pixels, bytes(pal_rgba)

    if fmt in (FMT_RGBA8888, FMT_RGBA5650, FMT_RGBA5551, FMT_RGBA4444):
        # Direct-color formats carry no palette — pack pixels straight into
        # the target bit layout (inverse of the decode math in gim_info_to_png).
        rgba = list(img.tobytes())
        pixels_2d = []
        for y in range(h):
            row = []
            for x in range(w):
                r, g, b, a = rgba[(y * w + x) * 4:(y * w + x) * 4 + 4]
                if fmt == FMT_RGBA8888:
                    px = r | (g << 8) | (b << 16) | (a << 24)
                elif fmt == FMT_RGBA5650:
                    px = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                elif fmt == FMT_RGBA5551:
                    px = ((r >> 3) << 11) | ((g >> 3) << 6) | ((b >> 3) << 1) | (1 if a >= 128 else 0)
                else:  # RGBA4444
                    px = ((r >> 4) << 12) | ((g >> 4) << 8) | ((b >> 4) << 4) | (a >> 4)
                row.append(px)
            pixels_2d.append(row)

        if order == 1:
            over_w = _overscan(w, tile_w)
            over_h = _overscan(h, tile_h)
            flat_swizzle = _inv_swap_tiles(pixels_2d, w, h, tile_w, tile_h)
            swizzle_2d = [flat_swizzle[y * over_w:(y + 1) * over_w] for y in range(over_h)]
        else:
            swizzle_2d = pixels_2d
            over_w, over_h = w, h

        ih_mock = {'bpp': bpp, 'pitch_align': 16}
        raw_pixels = _pack_pixels(swizzle_2d, ih_mock, over_w, over_h)
        return raw_pixels, b''

    return b'', b''


# ─────────────────────────────────────────────────────────────
# In-place file patching
# ─────────────────────────────────────────────────────────────

def inject_image_into_file(file_data: bytes, img_idx: int, png_path: str) -> bytes:
    """
    Replace image img_idx with the PNG at png_path (in-place, same byte positions).
    Returns modified file_data. Raises ValueError on failure.
    """
    images = extract_all_gim(file_data)
    if img_idx >= len(images):
        raise ValueError(f"Image index {img_idx} out of range ({len(images)} images)")

    info = images[img_idx]
    with open(png_path, 'rb') as f:
        png_data = f.read()

    new_pixels, new_palette = png_to_gim_pixels(png_data, info)
    if not new_pixels:
        raise ValueError(f"Could not convert PNG to format {info['format']}")

    result = bytearray(file_data)

    # Write pixel data
    pix_start = info['pix_raw_start_abs']
    pix_end   = info['pix_raw_end_abs']
    size = pix_end - pix_start
    result[pix_start:pix_end] = new_pixels[:size]

    # Write palette data
    pal = info.get('palette')
    if new_palette and pal:
        ps = pal['pal_raw_start_abs']
        pe = pal['pal_raw_end_abs']
        result[ps:pe] = new_palette[:pe - ps]

    return bytes(result)


# ─────────────────────────────────────────────────────────────
# Translation progress / listing (web app)
# ─────────────────────────────────────────────────────────────

_IMG_NAME_RE = re.compile(r'^(?P<fileid>.+)_(?P<idx>\d+)_(?P<w>\d+)x(?P<h>\d+)$')


def _base_pngs(fdir: str) -> List[str]:
    return sorted(fn for fn in os.listdir(fdir)
                  if fn.endswith('.png') and not fn[:-4].endswith('_translated'))


def list_image_files(images_dir: str) -> List[Dict[str, Any]]:
    """List image-bearing source files for the sidebar: [{id, done, total}, ...]."""
    result = []
    if not os.path.isdir(images_dir):
        return result
    for fileid in sorted(os.listdir(images_dir)):
        fdir = os.path.join(images_dir, fileid)
        if not os.path.isdir(fdir):
            continue
        base = _base_pngs(fdir)
        if not base:
            continue
        done = sum(1 for fn in base
                   if os.path.exists(os.path.join(fdir, f'{fn[:-4]}_translated.png')))
        result.append({'id': fileid, 'done': done, 'total': len(base)})
    return result


def list_file_image_entries(images_dir: str, fileid: str) -> List[Dict[str, Any]]:
    """List images within one source file's folder, for the side-by-side viewer."""
    fdir = os.path.join(images_dir, fileid)
    if not os.path.isdir(fdir):
        return []
    entries = []
    for fn in _base_pngs(fdir):
        stem = fn[:-4]
        m = _IMG_NAME_RE.match(stem)
        translated_fn = f'{stem}_translated.png'
        has_translated = os.path.exists(os.path.join(fdir, translated_fn))
        entries.append({
            'idx': int(m.group('idx')) if m else 0,
            'width': int(m.group('w')) if m else 0,
            'height': int(m.group('h')) if m else 0,
            'filename': fn,
            'translated_filename': translated_fn if has_translated else None,
        })
    entries.sort(key=lambda e: e['idx'])
    return entries
