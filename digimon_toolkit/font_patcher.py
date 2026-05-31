#!/usr/bin/env python3
"""
EBOOT Font Patcher — Digimon Adventure PSP (English Patch)
===========================================================
Replaces the '~' glyph with a combining tilde (floating accent at top of cell).
Write 'n~' in dialog text to render as 'ñ'.

Usage:
    python digimon_toolkit/font_patcher.py                  # patch default ISO
    python digimon_toolkit/font_patcher.py path/to/iso      
    python digimon_toolkit/font_patcher.py path/to/iso --reset   # restore
    python digimon_toolkit/font_patcher.py path/to/iso --verify  # check status
"""

import sys, os

FONT_OFFSET = 136          # in EBOOT data segment
GLYPH_SIZE = 16            # 8x16 bitmap

# Combining tilde (wave at top rows 0-2)
COMB_TILDE = bytes([0x60,0x9C,0x06, 0,0,0,0,0, 0,0,0,0,0,0,0,0])
# Original tilde
ORIG_TILDE  = bytes([0x47,0x07,0,0x0C,0,0,0,0, 0xBC,0x91,0x02,0x0C,0,0,0,0])

def find_font(iso: bytes) -> int:
    n = iso.find(b'\x25\x28\x00\x00\x0b')  # 'n' glyph signature
    if n < 0: return -1
    return n - (0x6E - 0x20) * GLYPH_SIZE

def show_glyph(iso, font_off, code):
    off = font_off + (code - 0x20) * GLYPH_SIZE
    g = iso[off:off+GLYPH_SIZE]
    ch = chr(code) if 0x20 <= code < 0x7F else f'0x{code:02x}'
    print(f"  '{ch}':")
    for r in range(GLYPH_SIZE):
        v = ''.join('#' if (g[r]>>(7-c))&1 else ' ' for c in range(8))
        print(f"    +{r:2d} {g[r]:02x} {v}")

def patch(iso_path, use_combining=True):
    with open(iso_path, 'rb') as f:
        iso = bytearray(f.read())
    font_off = find_font(iso)
    if font_off < 0: print("ERROR: font not found"); return False
    tilde_off = font_off + (0x7E-0x20)*GLYPH_SIZE
    new_g = COMB_TILDE if use_combining else ORIG_TILDE
    iso[tilde_off:tilde_off+GLYPH_SIZE] = new_g
    with open(iso_path, 'wb') as f:
        f.write(iso)
    mode = "COMBINING TILDE" if use_combining else "ORIGINAL (restored)"
    print(f"OK - '~' set to {mode}")
    if use_combining:
        print("Then write 'n~' in dialog text to get ñ")
    return True

def verify(iso_path):
    with open(iso_path, 'rb') as f:
        iso = f.read()
    font_off = find_font(iso)
    if font_off < 0: print("ERROR: font not found"); return
    tilde_off = font_off + (0x7E-0x20)*GLYPH_SIZE
    tilde = iso[tilde_off:tilde_off+GLYPH_SIZE]
    if tilde == COMB_TILDE: print("PATCHED (combining tilde)")
    elif tilde == ORIG_TILDE: print("ORIGINAL (not patched)")
    else: print("UNKNOWN glyph")

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = set(a for a in sys.argv[1:] if a.startswith('--'))
    iso = args[0] if args else "output/Digimon Adventure (Translated).iso"
    if not os.path.exists(iso): print(f"ERROR: {iso} not found"); sys.exit(1)
    if '--verify' in flags: verify(iso)
    else: patch(iso, use_combining='--reset' not in flags)
