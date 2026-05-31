# Digimon Adventure PSP — Localization Toolkit

> `CLAUDE.md` is a symlink to this file.

## Overview

This toolkit extracts text from the English fan patch (v1.2) of **Digimon Adventure (PSP)**, converts it to an editable CSV format, and repackages translated content back into a playable ISO and distributable xdelta patch.

The patch source is the English fan translation applied over the original Japanese ISO. The toolkit is language-agnostic: any target language can be plugged in by providing a translation guide in its own folder alongside the CSVs.

---

## Repository Layout

```
translations/
├── csv/
│   ├── dialog/      ← Working files — one CSV per game scene
│   └── other/       ← Secondary UI/menu text
├── dialog/          ← JSON backend (do not edit directly)
├── other/           ← JSON backend for secondary text
├── eboot/           ← Executable strings (UI, skills, episode menu)
└── names/
    └── names.json   ← Character and Digimon names

digimon_toolkit/
├── cli.py           ← Command-line interface
├── csv_tools.py     ← JSON ↔ CSV conversion
├── cpk.py           ← CRI CPK archive reader/writer
├── esdf.py          ← ESDF text format parser
├── pbin.py          ← pBin container parser
├── utf.py           ← @UTF table parser
└── psp_image.py     ← GIM/PSP image handler

<LANG>_TRANSLATION/  ← One folder per target language (e.g. FR_FR_TRANSLATION/)
                        Contains language guide and reference docs for translators.

orig_data/           ← Extracted original Japanese CPK files
patched_data/        ← Extracted English-patched CPK files
orig_iso/            ← Mounted original Japanese ISO
patched_iso/         ← Mounted English-patched ISO
output/              ← Generated ISO and xdelta patch
```

---

## CLI Reference

```bash
python digimon_toolkit/cli.py extract-cpk     # Extract orig_data/ and patched_data/
python digimon_toolkit/cli.py extract-text    # Parse ESDF text → JSON in translations/
python digimon_toolkit/cli.py extract-images  # Extract GIM textures to PNG
python digimon_toolkit/cli.py extract-all     # Run all three extract steps
python digimon_toolkit/cli.py to-csv          # Export dialog JSONs → CSV in translations/csv/
python digimon_toolkit/cli.py from-csv        # Import CSV translations → JSON
python digimon_toolkit/cli.py progress        # Show translation progress bar
python digimon_toolkit/cli.py apply           # Apply translations → build ISO + xdelta patch
```

---

## Workflow

### Normal translation session

```bash
# 1. Check progress
python digimon_toolkit/cli.py progress

# 2. Edit CSVs in translations/csv/dialog/
#    Fill in the 'translation' column for each row.

# 3. Import CSVs back to JSON
python digimon_toolkit/cli.py from-csv

# 4. Build ISO and patch
python digimon_toolkit/cli.py apply
```

### Full extraction from scratch

Only needed if patched_data/ or translations/ are missing or corrupted.

```bash
python digimon_toolkit/cli.py extract-cpk
python digimon_toolkit/cli.py extract-text
python digimon_toolkit/cli.py to-csv
```

---

## CSV Format

One CSV per dialog scene, located in `translations/csv/dialog/`.

```
index,limit,original,translation
0,71,"During the summer of that year,\nstrange events happened all over\nEarth.",
5,7,Taichi!,
6,16,"What's up, Sora?",
```

| Column | Description | Edit? |
|--------|-------------|-------|
| `index` | Entry number within the file | NO |
| `limit` | Maximum bytes for the translation | NO |
| `original` | English source text | NO |
| `translation` | Translated text in the target language | YES |

**Newlines** inside text are represented as the literal two-character sequence `\n`. Each `\n` counts as 1 byte toward the `limit`.

**Byte limit enforcement**: the `limit` value equals the byte length of the English source string (post-accent-stripping). Translations exceeding this limit are silently truncated in-game. The `from-csv` import does not validate lengths — check manually or via `csv_tools.check_lengths()`.

---

## Technical Notes

### Game file formats

