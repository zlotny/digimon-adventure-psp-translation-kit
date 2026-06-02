"""
Translation Helper — Flask API server.
Serves the Vue webapp from webapp/dist/ and exposes a JSON API for
reading and writing translation files without touching the CLI.
"""
import json
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

BASE = Path(__file__).parent.parent
TRANS = BASE / 'translations'
WEBAPP_DIST = BASE / 'webapp' / 'dist'

app = Flask(__name__, static_folder=None)


# ─────────────────────────────────────────────────────────────
# Normalisation helpers
# ─────────────────────────────────────────────────────────────

def _norm_dialog(entry):
    return {
        'index':      entry.get('index', 0),
        'source':     entry.get('english', ''),
        'translation': entry.get('translation', ''),
        'limit':      entry.get('_length'),
        'speaker_id': entry.get('speaker_id'),
    }


def _norm_eboot(entry, idx):
    return {
        'index':      idx,
        'source':     entry.get('text', ''),
        'translation': entry.get('translation', ''),
        'limit':      entry.get('_length'),
        'speaker_id': None,
    }


def _norm_name(entry, idx):
    return {
        'index':      idx,
        'source':     entry.get('name', ''),
        'translation': entry.get('translation', ''),
        'limit':      entry.get('_length'),
        'speaker_id': None,
    }


# ─────────────────────────────────────────────────────────────
# Read helpers
# ─────────────────────────────────────────────────────────────

def _read_file(category, name):
    if category == 'dialog':
        path = TRANS / 'dialog' / f'{name}.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        return [_norm_dialog(e) for e in data.get('dialog', [])]

    if category == 'eboot':
        path = TRANS / 'eboot' / f'{name}.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        return [_norm_eboot(e, i) for i, e in enumerate(data.get('strings', []))]

    if category == 'names':
        path = TRANS / 'names' / 'names.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        entries = []
        for i, e in enumerate(data.get('character_names', [])):
            entries.append(_norm_name(e, i))
        offset = len(entries)
        for i, e in enumerate(data.get('digimon_names', [])):
            entries.append(_norm_name(e, offset + i))
        return entries

    return []


def _file_progress(entries_raw, key):
    """Count done/total from a raw (not normalised) entry list."""
    done = sum(1 for e in entries_raw if e.get(key, ''))
    return done, len(entries_raw)


from digimon_toolkit.font_tool import ACCENT_MAP as _ACCENT_MAP
_PROXY_CHARS = set(chr(v) for v in _ACCENT_MAP.values())

def _entry_has_problem(text, limit, is_dialog=False):
    if not text:
        return False
    if is_dialog:
        lines = text.split('\n')
        line_limits = [33, 33, 31]
        if any(len(l) > line_limits[min(i, 2)] for i, l in enumerate(lines)):
            return True
        if len(lines) > 3:
            return True
        if '\\n' in text:
            return True
        if any(c in _PROXY_CHARS for c in text):
            return True
    if limit is not None:
        if sum(1 for c in text if c != '\n') > limit:
            return True
    return False


# ─────────────────────────────────────────────────────────────
# Write helpers
# ─────────────────────────────────────────────────────────────

def _write_entry(category, name, index, translation):
    if category == 'dialog':
        path = TRANS / 'dialog' / f'{name}.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        for e in data.get('dialog', []):
            if e.get('index') == index:
                e['translation'] = translation
                break
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    elif category == 'eboot':
        path = TRANS / 'eboot' / f'{name}.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        strings = data.get('strings', [])
        if 0 <= index < len(strings):
            strings[index]['translation'] = translation
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    elif category == 'names':
        path = TRANS / 'names' / 'names.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        char = data.get('character_names', [])
        digi = data.get('digimon_names', [])
        nc = len(char)
        if index < nc:
            char[index]['translation'] = translation
        elif index - nc < len(digi):
            digi[index - nc]['translation'] = translation
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


# ─────────────────────────────────────────────────────────────
# API routes
# ─────────────────────────────────────────────────────────────

