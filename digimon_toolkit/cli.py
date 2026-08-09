#!/usr/bin/env python3
"""
Digimon Adventure PSP - Translation Toolkit CLI
================================================

Commands:
    python digimon_toolkit/cli.py extract-cpk               Extract both CPKs (deduplicated)
    python digimon_toolkit/cli.py extract-text               Extract ALL text to JSON (includes speaker_id)
    python digimon_toolkit/cli.py extract-images             Extract GIM images changed vs. Japanese to translations/images/
    python digimon_toolkit/cli.py extract-videos             Extract the TV opening (video+audio) to translations/videos/intro.mp4
    python digimon_toolkit/cli.py extract-audio               Extract the menu theme to translations/audio/menu_theme.wav
    python digimon_toolkit/cli.py extract-all                Full extraction (cpk + text + images + videos + audio)
    python digimon_toolkit/cli.py progress                   Show translation progress stats
    python digimon_toolkit/cli.py apply                      Apply translations + image edits → build ISO+patch
    python digimon_toolkit/cli.py serve                      Launch the translation web UI at http://localhost:5174
"""
import sys, os, json, re, shutil, subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from digimon_toolkit.cpk import CPKArchive
from digimon_toolkit.pbin import parse_pbin
from digimon_toolkit.esdf import extract_esdf_bin, parse_english_esdf_texts, texts_to_json, replace_text_in_pbin
from digimon_toolkit.psp_image import extract_all_gim, gim_info_to_png, inject_image_into_file
from digimon_toolkit.psmf import is_psmf, extract_psmf_to_mp4, splice_audio_into_psmf
from digimon_toolkit.afs2 import is_afs2, extract_track as afs2_extract_track, decode_riff_to_wav, splice_track_into_archive
from digimon_toolkit.eboot_patcher import build_eboot_full_json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG_CPK = os.path.join(BASE, 'orig_iso/PSP_GAME/USRDIR/FILEDATA.CPK')
PATCH_CPK = os.path.join(BASE, 'patched_iso/PSP_GAME/USRDIR/FILEDATA.CPK')
ORIG_DIR = os.path.join(BASE, 'orig_data')
PATCH_DIR = os.path.join(BASE, 'patched_data')
TRANS = os.path.join(BASE, 'translations')
OUT = os.path.join(BASE, 'output')
PATCHED_ISO = os.path.join(BASE, '3161 - Digimon Adventure (Japan) - English Patch 1.2.iso')
ORIG_ISO = os.path.join(BASE, '3161 - Digimon Adventure (Japan).iso')
CPK_ISO_OFF = 56171 * 2048


def unique_files(cpk):
    seen = set()
    uniq = []
    for e in cpk.files:
        k = (e.file_offset, e.file_size)
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq


# ═════════════════════════════════════════════════════════
# EXTRACT
# ═════════════════════════════════════════════════════════

def cmd_extract_cpk():
    for label, src, dst in [("Original", ORIG_CPK, ORIG_DIR), ("Patched", PATCH_CPK, PATCH_DIR)]:
        print(f"Extracting {label} CPK...")
        cpk = CPKArchive(src); cpk.load()
        with open(src, 'rb') as f: data = f.read()
        os.makedirs(dst, exist_ok=True)
        for e in unique_files(cpk):
            if not e.file_name or e.file_size == 0: continue
            try:
                c = cpk.extract_file(data, e)
                with open(os.path.join(dst, str(e.file_name)), 'wb') as f: f.write(c)
            except: pass
        print(f"  → {dst}/")

    for f in ['EBOOT.BIN','OPNSSMP.BIN','PARAM.SFO','ICON0.PNG','PIC1.PNG']:
        s = os.path.join(BASE, f'patched_iso/PSP_GAME/SYSDIR/{f}' if f in ('EBOOT.BIN','OPNSSMP.BIN','PARAM.SFO') else f'patched_iso/PSP_GAME/{f}')
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(PATCH_DIR, f'_{f}'))


