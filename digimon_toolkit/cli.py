#!/usr/bin/env python3
"""
Digimon Adventure PSP - Translation Toolkit CLI
================================================

Commands:
    python digimon_toolkit/cli.py extract-cpk               Extract both CPKs (deduplicated)
    python digimon_toolkit/cli.py extract-text               Extract ALL text to JSON (includes speaker_id)
    python digimon_toolkit/cli.py extract-images             Extract patched UI images to output/images/
    python digimon_toolkit/cli.py extract-image <id>         Extract images from a single file (e.g. 0156)
    python digimon_toolkit/cli.py inject-image <id> <N> <png>  Replace image N in file <id> with a PNG
    python digimon_toolkit/cli.py extract-all                Full extraction (cpk + text + images)
    python digimon_toolkit/cli.py to-csv                     Export dialog JSONs to CSV (translations/csv/)
    python digimon_toolkit/cli.py from-csv                   Import CSV translations back to JSON
    python digimon_toolkit/cli.py progress                   Show translation progress stats
    python digimon_toolkit/cli.py apply                      Apply translations + image edits → build ISO+patch
    python digimon_toolkit/cli.py serve                      Launch the translation web UI at http://localhost:5174
"""
import sys, os, json, struct, re, shutil, subprocess
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from digimon_toolkit.cpk import CPKArchive
from digimon_toolkit.pbin import parse_pbin
from digimon_toolkit.esdf import extract_esdf_bin, parse_english_esdf_texts, texts_to_json, replace_text_in_pbin
from digimon_toolkit.psp_image import extract_all_gim, gim_info_to_png, inject_image_into_file
from digimon_toolkit.eboot_patcher import build_eboot_full_json
from digimon_toolkit.csv_tools import json_dir_to_csv_dir, csv_dir_to_json_dir, stats as csv_stats

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
    """Extract all GIM images from the 11 patched image files to output/images/."""
    _PATCHED_IMAGE_IDS = [
        '0015', '0044', '0045', '0046', '0047', '0048',
        '0050', '0069', '0070', '0126', '0151', '0156',
    ]
    out_base = os.path.join(OUT, 'images')
    os.makedirs(out_base, exist_ok=True)

    total = 0
    for fid in _PATCHED_IMAGE_IDS:
        fpath = os.path.join(PATCH_DIR, fid)
        if not os.path.exists(fpath):
            print(f"  skip {fid} (not found)")
            continue
        with open(fpath, 'rb') as f:
            data = f.read()
        images = extract_all_gim(data)
        if not images:
            print(f"  skip {fid} (no GIM found)")
            continue
        fout = os.path.join(out_base, fid)
        os.makedirs(fout, exist_ok=True)
        for info in images:
            png = gim_info_to_png(info)
            if png:
                out_path = os.path.join(fout, f'img_{info["idx"]:02d}_{info["width"]}x{info["height"]}.png')
                with open(out_path, 'wb') as f:
                    f.write(png)
                print(f"    {fid}/img_{info['idx']:02d}  {info['width']}×{info['height']}  fmt={info['format']}")
                total += 1
            else:
                print(f"    {fid}/img_{info['idx']:02d}  {info['width']}×{info['height']}  fmt={info['format']}  (no PIL — skipped)")
    print(f"  {total} images → {out_base}/")


def cmd_extract_image(file_id: str):
    """Extract all images from a single patched_data/<file_id> file."""
    fpath = os.path.join(PATCH_DIR, file_id)
    if not os.path.exists(fpath):
        print(f"  File not found: {fpath}")
        return
    with open(fpath, 'rb') as f:
        data = f.read()
    images = extract_all_gim(data)
    if not images:
        print(f"  No GIM images found in {file_id}")
        return

    out_base = os.path.join(OUT, 'images', file_id)
    os.makedirs(out_base, exist_ok=True)
    for info in images:
        png = gim_info_to_png(info)
        if png:
            out_path = os.path.join(out_base, f'img_{info["idx"]:02d}_{info["width"]}x{info["height"]}.png')
            with open(out_path, 'wb') as f:
                f.write(png)
            print(f"  img_{info['idx']:02d}  {info['width']}×{info['height']}  fmt={info['format']}  → {out_path}")
        else:
            print(f"  img_{info['idx']:02d}  {info['width']}×{info['height']}  fmt={info['format']}  (Pillow not installed — no PNG)")

    print(f"  {len(images)} images found.")