@app.route('/api/files')
def api_files():
    result = {'dialog': [], 'eboot': [], 'names': []}

    dialog_dir = TRANS / 'dialog'
    if dialog_dir.exists():
        for p in sorted(dialog_dir.glob('*.json')):
            if p.stem.startswith('ID'):
                continue
            data = json.loads(p.read_text(encoding='utf-8'))
            entries = data.get('dialog', [])
            done, total = _file_progress(entries, 'translation')
            problems = sum(1 for e in entries if _entry_has_problem(e.get('translation', ''), e.get('_length'), is_dialog=True))
            result['dialog'].append({'id': p.stem, 'done': done, 'total': total, 'problems': problems})

    eboot_dir = TRANS / 'eboot'
    if eboot_dir.exists():
        for p in sorted(eboot_dir.glob('*.json')):
            data = json.loads(p.read_text(encoding='utf-8'))
            strings = data.get('strings', [])
            done, total = _file_progress(strings, 'translation')
            problems = sum(1 for e in strings if _entry_has_problem(e.get('translation', ''), e.get('_length')))
            result['eboot'].append({'id': p.stem, 'done': done, 'total': total, 'problems': problems})

    names_path = TRANS / 'names' / 'names.json'
    if names_path.exists():
        data = json.loads(names_path.read_text(encoding='utf-8'))
        all_names = data.get('character_names', []) + data.get('digimon_names', [])
        done, total = _file_progress(all_names, 'translation')
        problems = sum(1 for e in all_names if _entry_has_problem(e.get('translation', ''), e.get('_length')))
        result['names'].append({'id': 'names', 'done': done, 'total': total, 'problems': problems})

    return jsonify(result)


@app.route('/api/file/<category>/<name>')
def api_get_file(category, name):
    if category not in ('dialog', 'eboot', 'names'):
        return jsonify({'error': 'invalid category'}), 400
    try:
        entries = _read_file(category, name)
        return jsonify({'entries': entries})
    except FileNotFoundError:
        return jsonify({'error': 'not found'}), 404