def cmd_extract_text():
    os.makedirs(TRANS, exist_ok=True)

    # ── A) Dialog from ESDF ──
    for sub, has_dialog in [('dialog', True), ('other', False)]:
        d = os.path.join(TRANS, sub); os.makedirs(d, exist_ok=True)
        n = 0
        for fn in sorted(os.listdir(PATCH_DIR)):
            if fn.startswith('_'): continue
            with open(os.path.join(PATCH_DIR, fn), 'rb') as f: data = f.read()
            ed = extract_esdf_bin(data)
            if not ed:
                if data[:4] == b'TXTD':
                    ed = data
                else:
                    continue
            blk = parse_english_esdf_texts(ed)
            if blk.text_count == 0: continue
            diag = sum(1 for e in blk.entries if ' ' in e.text and len(e.text) > 15)
            if has_dialog and diag == 0: continue
            if not has_dialog and diag > 0: continue
            jd = texts_to_json(blk, fn)
            with open(os.path.join(d, f'{fn}.json'), 'w', encoding='utf-8') as f: json.dump(jd, f, indent=2, ensure_ascii=False)
            n += 1
        print(f"  {n} files → translations/{sub}/")

    # ── B) EVERYTHING from EBOOT.BIN ──
    eb = os.path.join(PATCH_DIR, '_EBOOT.BIN')
    if os.path.exists(eb):
        with open(eb, 'rb') as f: ed = f.read()
        eboot_data = build_eboot_full_json(ed)
        
        os.makedirs(os.path.join(TRANS, 'names'), exist_ok=True)
        nd = {"source": "EBOOT.BIN", "character_names": eboot_data['names']['character'],
              "digimon_names": eboot_data['names']['digimon']}
        with open(os.path.join(TRANS, 'names', 'names.json'), 'w', encoding='utf-8') as f:
            json.dump(nd, f, indent=2, ensure_ascii=False)
        print(f"  {len(nd['character_names']) + len(nd['digimon_names'])} names → translations/names/")
        
        # Dump ALL other categories
        eboot_dir = os.path.join(TRANS, 'eboot')
        os.makedirs(eboot_dir, exist_ok=True)
        total_eboot = 0
        for cat in ['episode_menu', 'field_guide', 'battle_tutorial',
                     'evolution_stats', 'items', 'skills_attacks',
                     'skill_descriptions', 'ui_other']:
            items = eboot_data.get(cat, [])
            if not items: continue
            out = {"source": f"EBOOT.BIN/{cat}", "strings": items}
            with open(os.path.join(eboot_dir, f'{cat}.json'), 'w', encoding='utf-8') as f:
                json.dump(out, f, indent=2, ensure_ascii=False)
            total_eboot += len(items)
        print(f"  {total_eboot} strings → translations/eboot/ (in {len([k for k in eboot_data if k not in ('source','names')])} categories)")


