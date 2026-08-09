# Digimon Adventure PSP — Localization Toolkit

> `CLAUDE.md` is a symlink to this file.

## Overview

This toolkit extracts text, images, and cutscene videos from the English fan patch (v1.2) of **Digimon Adventure (PSP)**, exposes the text through an editable JSON backend (driven by a translation web app), and repackages translated content back into a playable ISO and distributable xdelta patch.

The patch source is the English fan translation applied over the original Japanese ISO. The toolkit is language-agnostic: any target language can be plugged in by providing a translation guide in its own folder alongside the JSON files.

---

## Repository Layout

```
translations/
├── dialog/          ← JSON backend (do not edit directly)
├── other/           ← JSON backend for secondary text
├── eboot/           ← Executable strings (UI, skills, episode menu)
├── names/
│   └── names.json   ← Character and Digimon names
├── images/          ← GIM textures the English patch changed vs. Japanese, as PNG
│   └── <fileid>/<fileid>_<idx>_<w>x<h>.png (+ optional _translated.png sibling)
├── videos/          ← TV opening (file 3691), extracted to intro.mp4 + dub reference files
└── audio/           ← Menu theme (file 3693 track 0), extracted to menu_theme.wav + dub reference files

digimon_toolkit/
├── cli.py           ← Command-line interface
├── font_tool.py     ← Font extraction, atlas edit pipeline, accent glyph patching
├── cpk.py           ← CRI CPK archive reader/writer
├── esdf.py          ← ESDF text format parser
├── pbin.py          ← pBin container parser
├── utf.py           ← @UTF table parser
├── psp_image.py     ← GIM/PSP image handler
├── psmf.py          ← PSMF/PMF cutscene demuxer
└── afs2.py          ← AFS2/AWB BGM archive reader

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
python digimon_toolkit/cli.py extract-images  # Extract GIM textures changed by the patch → translations/images/
python digimon_toolkit/cli.py extract-videos  # Extract the TV opening (video+audio) → translations/videos/intro.mp4
python digimon_toolkit/cli.py extract-audio   # Extract the menu theme → translations/audio/menu_theme.wav
python digimon_toolkit/cli.py extract-all     # Run all five extract steps
python digimon_toolkit/cli.py progress        # Show translation progress bar
python digimon_toolkit/cli.py apply           # Apply translations → build ISO + xdelta patch
```

---

## Workflow

### Normal translation session

```bash
# 1. Launch the translation web app (reads/writes translations/*.json directly)
python digimon_toolkit/cli.py serve

# 2. Translate dialog/EBOOT/names text in the browser UI, and/or drop
#    <name>_translated.png / _translated.mp4 files next to extracted
#    images/videos (see "Images & video" below).

# 3. Build ISO and patch
python digimon_toolkit/cli.py apply
```

Text lives in `translations/dialog/*.json`, `translations/eboot/*.json`, and
`translations/names/names.json` — edit these through the web app (`serve`),
not by hand; it validates byte limits and unsupported characters as you type.

### Full extraction from scratch

Only needed if patched_data/ or translations/ are missing or corrupted.

```bash
python digimon_toolkit/cli.py extract-all
```

---

## Images & video

- **Images**: `extract-images` diffs every GIM texture in `patched_data/`
  against `orig_data/` **per-image, not per-file** (a file with 8 icons
  where only 1 differs from the Japanese original only extracts that 1) and
  writes only the ones the English patch actually changed to
  `translations/images/<fileid>/<fileid>_<idx>_<w>x<h>.png` — currently 28
  images across 22 files, not the ~12,300 textures/icons/backgrounds in the
  whole game. This needs `orig_data/` to exist (run `extract-cpk` first). To
  translate one, save an edited copy next to it named
  `<fileid>_<idx>_<w>x<h>_translated.png` (same dimensions) — some of these
  render as white ink on a transparent background (this game's normal UI text
  style), so they'll look blank in a viewer with a white background; check
  the alpha channel, not just the RGB, before assuming one is empty. `apply`
  picks up every `_translated.png` it finds and injects it back at the
  original byte offset; anything without one is left untouched. A few images
  use pixel formats (Index16/Index32 — GIM format codes 6/7) that can be
  extracted for reference but not re-injected (no >256-colour quantization
  path); `apply` reports these separately if you try. The web app (`serve`)
  shows an **Images** category in the sidebar (`x/y` count, folded into the
  overall progress total) — open a file there to see each image's original
  next to its translation side by side, or a reminder that one's missing.
  It's a read-only comparison view, not an editor: translations still happen
  by saving the `_translated.png` file on disk, same as the CLI workflow.