@app.route('/api/file/<category>/<name>/<int:index>', methods=['PATCH'])
def api_patch_entry(category, name, index):
    if category not in ('dialog', 'eboot', 'names'):
        return jsonify({'error': 'invalid category'}), 400
    body = request.get_json(silent=True) or {}
    if 'translation' not in body:
        return jsonify({'error': 'missing translation field'}), 400
    try:
        _write_entry(category, name, index, body['translation'])
        return '', 204
    except FileNotFoundError:
        return jsonify({'error': 'not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────
# Static file serving (built Vue app)
# ─────────────────────────────────────────────────────────────

def _iter_all_entries(field='any'):
    """
    Yield (category, file_id, raw_entry, source_text, translation_text)
    for every entry across dialog / eboot / names.
    field='source'      → only entries where source field is non-empty
    field='translation' → only entries where translation field is non-empty
    field='any'         → all entries
    """
    dialog_dir = TRANS / 'dialog'
    if dialog_dir.exists():
        for p in sorted(dialog_dir.glob('*.json')):
            if p.stem.startswith('ID'):
                continue
            data = json.loads(p.read_text(encoding='utf-8'))
            for e in data.get('dialog', []):
                yield 'dialog', p.stem, e, e.get('english', ''), e.get('translation', '')

    eboot_dir = TRANS / 'eboot'
    if eboot_dir.exists():
        for p in sorted(eboot_dir.glob('*.json')):
            data = json.loads(p.read_text(encoding='utf-8'))
            for i, e in enumerate(data.get('strings', [])):
                yield 'eboot', p.stem, e, e.get('text', ''), e.get('translation', '')

    names_path = TRANS / 'names' / 'names.json'
    if names_path.exists():
        data = json.loads(names_path.read_text(encoding='utf-8'))
        idx = 0
        for e in data.get('character_names', []) + data.get('digimon_names', []):
            yield 'names', 'names', e, e.get('name', ''), e.get('translation', '')
            idx += 1


@app.route('/api/search')
def api_search():
    q     = request.args.get('q', '').strip().lower()
    field = request.args.get('field', 'any')   # 'source' | 'translation' | 'any'
    if len(q) < 2:
        return jsonify([])

    results = []
    entry_idx = 0  # running index for names (which has no 'index' key)

    dialog_dir = TRANS / 'dialog'
    if dialog_dir.exists():
        for p in sorted(dialog_dir.glob('*.json')):
            if p.stem.startswith('ID'):
                continue
            data = json.loads(p.read_text(encoding='utf-8'))
            for e in data.get('dialog', []):
                src = e.get('english', '')
                tra = e.get('translation', '')
                hit = (field in ('source', 'any') and q in src.lower()) or \
                      (field in ('translation', 'any') and q in tra.lower())
                if hit:
                    results.append({'category': 'dialog', 'file': p.stem,
                                    'index': e.get('index', 0), 'source': src, 'translation': tra})

    eboot_dir = TRANS / 'eboot'
    if eboot_dir.exists():
        for p in sorted(eboot_dir.glob('*.json')):
            data = json.loads(p.read_text(encoding='utf-8'))
            for i, e in enumerate(data.get('strings', [])):
                src = e.get('text', '')
                tra = e.get('translation', '')
                hit = (field in ('source', 'any') and q in src.lower()) or \
                      (field in ('translation', 'any') and q in tra.lower())
                if hit:
                    results.append({'category': 'eboot', 'file': p.stem,
                                    'index': i, 'source': src, 'translation': tra})

    names_path = TRANS / 'names' / 'names.json'
    if names_path.exists():
        data = json.loads(names_path.read_text(encoding='utf-8'))
        idx = 0
        for e in data.get('character_names', []) + data.get('digimon_names', []):
            src = e.get('name', '')
            tra = e.get('translation', '')
            hit = (field in ('source', 'any') and q in src.lower()) or \
                  (field in ('translation', 'any') and q in tra.lower())
            if hit:
                results.append({'category': 'names', 'file': 'names',
                                'index': idx, 'source': src, 'translation': tra})
            idx += 1

    return jsonify(results[:60])


@app.route('/api/replace', methods=['POST'])
def api_replace():
    body    = request.get_json(silent=True) or {}
    search  = body.get('search', '')
    replace = body.get('replace', '')
    mode    = body.get('mode', 'translation')   # 'source' | 'translation'

    if not search:
        return jsonify({'error': 'search is required'}), 400

    # field keys by mode and category
    SOURCE_KEY = {'dialog': 'english', 'eboot': 'text', 'names': 'name'}
    field_key  = SOURCE_KEY if mode == 'source' else None  # None → use 'translation' everywhere

    count = 0

    def _replace_in_list(entries, get_key):
        nonlocal count
        changed = False
        for e in entries:
            key = get_key(e)
            val = e.get(key, '')
            if search in val:
                e[key] = val.replace(search, replace)
                count += 1
                changed = True
        return changed

    dialog_dir = TRANS / 'dialog'
    if dialog_dir.exists():
        for p in sorted(dialog_dir.glob('*.json')):
            if p.stem.startswith('ID'):
                continue
            data = json.loads(p.read_text(encoding='utf-8'))
            key  = 'english' if mode == 'source' else 'translation'
            if _replace_in_list(data.get('dialog', []), lambda e, k=key: k):
                p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    eboot_dir = TRANS / 'eboot'
    if eboot_dir.exists():
        for p in sorted(eboot_dir.glob('*.json')):
            data = json.loads(p.read_text(encoding='utf-8'))
            key  = 'text' if mode == 'source' else 'translation'
            if _replace_in_list(data.get('strings', []), lambda e, k=key: k):
                p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    names_path = TRANS / 'names' / 'names.json'
    if names_path.exists():
        data = json.loads(names_path.read_text(encoding='utf-8'))
        key  = 'name' if mode == 'source' else 'translation'
        changed = False
        for e in data.get('character_names', []) + data.get('digimon_names', []):
            val = e.get(key, '')
            if search in val:
                e[key] = val.replace(search, replace)
                count += 1
                changed = True
        if changed:
            names_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    return jsonify({'count': count})


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static(path):
    if path and (WEBAPP_DIST / path).exists():
        return send_from_directory(WEBAPP_DIST, path)
    return send_from_directory(WEBAPP_DIST, 'index.html')


def run(port=5174):
    app.run(host='127.0.0.1', port=port, debug=False)
