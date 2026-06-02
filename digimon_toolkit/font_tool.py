"""
Font extraction and patching tool for Digimon Adventure PSP.

Font location: CPK file 3631, byte offset 29824
Format: 192 chars (0x20–0xDF), 128 bytes/char, 8 bytes/row × 16 rows, 4bpp
Pixel packing: low nibble = first pixel (standard PSP Index4)

Accent proxy mapping (chars reused as accented letter slots):
    @ → á    # → é    $ → í    & → ó    * → ú    + → ñ    = → ü

Workflow:
    1. python digimon_toolkit/font_tool.py extract
       → writes translations/font_atlas.png  (192-glyph grid, editable)

    2. Edit translations/font_atlas.png in any image editor.
       Each cell is 96×96 px (6× scale). White = ink, black = transparent.
       Find the accented chars at: @ col 0 row 2 / # col 3 row 1 / $ col 4 row 1
                                   & col 6 row 1 / * col 10 row 1/ + col 11 row 1
                                   = col 29 row 1

    3. python digimon_toolkit/font_tool.py import-atlas
       → reads translations/font_atlas.png, updates patched_data/3631

    4. bash translations/build-iso.sh   (calls import-atlas automatically)

Other commands:
    python digimon_toolkit/font_tool.py patch       # re-render accents from system TTF
    python digimon_toolkit/font_tool.py show <hex>  # show one glyph (e.g. show 40 for @)
"""

import sys, struct, os
from pathlib import Path
from PIL import Image

# ── font file constants ──────────────────────────────────────────────────────
FONT_FILE   = 'patched_data/3631'
FONT_OFFSET = 29824        # byte offset of pixel data inside the file
CHAR_FIRST  = 0x20         # first char code in the table
N_CHARS     = 192          # chars covered (0x20–0xDF)
BPR         = 8            # bytes per row (16 pixels at 4bpp)
CELL_ROWS   = 16           # rows per glyph cell
STRIDE      = BPR * CELL_ROWS   # 128 bytes per glyph

# ── mapping: Unicode accented char → slot in 0x80–0xDF range ─────────────────
# Chars placed here replace unused half-width katakana slots.
# Toolkit apply() must remap these before writing ESDF text.
ACCENT_MAP = {
    # Maps Unicode accented chars → ASCII chars that are repainted in the font.
    # These ASCII codes already work in the game renderer; we just swap the glyphs.
    # @ # $ & * + = are not used in Spanish dialog text.
    'á': 0x40,  # @
    'é': 0x23,  # #
    'í': 0x24,  # $
    'ó': 0x26,  # &
    'ú': 0x2A,  # *
    'ñ': 0x2B,  # +
    'ü': 0x3D,  # =
}

# ── low-level helpers ─────────────────────────────────────────────────────────

def read_font() -> bytes:
    with open(FONT_FILE, 'rb') as f:
        f.seek(FONT_OFFSET)
        return f.read(N_CHARS * STRIDE)

def glyph(font: bytes, char_code: int) -> bytes:
    idx = char_code - CHAR_FIRST
    return font[idx*STRIDE:(idx+1)*STRIDE]

def set_glyph(font: bytearray, char_code: int, glyph_bytes: bytes):
    idx = char_code - CHAR_FIRST
    font[idx*STRIDE:(idx+1)*STRIDE] = glyph_bytes[:STRIDE]

def glyph_to_image(g: bytes) -> Image.Image:
    """Convert raw glyph bytes → RGBA PIL image (white on transparent)."""
    img = Image.new('RGBA', (BPR*2, CELL_ROWS), (0,0,0,0))
    for row in range(CELL_ROWS):
        for bpos in range(BPR):
            byte = g[row*BPR + bpos]
            img.putpixel((bpos*2,   row), (255,255,255,(byte&0xF)*17))
            img.putpixel((bpos*2+1, row), (255,255,255,((byte>>4)&0xF)*17))
    return img

def image_to_glyph(img: Image.Image) -> bytes:
    """Convert a 16×16 RGBA image → raw 4bpp glyph bytes. Alpha = ink intensity."""
    img = img.convert('RGBA')
    g = bytearray(STRIDE)
    for row in range(CELL_ROWS):
        for bpos in range(BPR):
            p0 = img.getpixel((bpos*2,   row))[3] // 17
            p1 = img.getpixel((bpos*2+1, row))[3] // 17
            g[row*BPR + bpos] = (p0 & 0xF) | ((p1 & 0xF) << 4)
    return bytes(g)