- **Video**: `extract-videos` extracts only file `3691` — the TV series
  opening theme — to `translations/videos/intro.mp4`, video and audio both
  (see "PSMF video format" below for how the audio track is recovered; it's
  not something ffmpeg does out of the box).
  Reference/dub files for it live alongside the extraction:
  `intro_translated.mp4` (the edited video, kept for the record) and
  `intro_translated.at3` (raw ATRAC3+ audio, encoded externally — Sony's
  encoder is proprietary/Windows-only, no way around that) — this second
  file is what `apply` actually splices back in. Reinjection keeps the
  original H.264 video bytes 100% untouched and only replaces the audio's
  PES packets, rewrapped in the PSP-specific frame format (see "PSMF video
  format" below) — confirmed booting and playing correctly on real PPSSPP.
  `digimon_toolkit.psmf.splice_audio_into_psmf()` requires the new audio to
  fit the original's exact byte budget (no CPK resize support yet) and to
  use the same 744-byte ATRAC3+ frame size as this game's tracks; `apply`
  reports a size mismatch rather than silently skipping it. Requires
  `ffmpeg` on `PATH`.
- **Audio (BGM)**: `extract-audio` extracts only file `3693` track id `0` —
  the menu theme — to `translations/audio/menu_theme.wav`, decoded to plain
  PCM (see "AFS2 audio format" below). This track loops (see its `smpl`
  chunk / `digimon_toolkit.afs2.loop_points()`) from a **non-zero** sample,
  not from the start — dub the whole 0→end file 1:1 without retiming so the
  existing loop points still land correctly, and rebuild an equivalent
  `smpl` chunk with adjusted sample positions if the encoded result ends up
  a different length (`translations/audio/menu_theme_translated.at3` is
  literally what gets spliced in — including its `smpl` chunk, so build it
  correctly before handing it off). `apply` picks it up via
  `digimon_toolkit.afs2.splice_track_into_archive()`, which pads the new
  track to exactly fill its original archive slot — every other track in
  the archive is untouched. Confirmed booting and looping correctly on real
  PPSSPP. A track *larger* than its original slot needs the AFS2 archive's
  own offset table rebuilt (self-contained — only affects that one CPK
  entry) — not implemented; `apply` reports this rather than truncating
  anything.
  **Lesson learned the hard way**: ATRAC3+ is a transform codec with
  overlapping windows between frames — never trim frames from an already-
  encoded stream to hit a size budget; it corrupts the reconstruction of
  the frame(s) before the cut, producing audible noise right at the trim
  point. If new audio doesn't fit, shorten the *source* PCM before encoding
  (with margin — the encoder's own delay/lookahead padding means the
  output is a few frames longer than a naive sample-count estimate) and
  re-encode, don't touch the compressed output afterward.

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

The numeric IDs roughly map to the 54 anime episodes plus extra game-specific scenes.
These boundaries were verified in 2026-07 by reading actual dialog content (not
guessed from the ID range) — see `translations/progress.sh`'s `ARC_RANGES` for the
version this table must stay in sync with:

| File range | Content |
|------------|---------|
| 3520–3541 | Episodes 1–13 (Devimon arc). Devimon's defeat + Gennai's epilogue are the tail of 3541. |
| 3542–3547 | Episodes 14–20 (Etemon arc). Etemon dies in 3547. |
| 3548–3571 | Episodes 21–39 (Myotismon/VenomVamdemon arc). VenomVamdemon falls in 3571. |
| 3572–3584, 3611–3614 | Episodes 40–52 (Dark Masters arc). The four Dark Masters fall across 3572–3584; 3611–3614 are non-contiguous memorial/epilogue scenes for the same saga (Whamon's and Piccolomon's graves). |
| 3585–3586 | Episodes 53–54 (Apocalymon arc), including the series finale/epilogue. |
| 3587–3589 | *Digimon Adventure: Our War Game!* (the movie — not part of the 54-episode TV series). |
| 3590–3610 | Game-original side-quests/minigames with no anime tie-in. |
| 3615–3622 | Game-original bonus dungeon: a crossover gauntlet cameo-ing heroes from later Digimon series (02, Tamers, Frontier, Data Squad, Xros Wars). |

Note: files `3537` and `3601` don't exist — real gaps in the numbering, not extraction
errors. Several files are near-duplicate script branches for when the party splits
(e.g. `3531`/`3532`, `3533`/`3534`, `3527`/`3528`) — translate both, they diverge in
minor dialogue.

### Speaker IDs in dialog entries

Each dialog entry carries a `speaker_id` field (0–9), surfaced by the web app as `speaker`. This ID is extracted from the ESDF binary record table that precedes the text region in each file.

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

The dialog font is stored in **CPK file `3631`** as a raw binary (not GIM, not pBin).

| Property | Value |
|----------|-------|
| File | `patched_data/3631`, byte offset **29824** (= 0x7480) |
| Coverage | 192 chars, codes 0x20–0xDF |
| Format | 4bpp PSP Index4, 8 bytes/row × 16 rows = 128 bytes/glyph |
| Glyph lookup | `char_byte − 0x20` → array index → `index × 128` byte offset |

At runtime the game copies glyphs on demand into a 512×256 CLUT4 texture at PSP address 0x090E4900 (a dynamic glyph cache). The metrics table (beginning of file 3631) stores per-char width/height/slot used when building that cache.

**Accent character support** — seven ASCII slots are repainted as accented letters:

| Write in translation | Proxy byte | Renders as |
|:---:|:---:|:---:|
| á | `@` 0x40 | á |
| é | `#` 0x23 | é |
| í | `$` 0x24 | í |
| ó | `&` 0x26 | ó |
| ú | `*` 0x2A | ú |
| ñ | `_` 0x5F | ñ |
| ü | `=` 0x3D | ü |

`cli.py:cmd_apply()` remaps these automatically. **Do not use @, #, $, &, *, _, = literally in translations.**

UI text (buttons, menus, banners) is **baked into GIM textures** — see "Images & video" above for the extract/translate/apply pipeline.

### Image files the English patch actually changed

This is what `extract-images`' orig-vs-patched diff currently finds — 28
images across 22 files, identified by reading each one (not guessed from
file ID):

| File | Image(s) | Content |
|------|----------|---------|
| `0010` | 01, 02, 04 | Menu headers: ENTRY, EPISODE SELECTION, DUNGEON SELECTION |
| `0015` | 07 | Yes/No confirmation buttons |
| `0044` | 00, 01, 02 | Battle command: GUARD (multi-state icon) |
| `0045` | 01 | Battle command: FLEE |
| `0046` | 01 | Battle command: SKILL |
| `0047` | 01 | Battle command: ITEM |
| `0048` | 01 | Battle command: L/R button labels |
| `0049` | 01 | Battle command: EVOLVE |
| `0050` | 00, 01 | Battle command: ATTACK |
| `0069` | 05 | Dialog panel with character portraits |
| `0070` | 05 | Battle UI decorative lines |
| `0079` | 01 | Menu header: BATTLE RESULTS |
| `0089` | 01 | Menu header: MAIN MENU |
| `0104` | 01 | Menu header: PARTY |
| `0108` | 01, 03 | Menu headers: DIGIPIECE, ITEMS |
| `0114` | 01 | Menu header: LIBRARY |
| `0124` | 01 | Menu header: ITEMS |
| `0125` | 01 | Menu header: STATUS |
| `0126` | 12 | Battle HUD (HP / character name) — idx 12 is a "STRATEGY" label |
| `0130` | 01 | Menu header: OPTIONS |
| `0151` | 00 | RANK UP screen |
| `0156` | 04 | Startup logo sequence — **the "WARNING: unofficial translation, digimonadventurenglish.weebly.com" credit banner** (512×256); replace `0156_04_512x256_translated.png` with your own credit text/site to re-brand it |

Most of the 256×32 menu-header banners render as white ink with anti-aliased
alpha and no fill — they'll look blank against a plain white background;
open them over a dark/checkered background to actually see the text.

This list is a snapshot of the current English patch, not a hardcoded
allowlist — re-running `extract-images` re-diffs from scratch and picks up
anything a future patch version changes. The other ~2,330 files with GIM
textures in the game (icons, portraits, unmodified backgrounds) are left
alone; they were never touched by the English translation.

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

| Code | Name       | bpp | Inject support |
|------|------------|-----|-----------------|
| 0    | RGBA5650   | 16  | yes (direct pack, no palette) |
| 1    | RGBA5551   | 16  | yes (direct pack, no palette) |
| 2    | RGBA4444   | 16  | yes (direct pack, no palette) |
| 3    | RGBA8888   | 32  | yes (direct pack, no palette) |
| 4    | Index4     | 4   | yes (16-colour quantize) |
| 5    | Index8     | 8   | yes (256-colour quantize) |
| 6    | Index16    | 16  | extract only — no >256-colour quantization path |
| 7    | Index32    | 32  | extract only — no >256-colour quantization path |

Rare in this game (Index16/32 together are ~4.5% of all images, mostly
particle/smoke-style textures) — `gim_info_to_png` handles all eight for
extraction; `png_to_gim_pixels` handles 0–5 for re-injection.

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

### PSMF video format

Cutscenes (`patched_data/3634`–`3691`, 58 files) are Sony **PSMF** containers
(magic `PSMF0015`), not CRI Sofdec despite living in a CRI CPK. Reference
implementation: `digimon_toolkit/psmf.py`.

| Offset | Field | Notes |
|--------|-------|-------|
| +0x00 | signature | 4 bytes, `"PSMF"` |
| +0x04 | version | 4 ASCII digits, e.g. `"0015"` |
| +0x08 | data_offset | u32 **big-endian** — byte offset where the payload starts (2048 in every file in this game) |

The payload from `data_offset` onward is a standard **MPEG Program Stream**
(starts with pack header `0x000001BA`) — video is H.264 PES stream_id `0xE0`
(480×272), which `ffmpeg -f mpeg -i - -c copy` demuxes natively.

Audio is Sony ATRAC3+ carried as PES stream_id `0xBD` (private_stream_1) —
**ffmpeg's generic MPEG-PS demuxer never surfaces this as a stream at all**
(it only knows the DVD-style AC3/DTS/LPCM private_stream_1 convention, not
Sony's PSP-specific one), so getting audio out takes two extra parsing
layers on top of the standard PES header, both confirmed against PPSSPP's
own working demuxer (`Core/HW/MpegDemux.cpp` — not guessed, since a real,
shipping emulator has to get this exactly right or movies wouldn't play):

1. **PES sub-header** — each `0xBD` packet has a 1-byte channel id after the
   standard PES header, then 3 more sub-header bytes (4 if channel is
   `0xB0`–`0xBF`), before the actual payload.
2. **Frame-wrapper layer** — concatenating those payloads yields a stream of
   PSP-specific wrappers: 2-byte sync word `0x0F 0xD0`, then 2 code bytes
   where `wrapper_size = (((code1&3)<<8) | code2*8) + 16`; the real ATRAC3+
   frame is `wrapper[8:]`.

The concatenated raw ATRAC3+ frames are wrapped in a minimal synthetic Sony
OMA (`.oma`) header (96 bytes: `"EA3"` + zero + size 96 + unencrypted marker
+ `OMA_CODECID_ATRAC3P` + a 3-byte `codec_params` field encoding sample rate
index, channel id, and frame size — layout from FFmpeg's own
`libavformat/oma.h`/`omadec.c`) so ffmpeg's built-in `atrac3plus` **decoder**
can read it — decoding ATRAC3+ is open-source/reverse-engineered and ships in
stock ffmpeg; only the **encoder** is Sony's proprietary Windows-only tool.
Every PSP movie uses 44.1kHz stereo (PPSSPP hardcodes this — no per-file
codec detection), so those parameters are fixed, not detected per file.

`digimon_toolkit/psmf.py` implements both layers and muxes the result:
video stream-copied losslessly, audio decoded and re-encoded to AAC (not a
valid MP4 codec otherwise). If audio extraction fails for a given file for
any reason, it falls back to video-only rather than losing the video too.

### AFS2 audio format

BGM tracks (`patched_data/3693`, `3840`, ...) are CRI **AFS2** archives
(magic `"AFS2"`) — a flat table of `(track_id → byte range)` followed by
the tracks themselves, each a self-contained RIFF file wrapping raw
ATRAC3+ (no PSP-movie 8-byte frame wrapper here — this is the "plain" Sony
WAVE-for-ATRAC3+ format, decodable by ffmpeg directly). Header layout
confirmed against vgmstream's reference reader (`src/meta/awb.c`,
github.com/vgmstream/vgmstream — AFS2/AWB is the same format under two
names):

| Offset | Field | Notes |
|--------|-------|-------|
| +0x00 | signature | 4 bytes, `"AFS2"` |
| +0x05 | offset_size | u8 — byte width of each offset table entry (4 or 2) |
| +0x06 | waveid_alignment | u16 LE — byte width of each id table entry (usually 2) |
| +0x08 | total_subsongs | s32 LE |
| +0x0C | offset_alignment | u16 LE — offsets round up to this boundary |
| +0x10 | id table | `total_subsongs × waveid_alignment` bytes |
| ... | offset table | `(total_subsongs + 1) × offset_size` bytes (last entry = archive end) |

Some tracks carry a RIFF `smpl` chunk with an explicit loop **that doesn't
start at sample 0** — `digimon_toolkit/afs2.py:loop_points()` reads it
directly (standard RIFF `smpl` layout: 9-field header, then one 6-field
loop record with `start`/`end` sample offsets). The menu theme's loop is
8.98s→81.73s with an 8.98s one-time lead-in before it — get this wrong when
dubbing and the loop still cuts at the same sample, just against different
audio.

### Character encoding

ESDF text is encoded as Latin-1 single bytes. The `apply` command:
1. Remaps supported accented chars to their proxy ASCII codes (á→0x40, é→0x23, etc.)
2. Strips unsupported accented chars to their ASCII base (à→a, â→a, etc.)

Translations should use the real Unicode characters (á, ñ, etc.); the remapping happens automatically.

### Font atlas editing

`translations/font_atlas.png` is the source of truth for all 192 glyphs.

```bash
python digimon_toolkit/font_tool.py extract        # regenerate atlas from current font
# edit translations/font_atlas.png (96×96 px per cell, alpha = ink intensity)
python digimon_toolkit/font_tool.py import-atlas   # write atlas back to patched_data/3631
# or just run build-iso.sh — it imports the atlas automatically
```

**Critical:** atlas background must be fully transparent (alpha=0). Any non-zero alpha in empty areas will render as ink.

### System requirements

- Python 3.8+
- `xdelta3` (for patch generation): `brew install xdelta` / `apt install xdelta3`
- `ffmpeg` (for video extraction): `brew install ffmpeg` / `apt install ffmpeg`

### Output files

| File | Description |
|------|-------------|
| `output/Digimon Adventure (Translated).iso` | Full playable ISO for testing in PPSSPP |
| `output/translation_patch.xdelta` | Distributable patch applied over the original Japanese ISO |