def cmd_inject_image(file_id: str, img_idx: int, png_path: str):
    """
    Replace image img_idx in patched_data/<file_id> with the given PNG.
    Also updates the ID-prefixed variant (ID0XXXX).
    """
    fpath = os.path.join(PATCH_DIR, file_id)
    if not os.path.exists(fpath):
        print(f"  File not found: {fpath}")
        return
    if not os.path.exists(png_path):
        print(f"  PNG not found: {png_path}")
        return

    with open(fpath, 'rb') as f:
        data = f.read()

    try:
        new_data = inject_image_into_file(data, img_idx, png_path)
    except ValueError as e:
        print(f"  Error: {e}")
        return

    with open(fpath, 'wb') as f:
        f.write(new_data)
    print(f"  ✓ Injected img_{img_idx} into {fpath}")

    # Also update ID-prefixed variant
    try:
        padded = f'ID{int(file_id):05d}'
    except ValueError:
        padded = f'ID{file_id}'
    id_path = os.path.join(PATCH_DIR, padded)
    if os.path.exists(id_path):
        with open(id_path, 'rb') as f:
            id_data = f.read()
        new_id_data = inject_image_into_file(id_data, img_idx, png_path)
        with open(id_path, 'wb') as f:
            f.write(new_id_data)
        print(f"  ✓ Injected img_{img_idx} into {id_path}")