def cmd_extract_images():
    """
    Extract GIM images the English patch actually changed, to
    translations/images/<fileid>/. Diffs per-image (not per-file) against
    orig_data/ — a file with 8 icons where only 1 was localized only
    extracts that 1, so this stays limited to genuinely translatable content
    instead of every texture/icon/background in the game.
    Never overwrites an existing '*_translated.png' — safe to re-run.
    """
    if not os.path.exists(ORIG_DIR):
        print("  orig_data/ not found — run 'extract-cpk' first")
        return

    out_base = os.path.join(TRANS, 'images')
    os.makedirs(out_base, exist_ok=True)

    def _raw_key(info):
        pal = info.get('palette')
        return (info['pix_raw'], pal['raw_orig'] if pal else b'')

    files_with_images = 0
    total = 0
    skipped = 0
    for fn in sorted(os.listdir(PATCH_DIR)):
        if fn.startswith('ID') or fn.startswith('_'):
            continue
        fpath = os.path.join(PATCH_DIR, fn)
        if not os.path.isfile(fpath):
            continue
        with open(fpath, 'rb') as f:
            data = f.read()
        if b'MIG.00.1PSP' not in data:
            continue
        images = extract_all_gim(data)
        if not images:
            continue

        orig_path = os.path.join(ORIG_DIR, fn)
        orig_keys = []
        if os.path.exists(orig_path):
            with open(orig_path, 'rb') as f:
                orig_data = f.read()
            orig_keys = [_raw_key(i) for i in extract_all_gim(orig_data)]

        changed = [info for info in images
                   if info['idx'] >= len(orig_keys) or _raw_key(info) != orig_keys[info['idx']]]
        if not changed:
            continue

        fout = os.path.join(out_base, fn)
        os.makedirs(fout, exist_ok=True)
        files_with_images += 1
        for info in changed:
            out_path = os.path.join(fout, f'{fn}_{info["idx"]:02d}_{info["width"]}x{info["height"]}.png')
            if os.path.exists(out_path):
                total += 1
                continue
            png = gim_info_to_png(info)
            if png:
                with open(out_path, 'wb') as f:
                    f.write(png)
                total += 1
            else:
                skipped += 1
                print(f"    {fn}/img_{info['idx']:02d}  {info['width']}×{info['height']}  fmt={info['format']}  (could not decode — skipped)")

    print(f"  {total} changed images from {files_with_images} files → {out_base}/")
    if skipped:
        print(f"  {skipped} images skipped (undecodable)")


def cmd_extract_videos():
    """
    Extract the TV series opening (file 3691, the only cutscene actually
    worth translating right now) to translations/videos/intro.mp4. Video is
    stream-copied losslessly; audio (ATRAC3+) is decoded and re-encoded to
    AAC since ATRAC3+ isn't a valid MP4 codec.
    """
    out_base = os.path.join(TRANS, 'videos')
    os.makedirs(out_base, exist_ok=True)

    fid = '3691'
    fpath = os.path.join(PATCH_DIR, fid)
    if not os.path.exists(fpath):
        print(f"  {fid} not found — run 'extract-cpk' first")
        return
    with open(fpath, 'rb') as f:
        data = f.read()
    if not is_psmf(data):
        print(f"  {fid} is not a PSMF file")
        return

    out_path = os.path.join(out_base, 'intro.mp4')
    if os.path.exists(out_path):
        print(f"  videos/intro.mp4 already exists")
        return
    try:
        extract_psmf_to_mp4(data, out_path)
        print(f"  {fid} → videos/intro.mp4")
    except Exception as e:
        print(f"  {fid}: FAILED ({e})")


def cmd_extract_audio():
    """
    Extract the menu theme (file 3693, AFS2 track id 0 — the only BGM track
    actually worth translating right now) to translations/audio/menu_theme.wav,
    decoded to plain PCM for reference/dubbing.
    """
    out_base = os.path.join(TRANS, 'audio')
    os.makedirs(out_base, exist_ok=True)

    fid, track_id = '3693', 0
    fpath = os.path.join(PATCH_DIR, fid)
    if not os.path.exists(fpath):
        print(f"  {fid} not found — run 'extract-cpk' first")
        return
    with open(fpath, 'rb') as f:
        data = f.read()
    if not is_afs2(data):
        print(f"  {fid} is not an AFS2 archive")
        return

    out_path = os.path.join(out_base, 'menu_theme.wav')
    if os.path.exists(out_path):
        print(f"  audio/menu_theme.wav already exists")
        return
    try:
        riff = afs2_extract_track(data, track_id)
        decode_riff_to_wav(riff, out_path)
        print(f"  {fid} track {track_id} → audio/menu_theme.wav")
    except Exception as e:
        print(f"  {fid} track {track_id}: FAILED ({e})")


def cmd_extract_all():
    for c in [cmd_extract_cpk, cmd_extract_text, cmd_extract_images, cmd_extract_videos, cmd_extract_audio]:
        c(); print()


# ═════════════════════════════════════════════════════════
# APPLY
# ═════════════════════════════════════════════════════════

