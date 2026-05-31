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
            result['dialog'].append({'id': p.stem, 'done': done, 'total': total})

    eboot_dir = TRANS / 'eboot'
    if eboot_dir.exists():
        for p in sorted(eboot_dir.glob('*.json')):
            data = json.loads(p.read_text(encoding='utf-8'))
            strings = data.get('strings', [])
            done, total = _file_progress(strings, 'translation')
            result['eboot'].append({'id': p.stem, 'done': done, 'total': total})

    names_path = TRANS / 'names' / 'names.json'
    if names_path.exists():
        data = json.loads(names_path.read_text(encoding='utf-8'))
        all_names = data.get('character_names', []) + data.get('digimon_names', [])
        done, total = _file_progress(all_names, 'translation')
        result['names'].append({'id': 'names', 'done': done, 'total': total})

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

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static(path):
    if path and (WEBAPP_DIST / path).exists():
        return send_from_directory(WEBAPP_DIST, path)
    return send_from_directory(WEBAPP_DIST, 'index.html')


def run(port=5174):
    app.run(host='127.0.0.1', port=port, debug=False)