| Format | Description |
|--------|-------------|
| CPK | CRI Middleware archive (~737 MB). Contains all game data. |
| pBin | Per-resource container embedded in CPK entries. |
| ESDF | CRI text format embedded in pBin as a `BIN ESDF` entry. |
| CRILAYLA | CRI LZSS compression variant. Decompression supported; re-compression is not yet implemented. |
| GIM | PSP native texture format (`MIG.00.1PSP\x00`). Full read/write support via `psp_image.py`. |

### Dialog file ID mapping

Dialog files in the CPK are identified by a numeric ID (e.g. `3520`) and a zero-padded prefixed variant (`ID03520`). The `apply` command patches both variants automatically from a single JSON file.

The numeric IDs roughly map to the 54 anime episodes plus extra game-specific scenes:

| File range | Content |
|------------|---------|
| 3520–3533 | Episodes 1–13 (Devimon arc) |
| 3534–3540 | Episodes 14–20 (Etemon arc) |
| 3541–3561 | Episodes 21–39 (Myotismon arc) |
| 3562–3574 | Episodes 40–52 (Dark Masters arc) |
| 3575–3580 | Episodes 53–54 (Apocalymon arc) |
| 3581–3622 | Game-original scenes, battles, side content |

### Speaker IDs in dialog CSV

Each dialog CSV row includes a `speaker` column with a numeric ID (0–9). This ID is extracted from the ESDF binary record table that precedes the text region in each file.

The ID is **scene-local**: the same numeric value can refer to different characters across different episode files. The mapping must be established empirically by playing the game and observing which name the engine displays for each ID in each scene.

File 3520 (episode 1) reference mapping (approximate — positional matching is offset by ~4 records):

| speaker | Likely character |
|---------|-----------------|
| 0 | Narrator |
| 1 | Taichi / general dialog |
| 2 | Koushirou / Yamato |
| 4 | Sora |
| 7 | Taichi (action lines) |
| 8 | Yamato / Taichi shouts |

The lookup table for each episode is stored in `EBOOT.BIN` and cannot be extracted without reversing the MIPS binary.

### Font rendering

The English patch uses ASCII-only rendering. The font renderer is **embedded in `EBOOT.BIN`** as MIPS code — there is no separate GIM font atlas file. Adding accented characters or ñ to the dialog box would require patching the ELF binary.

UI text (buttons, menus, banners) is **baked into GIM textures** and can be patched via `extract-image` / `inject-image`.

### Patched image files

The English patch modified pixel data in 11 files. All are extractable as PNG:

| File | Content |
|------|---------|
| `0015` | Yes/No confirmation buttons |
| `0044` | Battle command: GUARD |
| `0045` | Battle command: FLEE |
| `0046` | Battle command: SKILL |
| `0047` | Battle command: ITEM |
| `0048` | L/R button labels |
| `0050` | Battle command: ATTACK |
| `0069` | Dialog panel with character portraits |
| `0070` | Battle UI decorative lines |
| `0126` | Battle HUD (HP / character name) |
| `0151` | RANK UP screen |
| `0156` | Startup logo sequence (img_04 = WARNING screen, 512×256) |

### GIM image format

Images use `MIG.00.1PSP\x00` signature (note: `\x00` terminator, not `\n`).
Reference implementation: `digimon_toolkit/psp_image.py` (verified against LibPSPThemes/gim.py).

#### Block structure (16-byte header for every block)

```
+0x00  block_type   u16   (2=root  3=picture  4=pixel  5=palette)
+0x02  reserved     u16   = 0
+0x04  block_size   u32   total bytes from this header onwards
+0x08  next_block   u32   offset from block start to next sibling (= block_size)
+0x0C  data_offset  u32   offset from block start to image-data-header
```

#### Image-data-header (48 bytes, at block_start + data_offset)