def cmd_apply():
    os.makedirs(OUT, exist_ok=True)
    cpk = CPKArchive(PATCH_CPK); cpk.load()
    with open(PATCH_CPK, 'rb') as f: cpkd = bytearray(f.read())

    # Accented chars now have dedicated font slots (0x81–0x90).
    # These are remapped to those internal char codes instead of being stripped.
    # Chars NOT in this map fall through to the ASCII strip below.
    from digimon_toolkit.font_tool import ACCENT_MAP as _FONT_ACCENT_MAP, ACCENT_STRIP as _FONT_ACCENT_STRIP
    _ACCENT_REMAP = str.maketrans({ch: chr(slot) for ch, slot in _FONT_ACCENT_MAP.items()})

    # Remaining accents without dedicated slots → strip to ASCII
    _STRIP_MAP = str.maketrans(_FONT_ACCENT_STRIP)

    def strip_accents(text: str) -> str:
        """Remap supported accented chars to font slots; strip the rest."""
        return text.translate(_ACCENT_REMAP).translate(_STRIP_MAP)

    def prepare_texts(items):
        """Extract translations, tracking which changed. Strips accents automatically."""
        texts = []
        changed = False
        for it in items:
            orig = it.get('english', it.get('text', ''))
            trans = it.get('translation') or orig
            clean = strip_accents(trans)
            texts.append(clean)
            if clean != orig:
                changed = True
        return texts, changed

    def patch_file(fid, texts):
        """
        Patch a file in the CPK by its ID.
        Applies to BOTH the bare name (e.g. '3520') AND the ID-prefixed
        zero-padded variant (e.g. 'ID03520') so the English-patch files
        are always updated together with their originals.

        Bare and ID-prefixed names commonly alias the exact same
        (offset, size) region in the CPK. Each unique region is patched
        only once: patching it a second time would re-extract the
        already-translated bytes, re-parse them for entry offsets (which
        have shifted because the Spanish text is a different length than
        the English source), and overwrite at those wrong offsets —
        silently corrupting/shuffling dialog text.
        """
        try:
            padded_id = f'ID{int(fid):05d}'
        except ValueError:
            padded_id = None

        targets = {fid}
        if padded_id:
            targets.add(padded_id)
        # Also handle the non-zero-padded ID variant just in case
        targets.add(f'ID{fid}')

        patched_any = False
        seen_regions = set()
        for e in cpk.files:
            n = str(e.file_name)
            if n not in targets:
                continue
            region = (e.file_offset, e.file_size)
            if region in seen_regions:
                continue
            seen_regions.add(region)
            try:
                ck = cpk.extract_file(bytes(cpkd), e)
                nc = replace_text_in_pbin(ck, texts)
                if len(nc) == e.file_size:
                    cpkd[e.file_offset:e.file_offset+e.file_size] = nc
                else:
                    cpkd[e.file_offset:e.file_offset+len(nc)] = nc[:e.file_size]
                patched_any = True
            except:
                pass
        return patched_any

    # 1) Dialog files
    applied = 0
    for sub in ['dialog', 'other']:
        sd = os.path.join(TRANS, sub)
        if not os.path.exists(sd): continue
        for fn in sorted(os.listdir(sd)):
            if not fn.endswith('.json'): continue
            fid = fn[:-5]
            with open(os.path.join(sd, fn), 'r', encoding='utf-8') as f:
                td = json.load(f)
            nt, changed = prepare_texts(td.get('dialog', []))
            if not changed: continue
            if patch_file(fid, nt):
                print(f"  ✓ {sub}/{fn}")
                applied += 1

    def patch_image_file(fid):
        """
        If patched_data/<fid> differs from the CPK's stored version, inject it.
        Works for both the bare name and the ID-prefixed zero-padded variant.
        Used for the font file, which font_tool.py writes in-place (same size).
        """
        src = os.path.join(PATCH_DIR, fid)
        if not os.path.exists(src):
            return False
        with open(src, 'rb') as f:
            new_content = f.read()
        try:
            padded_id = f'ID{int(fid):05d}'
        except ValueError:
            padded_id = f'ID{fid}'
        targets = {fid, padded_id, f'ID{fid}'}
        patched_any = False
        for e in cpk.files:
            n = str(e.file_name)
            if n not in targets:
                continue
            orig = cpk.extract_file(bytes(cpkd), e)
            if orig == new_content:
                continue  # nothing changed, skip
            if len(new_content) != e.file_size:
                print(f"  ⚠ image/{fid}: size mismatch ({len(new_content)} vs {e.file_size}), skipping")
                continue
            cpkd[e.file_offset:e.file_offset + e.file_size] = new_content
            patched_any = True
        return patched_any

    # Font file — always inject patched_data/3631 (contains patched glyph slots)
    if patch_image_file('3631'):
        print(f"  ✓ font/3631")
    else:
        print(f"  · font/3631 (unchanged or not found)")

    # 2) UI/texture images — translations/images/<fid>/<fid>_<idx>_<w>x<h>.png
    # with a '<same>_translated.png' sibling. Untranslated ones are skipped
    # and counted below; nothing is required to have a translation.
    img_applied = img_skipped = img_failed = 0
    img_dir = os.path.join(TRANS, 'images')
    if os.path.exists(img_dir):
        for fid in sorted(os.listdir(img_dir)):
            fid_dir = os.path.join(img_dir, fid)
            if not os.path.isdir(fid_dir):
                continue
            base_pngs = sorted(f for f in os.listdir(fid_dir)
                                if f.endswith('.png') and not f[:-4].endswith('_translated'))
            edits = []
            for fn in base_pngs:
                stem = fn[:-4]
                translated = os.path.join(fid_dir, f'{stem}_translated.png')
                if not os.path.exists(translated):
                    img_skipped += 1
                    continue
                m = re.match(rf'{re.escape(fid)}_(\d+)_\d+x\d+$', stem)
                if not m:
                    img_failed += 1
                    print(f"  ⚠ images/{fid}: unrecognised filename {fn}, skipping")
                    continue
                edits.append((int(m.group(1)), translated))
            if not edits:
                continue

            try:
                padded_id = f'ID{int(fid):05d}'
            except ValueError:
                padded_id = f'ID{fid}'
            targets = {fid, padded_id, f'ID{fid}'}
            matches = [e for e in cpk.files if str(e.file_name) in targets]
            if not matches:
                print(f"  ⚠ images/{fid}: not found in CPK, skipping")
                img_failed += len(edits)
                continue

            content = cpk.extract_file(bytes(cpkd), matches[0])
            file_applied = 0
            for img_idx, translated_path in edits:
                try:
                    content = inject_image_into_file(content, img_idx, translated_path)
                    file_applied += 1
                except Exception as exc:
                    img_failed += 1
                    print(f"  ⚠ images/{fid} img_{img_idx:02d}: {exc}")

            if file_applied:
                seen_regions = set()
                for e in matches:
                    region = (e.file_offset, e.file_size)
                    if region in seen_regions:
                        continue
                    seen_regions.add(region)
                    if len(content) == e.file_size:
                        cpkd[e.file_offset:e.file_offset + e.file_size] = content
                    else:
                        cpkd[e.file_offset:e.file_offset + len(content)] = content[:e.file_size]
                print(f"  ✓ images/{fid} ({file_applied} translated)")
                img_applied += file_applied

    # 3) Video/audio — translations/videos/intro_translated.at3 (splices into
    # the PSMF's audio, video untouched) and translations/audio/menu_theme_translated.at3
    # (fills the AFS2 track's slot, other tracks untouched). Same-size-budget
    # splices only — no CPK resize support yet — so anything that doesn't
    # fit is reported, not silently dropped.
    def patch_cpk_entry(fid, new_content):
        try:
            padded_id = f'ID{int(fid):05d}'
        except ValueError:
            padded_id = f'ID{fid}'
        targets = {fid, padded_id, f'ID{fid}'}
        matches = [e for e in cpk.files if str(e.file_name) in targets]
        if not matches:
            print(f"  ⚠ {fid}: not found in CPK, skipping")
            return False
        ok = False
        seen_regions = set()
        for e in matches:
            region = (e.file_offset, e.file_size)
            if region in seen_regions:
                continue
            seen_regions.add(region)
            if len(new_content) != e.file_size:
                print(f"  ⚠ {fid}: size mismatch ({len(new_content)} vs {e.file_size}), skipping")
                continue
            cpkd[e.file_offset:e.file_offset + e.file_size] = new_content
            ok = True
        return ok

    av_applied = 0

    intro_at3 = os.path.join(TRANS, 'videos', 'intro_translated.at3')
    if os.path.exists(intro_at3):
        orig_entry = next((e for e in cpk.files if str(e.file_name) == '3691'), None)
        with open(intro_at3, 'rb') as f:
            new_riff = f.read()
        try:
            if orig_entry is None:
                raise ValueError("3691 not found in CPK")
            orig_3691 = cpk.extract_file(bytes(cpkd), orig_entry)
            new_3691 = splice_audio_into_psmf(orig_3691, new_riff)
            if patch_cpk_entry('3691', new_3691):
                print(f"  ✓ videos/intro_translated.at3 → 3691")
                av_applied += 1
        except Exception as e:
            print(f"  ⚠ videos/intro_translated.at3: {e}")

    menu_at3 = os.path.join(TRANS, 'audio', 'menu_theme_translated.at3')
    if os.path.exists(menu_at3):
        orig_entry = next((e for e in cpk.files if str(e.file_name) == '3693'), None)
        with open(menu_at3, 'rb') as f:
            new_track = f.read()
        try:
            if orig_entry is None:
                raise ValueError("3693 not found in CPK")
            orig_3693 = cpk.extract_file(bytes(cpkd), orig_entry)
            new_3693 = splice_track_into_archive(orig_3693, 0, new_track)
            if patch_cpk_entry('3693', new_3693):
                print(f"  ✓ audio/menu_theme_translated.at3 → 3693")
                av_applied += 1
        except Exception as e:
            print(f"  ⚠ audio/menu_theme_translated.at3: {e}")

    # ── Build ISO ──
    iso_out = os.path.join(OUT, 'Digimon Adventure (Translated).iso')
    print(f"\nBuilding ISO...")
    shutil.copy2(PATCHED_ISO, iso_out)
    with open(iso_out, 'r+b') as f:
        f.seek(CPK_ISO_OFF)
        f.write(bytes(cpkd))
    print(f"  ✓ {iso_out} ({os.path.getsize(iso_out)/1024/1024:.0f} MB)")

    # 3) EBOOT names — must run AFTER the ISO is written so it isn't overwritten
    names_file = os.path.join(TRANS, 'names', 'names.json')
    eboot_path = os.path.join(PATCH_DIR, '_EBOOT.BIN')
    if os.path.exists(names_file) and os.path.exists(eboot_path):
        with open(names_file, 'r', encoding='utf-8') as f: nd = json.load(f)
        # Find where EBOOT.BIN starts in the ISO by scanning for ELF magic at
        # 2048-byte sector boundaries. EBOOT is near the start of the image so
        # reading 50 MB is more than enough.
        eboot_iso_off = -1
        with open(PATCHED_ISO, 'rb') as fi:
            scan_data = fi.read(50 * 1024 * 1024)
        for sector in range(len(scan_data) // 2048):
            if scan_data[sector * 2048: sector * 2048 + 4] == b'\x7fELF':
                eboot_iso_off = sector * 2048
                break
        if eboot_iso_off < 0:
            print(f"  ⚠ EBOOT.BIN not found in ISO — names not patched")
        else:
            with open(eboot_path, 'rb') as f: eboot = bytearray(f.read())

            _EBOOT_SJIS = {
                '○': b'\x81\x9b', '×': b'\x81\x7e', '□': b'\x81\xa0',
                '→': b'\x81\xa8', '←': b'\x81\xa9', '↑': b'\x81\xaa', '↓': b'\x81\xab',
            }

            def _encode_eboot(text: str) -> bytes:
                out = b''
                for ch in text:
                    out += _EBOOT_SJIS[ch] if ch in _EBOOT_SJIS else ch.encode('latin-1', errors='replace')
                return out

            def _patch_eboot_item(item, orig_key='name'):
                offset = item.get('_offset', -1)
                length = item.get('_length', 0)
                if offset < 0 or length <= 0:
                    return 0
                orig = item.get(orig_key, '')
                trans = strip_accents(item.get('translation', orig))
                if not trans:
                    return 0
                tb = _encode_eboot(trans)
                if len(tb) > length:
                    tb = tb[:length]
                eboot[offset:offset + len(tb)] = tb
                if len(tb) < length:
                    eboot[offset + len(tb):offset + length] = b'\x00' * (length - len(tb))
                return 1

            patched = 0
            for cat in ['character_names', 'digimon_names']:
                for item in nd.get(cat, []):
                    patched += _patch_eboot_item(item, orig_key='name')

            # Patch eboot string files (skill descriptions, attack names, etc.)
            eboot_dir = os.path.join(TRANS, 'eboot')
            if os.path.exists(eboot_dir):
                for fn in sorted(os.listdir(eboot_dir)):
                    if not fn.endswith('.json'): continue
                    with open(os.path.join(eboot_dir, fn), 'r', encoding='utf-8') as f:
                        edata = json.load(f)
                    file_patched = 0
                    for item in edata.get('strings', []):
                        file_patched += _patch_eboot_item(item, orig_key='text')
                    if file_patched:
                        patched += file_patched
                        print(f"  ✓ eboot/{fn} ({file_patched} strings)")

            if patched:
                with open(iso_out, 'r+b') as f:
                    f.seek(eboot_iso_off)
                    f.write(eboot)
            print(f"  ✓ {patched} EBOOT entries patched")

    # ── xdelta patch ──
    patch_out = os.path.join(OUT, 'translation_patch.xdelta')
    print(f"Creating xdelta patch...")
    subprocess.run(['xdelta3', '-f', '-e', '-s', ORIG_ISO, iso_out, patch_out], capture_output=True, timeout=600)
    if os.path.exists(patch_out):
        print(f"  ✓ {patch_out} ({os.path.getsize(patch_out)/1024/1024:.0f} MB)")

    print(f"\nImages: {img_applied} translated & applied, {img_skipped} extracted-but-not-yet-translated"
          + (f", {img_failed} failed" if img_failed else ""))
    print(f"Video/audio: {av_applied}/2 translated & applied (intro, menu theme)")

    print(f"\nOutput files:")
    for f in sorted(os.listdir(OUT)):
        sz = os.path.getsize(os.path.join(OUT, f))
        print(f"  {f}: {sz/1024/1024:.1f} MB" if sz > 1e6 else f"  {f}: {sz/1024:.1f} KB")


def cmd_serve():
    import webbrowser, threading, signal
    webapp_dir = os.path.join(BASE, 'webapp')

    if not os.path.exists(webapp_dir):
        print("Error: webapp/ not found. Clone the full repository.")
        return

    if shutil.which('npm') is None:
        print("Error: npm not found. Install Node.js 18+ from https://nodejs.org/")
        return

    # Kill any stale process holding port 5174
    try:
        r = subprocess.run(['lsof', '-ti', ':5174'], capture_output=True, text=True)
        for pid in r.stdout.split():
            subprocess.run(['kill', pid.strip()], capture_output=True)
    except Exception:
        pass

    if not os.path.exists(os.path.join(webapp_dir, 'node_modules')):
        print("Installing webapp dependencies (first run only)…")
        subprocess.run(['npm', 'install'], cwd=webapp_dir, check=True)

    from digimon_toolkit.server import run
    threading.Thread(target=run, kwargs={'port': 5174}, daemon=True).start()

    print("Translation Helper → http://localhost:5173")
    threading.Timer(2.0, lambda: webbrowser.open('http://localhost:5173')).start()

    vite = subprocess.Popen(['npm', 'run', 'dev'], cwd=webapp_dir)
    try:
        vite.wait()
    except KeyboardInterrupt:
        vite.terminate()
        vite.wait()


def cmd_progress():
    """Show translation progress by reading translations/*.json directly."""
    from digimon_toolkit.server import _file_progress

    categories = []  # (label, done, total)
    files_done = files_total = 0

    dialog_dir = os.path.join(TRANS, 'dialog')
    if os.path.exists(dialog_dir):
        done = total = 0
        for fn in sorted(os.listdir(dialog_dir)):
            if not fn.endswith('.json') or fn.startswith('ID'):
                continue
            with open(os.path.join(dialog_dir, fn), 'r', encoding='utf-8') as f:
                entries = json.load(f).get('dialog', [])
            d, t = _file_progress(entries, 'translation')
            done += d; total += t
            files_total += 1
            if t and d == t:
                files_done += 1
        categories.append(('Dialog', done, total))

    eboot_dir = os.path.join(TRANS, 'eboot')
    if os.path.exists(eboot_dir):
        done = total = 0
        for fn in sorted(os.listdir(eboot_dir)):
            if not fn.endswith('.json'):
                continue
            with open(os.path.join(eboot_dir, fn), 'r', encoding='utf-8') as f:
                strings = json.load(f).get('strings', [])
            d, t = _file_progress(strings, 'translation')
            done += d; total += t
        categories.append(('EBOOT', done, total))

    names_path = os.path.join(TRANS, 'names', 'names.json')
    if os.path.exists(names_path):
        with open(names_path, 'r', encoding='utf-8') as f:
            nd = json.load(f)
        all_names = nd.get('character_names', []) + nd.get('digimon_names', [])
        done, total = _file_progress(all_names, 'translation')
        categories.append(('Names', done, total))

    other_dir = os.path.join(TRANS, 'other')
    if os.path.exists(other_dir):
        done = total = 0
        for fn in sorted(os.listdir(other_dir)):
            if not fn.endswith('.json') or fn.startswith('ID'):
                continue
            with open(os.path.join(other_dir, fn), 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get('skip'):
                continue
            d, t = _file_progress(data.get('dialog', []), 'translation')
            done += d; total += t
        categories.append(('UI / other', done, total))

    total_done = sum(d for _, d, _ in categories)
    total_all = sum(t for _, _, t in categories)
    if total_all == 0:
        print("  No translation files found — run 'extract-text' first.")
        return

    print(f"\n  Translation progress:")
    for label, done, total in categories:
        pct = round(100 * done / total, 1) if total else 0.0
        print(f"    {label:<12} {done}/{total} ({pct}%)")

    pct = round(100 * total_done / total_all, 1)
    bar_len = 40
    filled = int(bar_len * total_done / total_all)
    bar = '█' * filled + '░' * (bar_len - filled)
    print(f"    {'Total':<12} {total_done}/{total_all} ({pct}%)")
    print(f"    [{bar}]")
    if files_total:
        print(f"    Dialog files complete: {files_done}/{files_total}")


def main():
    cmd = sys.argv[1] if len(sys.argv) >= 2 else ''

    cmds = {
        'extract-cpk':    cmd_extract_cpk,
        'extract-text':   cmd_extract_text,
        'extract-images': cmd_extract_images,
        'extract-videos': cmd_extract_videos,
        'extract-audio':  cmd_extract_audio,
        'extract-all':    cmd_extract_all,
        'progress':       cmd_progress,
        'apply':          cmd_apply,
        'serve':          cmd_serve,
    }
    if cmd not in cmds:
        print(__doc__)
        return
    cmds[cmd]()

if __name__ == '__main__':
    main()
