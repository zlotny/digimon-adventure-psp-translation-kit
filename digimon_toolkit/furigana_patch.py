#!/usr/bin/env python3
"""
Furigana test patcher for Digimon Adventure PSP.

Patches dialog file 3520's first entry to use furigana rendering.
Tests the {n|~} markup → n + ff 41 + ~ + ff 00 → n with tilde above (ñ).
"""
import struct, os, sys

def patch_iso(iso_path: str) -> bool:
    cpk_off = 56171 * 2048  # CPK offset in ISO
    
    with open(iso_path, 'rb') as f:
        f.seek(cpk_off)
        cpk_data = bytearray(f.read(60000000))
    
    # Find the text in the CPK dump
    search = b"During the summer of that year,\nstrange"
    idx = cpk_data.find(search)
    if idx < 0:
        print("ERROR: Could not find target text in CPK")
        return False
    
    old = cpk_data[idx:idx+71]
    print(f"Original text ({len(old)} bytes):")
    print(f"  {old[:70].decode('ascii', errors='replace')!r}")
    
    # Build new text that fits in 71 bytes:
    # Original: "During the summer of that year,\nstrange events happened all over\nEarth." (70 chars + null)
    # New: same but "Ear{n|~}." → E a r n ff 41 ~ ff 00 . (11 bytes for "Earn~.")
    # Shorten line 2 to compensate: "happened all over" → "over" saves 16 bytes waste...
    # Let's be smarter: just shorten line 1 a bit
    
    line1 = b"During the summer of that year,\n"  # 31 bytes
    line2 = b"strange events all over\n"           # 24 bytes (saves "happened " = 10)
    prefix = b"Ear"                                 # 3 bytes
    furi = b"n\xff\x41~\xff\x00"                   # 6 bytes (n + ff 41 + ~ + ff 00)
    # Total: 31+24+3+6 = 64, we need 71
    # Pad with zeros to fill the slot
    padding = b"\x00" * (71 - 64)  # 7 null bytes
    
    new = line1 + line2 + prefix + furi + padding
    assert len(new) == 71, f"Expected 71 bytes, got {len(new)}"
    
    print(f"\nNew text ({len(new)} bytes):")
    # Show as much as decodable
    try:
        print(f"  {new[:58].decode('ascii')!r} + [furigana] + [padding]")
    except:
        pass
    print(f"  Full hex: {' '.join(f'{b:02x}' for b in new)}")
    print(f"  Furigana section (bytes 55-61): {' '.join(f'{b:02x}' for b in new[55:62])}")
    print(f"  → Base char: {new[58:59]!r} ({chr(new[58])}) + ff 41 + tilde ({chr(new[60])}) + ff 00")
    
    # Verify furigana markers are present
    assert b"\xff\x41" in new, "Missing ff 41 marker!"
    assert b"\xff\x00" in new, "Missing ff 00 terminator!"
    
    # Patch
    cpk_data[idx:idx+71] = new
    
    # Verify
    verify = cpk_data[idx:idx+71]
    assert b"\xff\x41" in verify, "ff 41 not in patched data!"
    assert verify[:10] == b"During the", "Patch verification failed!"
    
    # Write back to ISO
    with open(iso_path, 'r+b') as f:
        f.seek(cpk_off)
        f.write(bytes(cpk_data))
    
    print(f"\n✓ Successfully patched {iso_path}")
    print(f"\nFURIGANA TEST SUMMARY:")
    print(f"  Entry: index 0 of file 3520/ID03520 (first dialog line)")
    print(f"  Original: \"During the summer...all over\\nEarth.\"")
    print(f"  Patched:  \"During the summer...all over\\nEar\" + [n with ~ above]")
    print(f"  Mechanism: n (0x6E) + ff 41 marker + ~ (0x7E) + ff 00 end")
    print(f"  Expected: 'n' renders with tilde '~' above it = ñ approximation")
    print(f"\n  To test in PPSSPP: Load the ISO and start a new game.")
    print(f"  The first dialog box should show the modified text.")
    print(f"  If furigana works, 'n' will have '~' floating above it.")
    return True


if __name__ == '__main__':
    import sys
    iso = sys.argv[1] if len(sys.argv) > 1 else "output/Digimon Adventure (Translated).iso"
    patch_iso(iso)