```
+0x00  structure_size   u16  = 0x30 (48)
+0x02  reserved         u16
+0x04  format           u16  pixel format code (see table)
+0x06  pixel_order      u16  0=linear  1=swizzled
+0x08  width            u16  pixels per row
+0x0A  height           u16  pixel rows
+0x0C  rsx_bpp          u16  bits per pixel (4, 8, 16, or 32)
+0x0E  rsx_pitch_align  u16  typically 16
+0x10  rsx_height_align u16  typically 8
+0x18  next_index_block u32  offset from header to index block (typically 48)
+0x1C  frame_data_start u32  offset from header to pixel/palette data  ← CRITICAL
+0x20  frame_data_end   u32  offset from header to end of pixel/palette data
```

**Pixel data is at: `image_data_header_start + frame_data_start`** (not at a fixed offset from the GIM signature). In all files observed, `frame_data_start = 64` and the structure is:

```
GIM preamble    [+0..+15]   "MIG.00.1PSP\x00" + 4 null bytes
Root block      [+16..+31]  type=2, data_offset=16
Picture block   [+32..+47]  type=3, data_offset=16
Pixel block     [+48..+63]  type=4, data_offset=16
Image-data-hdr  [+64..+111] 48-byte header; frame_data_start=64
Pixel data      [+128..]    actual pixel bytes
Palette block   [pixel_block_start + pixel_block_size]
Palette hdr     [pal_block + 16] 48-byte header; frame_data_start=64
Palette data    [pal_hdr + 64]   palette color entries
```

#### Pixel format codes

| Code | Name       | bpp |
|------|------------|-----|
| 0    | RGBA5650   | 16  |
| 1    | RGBA5551   | 16  |
| 2    | RGBA4444   | 16  |
| 3    | RGBA8888   | 32  |
| 4    | Index4     | 4   |
| 5    | Index8     | 8   |

#### PSP swizzle (tile layout)

Applies when `pixel_order == 1`. Tile dimensions: `tile_width = 128 // rsx_bpp` pixels, `tile_height = 8` rows always.

The swizzled data is read as a flat `(over_w × over_h)` array (dimensions rounded up to tile multiples), then remapped via `swap_tiles()` (LibPSPThemes algorithm). This is NOT a simple Morton/Z-curve — it is a tile-sequential rearrangement where each tile's pixels are stored in row-major order within the tile.

#### Index4 nibble order

**Low nibble = first pixel, high nibble = second pixel** (PSP standard). Each byte packs two adjacent palette indices: `byte = (second_pixel << 4) | first_pixel`.

#### Palette format

The palette block uses the same image-data-header format. The palette's own `format` field determines color encoding — **it is not always RGBA8888**. Known variants in this game:

| Palette format | bpp | Decoding |
|---------------|-----|----------|
| 3 (RGBA8888)  | 32  | 4 bytes: R G B A |
| 2 (RGBA4444)  | 16  | u16 LE, bits [15:12]=R [11:8]=G [7:4]=B [3:0]=A, scale ×17 |
| 1 (RGBA5551)  | 16  | u16 LE, bits [15:11]=R [10:6]=G [5:1]=B [0]=A |

Always read `rsx_bpp` from the palette block's image-data-header to determine color size.
`psp_image._palette_to_rgba8888()` handles all variants and normalises to RGBA8888.

#### PIL gotcha

When building an indexed `Image.new('P', ...)` with transparency, use:
```python
img.putpalette(rgba_bytes, rawmode='RGBA')   # NOT putpalette(rgb_bytes)
```
Without `rawmode='RGBA'`, PIL silently drops the alpha channel and all pixels become fully opaque, making transparent areas render as solid colours.

### Character encoding

The English patch uses ASCII for in-game text rendering. The `apply` command strips accented characters to their ASCII base equivalents before writing to the CPK (á→a, ñ→n, etc.). Translations should be written with full accents for readability; the strip pass happens automatically at apply time.

If a future font hack adds native support for accented characters, remove the `strip_accents` call in `cli.py:cmd_apply()`.

### System requirements

- Python 3.8+
- `xdelta3` (for patch generation): `brew install xdelta` / `apt install xdelta3`

### Output files

| File | Description |
|------|-------------|
| `output/Digimon Adventure (Translated).iso` | Full playable ISO for testing in PPSSPP |
| `output/translation_patch.xdelta` | Distributable patch applied over the original Japanese ISO |