def render_ttf_glyph(char: str, font_path: str, size: int = 13) -> Image.Image:
    """Render a single character from a TTF/OTF file into a 16×16 RGBA cell."""
    from PIL import ImageFont
    try:
        ttf = ImageFont.truetype(font_path, size)
    except Exception:
        ttf = ImageFont.load_default()
    canvas = Image.new('RGBA', (BPR*2, CELL_ROWS), (0,0,0,0))
    from PIL import ImageDraw
    d = ImageDraw.Draw(canvas)
    # Centre the glyph vertically with a small top offset
    bbox = ttf.getbbox(char)
    x = max(0, (BPR*2 - (bbox[2]-bbox[0])) // 2 - bbox[0])
    y = max(0, (CELL_ROWS - (bbox[3]-bbox[1])) // 2 - bbox[1] - 1)
    d.text((x, y), char, font=ttf, fill=(255,255,255,255))
    return canvas

# ── commands ─────────────────────────────────────────────────────────────────

ATLAS_PATH  = 'translations/font_atlas.png'
ATLAS_COLS  = 16
ATLAS_CELL  = BPR * 2    # 16 px wide per cell — native 1:1, 1 pixel = 1 font pixel
ATLAS_CROW  = CELL_ROWS  # 16 px tall per cell

def _build_atlas(font: bytes) -> Image.Image:
    """Render all 192 glyphs into a grid PNG suitable for editing."""
    from PIL import ImageDraw
    rows_grid = (N_CHARS + ATLAS_COLS - 1) // ATLAS_COLS
    w = ATLAS_COLS * (ATLAS_CELL + 1) + 1
    h = rows_grid  * (ATLAS_CROW + 1) + 1
    # MUST be fully transparent: import reads alpha channel as glyph intensity.
    # Any non-zero alpha in "empty" areas would become ink in the font.
    atlas = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw  = ImageDraw.Draw(atlas)

    # Grid lines: semi-transparent so they're visible in editors but
    # don't affect import (grid lines lie between cells, not inside them).
    for col in range(ATLAS_COLS + 1):
        x = col * (ATLAS_CELL + 1)
        draw.line([(x, 0), (x, h)], fill=(180, 180, 255, 60))
    for row in range(rows_grid + 1):
        y = row * (ATLAS_CROW + 1)
        draw.line([(0, y), (w, y)], fill=(40, 40, 60, 255))

    for idx in range(N_CHARS):
        code = CHAR_FIRST + idx
        g    = glyph(font, code)
        gimg = glyph_to_image(g)   # already native 16×16 — paste directly, no resize
        col, row_g = idx % ATLAS_COLS, idx // ATLAS_COLS
        cx = col   * (ATLAS_CELL + 1) + 1
        cy = row_g * (ATLAS_CROW + 1) + 1
        atlas.paste(gimg, (cx, cy))

    return atlas


def cmd_extract():
    font  = read_font()
    atlas = _build_atlas(font)
    os.makedirs('translations', exist_ok=True)
    os.makedirs('output', exist_ok=True)
    atlas.save(ATLAS_PATH)
    atlas.save('output/font_atlas.png')
    rows_grid = (N_CHARS + ATLAS_COLS - 1) // ATLAS_COLS
    print(f"Font atlas → {ATLAS_PATH}  ({N_CHARS} glyphs, {ATLAS_COLS} cols × {rows_grid} rows, {ATLAS_CELL}×{ATLAS_CROW}px/cell)")
    print(f"            output/font_atlas.png  (same)")
    print()
    print("Accent char positions in the atlas:")
    for char, code in ACCENT_MAP.items():
        idx = code - CHAR_FIRST
        col, row = idx % ATLAS_COLS, idx // ATLAS_COLS
        print(f"  {char!r} (proxy {chr(code)!r} 0x{code:02x})  →  col {col:2d}  row {row}")


def cmd_import_atlas():
    """Read translations/font_atlas.png and write every glyph back to patched_data/3631."""
    if not os.path.exists(ATLAS_PATH):
        print(f"Atlas not found: {ATLAS_PATH}")
        print("Run 'python digimon_toolkit/font_tool.py extract' first.")
        sys.exit(1)

    atlas = Image.open(ATLAS_PATH).convert('RGBA')
    rows_grid = (N_CHARS + ATLAS_COLS - 1) // ATLAS_COLS
    expected_w = ATLAS_COLS * (ATLAS_CELL + 1) + 1
    expected_h = rows_grid  * (ATLAS_CROW + 1) + 1
    if atlas.size != (expected_w, expected_h):
        print(f"Atlas size mismatch: got {atlas.size}, expected {(expected_w, expected_h)}")
        print("Make sure you didn't resize/crop the atlas PNG.")
        sys.exit(1)

    with open(FONT_FILE, 'rb') as f:
        file_data = bytearray(f.read())

    font = bytearray(file_data[FONT_OFFSET:FONT_OFFSET + N_CHARS * STRIDE])

    for idx in range(N_CHARS):
        col, row_g = idx % ATLAS_COLS, idx // ATLAS_COLS
        cx = col   * (ATLAS_CELL + 1) + 1
        cy = row_g * (ATLAS_CROW + 1) + 1
        cell = atlas.crop((cx, cy, cx + ATLAS_CELL, cy + ATLAS_CROW))
        # Cell is already native 16×16 — read pixels directly, no resize.
        g = image_to_glyph(cell)
        code = CHAR_FIRST + idx
        set_glyph(font, code, g)

    file_data[FONT_OFFSET:FONT_OFFSET + N_CHARS * STRIDE] = font
    with open(FONT_FILE, 'wb') as f:
        f.write(file_data)
    print(f"Imported {N_CHARS} glyphs from {ATLAS_PATH} → {FONT_FILE}")

def cmd_show(code_hex: str):
    code = int(code_hex, 16)
    font = read_font()
    g = glyph(font, code)
    char = chr(code) if 32 <= code < 127 else f'<{code:02x}>'
    print(f"Glyph for {char!r} (0x{code:02x}):")
    for row in range(CELL_ROWS):
        nibs = []
        for bpos in range(BPR):
            byte = g[row*BPR+bpos]
            nibs += [byte&0xF, (byte>>4)&0xF]
        vis = ''.join('█' if n>11 else '▓' if n>7 else '▒' if n>3 else ' ' for n in nibs)
        print(f"  {row:2d}: |{vis}|")

def cmd_patch():
    """
    Build accented-char glyphs from a system font and patch them into file 3631.
    Tries common macOS/Linux font paths.
    """
    # Find a suitable Latin font
    candidates = [
        '/System/Library/Fonts/Helvetica.ttc',
        '/System/Library/Fonts/Arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    font_path = next((p for p in candidates if os.path.exists(p)), None)
    if not font_path:
        print("No suitable TTF found. Install DejaVu or similar fonts.")
        sys.exit(1)
    print(f"Using font: {font_path}")

    with open(FONT_FILE, 'rb') as f:
        file_data = bytearray(f.read())

    font = bytearray(file_data[FONT_OFFSET:FONT_OFFSET + N_CHARS*STRIDE])
    changed = []

    for char, slot in ACCENT_MAP.items():
        try:
            img = render_ttf_glyph(char, font_path, size=13)
            g = image_to_glyph(img)
            set_glyph(font, slot, g)
            changed.append((char, slot))
            print(f"  Patched '{char}' → slot 0x{slot:02x}")
        except Exception as e:
            print(f"  SKIP '{char}': {e}")

    file_data[FONT_OFFSET:FONT_OFFSET + N_CHARS*STRIDE] = font
    with open(FONT_FILE, 'wb') as f:
        f.write(file_data)

    print(f"\nPatched {len(changed)} glyphs into {FONT_FILE}")
    print("Run 'python digimon_toolkit/cli.py apply' to rebuild the ISO.")
    print("\nAccent map (add to your translation CSV):")
    for char, slot in sorted(ACCENT_MAP.items(), key=lambda x: x[1]):
        print(f"  {char!r}  →  0x{slot:02x}  (use char code {slot} in the game text)")

def cmd_export_map():
    """Print the accent mapping for use in the translation toolkit."""
    print("ACCENT_REMAP = {")
    for char, slot in sorted(ACCENT_MAP.items()):
        print(f"    {char!r}: chr({slot}),  # 0x{slot:02x}")
    print("}")


if __name__ == '__main__':
    cmds = {
        'extract':      cmd_extract,
        'import-atlas': cmd_import_atlas,
        'patch':        cmd_patch,
        'export-map':   cmd_export_map,
    }
    if len(sys.argv) < 2 or (sys.argv[1] not in cmds and sys.argv[1] != 'show'):
        print(__doc__)
        sys.exit(0)
    if sys.argv[1] == 'show':
        cmd_show(sys.argv[2] if len(sys.argv) > 2 else '40')
    else:
        cmds[sys.argv[1]]()