def cmd_extract_all():
    for c in [cmd_extract_cpk, cmd_extract_text, cmd_extract_images]:
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
    from digimon_toolkit.font_tool import ACCENT_MAP as _FONT_ACCENT_MAP
    _ACCENT_REMAP = str.maketrans({ch: chr(slot) for ch, slot in _FONT_ACCENT_MAP.items()})

    # Remaining accents without dedicated slots → strip to ASCII
    _STRIP_MAP = str.maketrans({
        'à': 'a', 'À': 'A', 'â': 'a', 'Â': 'A',
        'ä': 'a', 'Ä': 'A', 'ã': 'a', 'Ã': 'A', 'å': 'a', 'Å': 'A',
        'è': 'e', 'È': 'E', 'ê': 'e', 'Ê': 'E', 'ë': 'e', 'Ë': 'E',
        'ì': 'i', 'Ì': 'I', 'î': 'i', 'Î': 'I', 'ï': 'i', 'Ï': 'I',
        'ò': 'o', 'Ò': 'O', 'ô': 'o', 'Ô': 'O', 'ö': 'o', 'Ö': 'O', 'õ': 'o', 'Õ': 'O',
        'ù': 'u', 'Ù': 'U', 'û': 'u', 'Û': 'U',
        'ç': 'c', 'Ç': 'C', 'ý': 'y', 'Ý': 'Y', 'ÿ': 'y',
    })

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
        for e in cpk.files:
            n = str(e.file_name)
            if n not in targets:
                continue
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

    # 2) Modified image files (patched_data/<id> edited via inject-image)
    _IMAGE_IDS = [
        '0015', '0044', '0045', '0046', '0047', '0048',
        '0050', '0069', '0070', '0126', '0151', '0156',
    ]

    def patch_image_file(fid):
        """
        If patched_data/<fid> differs from the CPK's stored version, inject it.
        Works for both the bare name and the ID-prefixed zero-padded variant.
        inject-image writes in-place so the sizes always match.
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

    img_applied = 0
    for fid in _IMAGE_IDS:
        if patch_image_file(fid):
            print(f"  ✓ image/{fid}")
            img_applied += 1

    # 2b) Font file — always inject patched_data/3631 (contains patched glyph slots)
    if patch_image_file('3631'):
        print(f"  ✓ font/3631")
    else:
        print(f"  · font/3631 (unchanged or not found)")

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

            def _patch_eboot_item(item, orig_key='name'):
                offset = item.get('_offset', -1)
                length = item.get('_length', 0)
                if offset < 0 or length <= 0:
                    return 0
                orig = item.get(orig_key, '')
                trans = strip_accents(item.get('translation', orig))
                if not trans:
                    return 0
                tb = trans.encode('latin-1', errors='replace')
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

    print(f"\nOutput files:")
    for f in sorted(os.listdir(OUT)):
        sz = os.path.getsize(os.path.join(OUT, f))
        print(f"  {f}: {sz/1024/1024:.1f} MB" if sz > 1e6 else f"  {f}: {sz/1024:.1f} KB")


# ═════════════════════════════════════════════════════════
# CSV WORKFLOW
# ═════════════════════════════════════════════════════════

def cmd_to_csv():
    """Exporta los JSON de diálogo a CSV en translations/csv/dialog/"""
    csv_dialog = os.path.join(TRANS, 'csv', 'dialog')
    n = json_dir_to_csv_dir(os.path.join(TRANS, 'dialog'), csv_dialog)
    print(f"  {n} entradas → {csv_dialog}/")
    # También exporta 'other' (los sin prefijo ID, que son los de trabajo)
    csv_other = os.path.join(TRANS, 'csv', 'other')
    # Solo los ficheros other sin prefijo ID
    os.makedirs(csv_other, exist_ok=True)
    other_dir = os.path.join(TRANS, 'other')
    n2 = 0
    if os.path.exists(other_dir):
        from digimon_toolkit.csv_tools import json_to_csv
        for fname in sorted(os.listdir(other_dir)):
            if not fname.endswith('.json') or fname.startswith('ID'):
                continue
            src = os.path.join(other_dir, fname)
            dst = os.path.join(csv_other, fname[:-5] + '.csv')
            n2 += json_to_csv(src, dst)
    print(f"  {n2} entradas → {csv_other}/")


def cmd_from_csv():
    """Importa traducciones de CSV a JSON, y propaga a los ID0XXXX equivalentes."""
    csv_dialog = os.path.join(TRANS, 'csv', 'dialog')
    if not os.path.exists(csv_dialog):
        print("  No existe translations/csv/dialog/ — ejecuta primero 'to-csv'")
        return
    n = csv_dir_to_json_dir(csv_dialog, os.path.join(TRANS, 'dialog'))
    print(f"  {n} entradas actualizadas en translations/dialog/")

    csv_other = os.path.join(TRANS, 'csv', 'other')
    if os.path.exists(csv_other):
        n2 = csv_dir_to_json_dir(csv_other, os.path.join(TRANS, 'other'))
        print(f"  {n2} entradas actualizadas en translations/other/")


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
    """Muestra el progreso de traducción del directorio CSV."""
    csv_dialog = os.path.join(TRANS, 'csv', 'dialog')
    if not os.path.exists(csv_dialog):
        print("  No existe translations/csv/dialog/ — ejecuta primero 'to-csv'")
        return
    s = csv_stats(csv_dialog)
    print(f"\n  Progreso de diálogos:")
    print(f"    Ficheros completos : {s['files_done']}/{s['files_total']}")
    print(f"    Líneas traducidas  : {s['lines_done']}/{s['lines_total']} ({s['pct']}%)")
    bar_len = 40
    filled = int(bar_len * s['lines_done'] / s['lines_total']) if s['lines_total'] else 0
    bar = '█' * filled + '░' * (bar_len - filled)
    print(f"    [{bar}]")


def main():
    cmd = sys.argv[1] if len(sys.argv) >= 2 else ''

    # Commands with extra arguments
    if cmd == 'extract-image':
        if len(sys.argv) < 3:
            print("Usage: extract-image <file_id>   e.g. extract-image 0156")
            return
        cmd_extract_image(sys.argv[2])
        return

    if cmd == 'inject-image':
        if len(sys.argv) < 5:
            print("Usage: inject-image <file_id> <img_idx> <png_path>")
            print("  e.g. inject-image 0156 4 output/images/0156/img_04_256x256.png")
            return
        cmd_inject_image(sys.argv[2], int(sys.argv[3]), sys.argv[4])
        return

    cmds = {
        'extract-cpk':    cmd_extract_cpk,
        'extract-text':   cmd_extract_text,
        'extract-images': cmd_extract_images,
        'extract-all':    cmd_extract_all,
        'to-csv':         cmd_to_csv,
        'from-csv':       cmd_from_csv,
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
