"""
csv_tools.py — JSON <-> CSV conversion for the localization workflow.

Each dialog file (e.g. 3520.json) generates a CSV with one row per entry.
Newlines within text are represented as the literal sequence \\n (backslash-n),
so each entry occupies exactly one line in the CSV file.

CSV columns:
  index       — entry index within the file
  limit       — available bytes (= length of the original English text)
  speaker     — speaker group ID from ESDF binary records (read-only, 0 = narrator)
  original    — English source text (DO NOT MODIFY)
  translation — translated text in the target language (what the agent edits)
"""

import csv
import json
import os
from pathlib import Path


def _escape_newlines(text: str) -> str:
    """Convierte saltos de línea reales en la secuencia literal \\n."""
    return text.replace('\n', '\\n')


def _unescape_newlines(text: str) -> str:
    """Convierte la secuencia literal \\n de vuelta en saltos de línea reales."""
    return text.replace('\\n', '\n')


def _byte_len(text: str) -> int:
    """Longitud en bytes de un texto (UTF-8, que para ASCII es igual que len)."""
    return len(text.encode('utf-8'))


# ─────────────────────────────────────────────────────────────
# JSON → CSV
# ─────────────────────────────────────────────────────────────

def json_to_csv(json_path: str, csv_path: str) -> int:
    """
    Convierte un fichero JSON de diálogo en un CSV de traducción.
    Devuelve el número de entradas escritas.
    """
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    entries = data.get('dialog', [])

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(['index', 'limit', 'speaker', 'original', 'translation'])
        for entry in entries:
            idx = entry.get('index', '')
            limit = entry.get('_length', '')
            speaker = entry.get('speaker_id', 0)
            english = _escape_newlines(entry.get('english', ''))
            # Leave translation empty if it's identical to the English source
            trans_raw = entry.get('translation', '')
            translation = '' if trans_raw == entry.get('english', '') else _escape_newlines(trans_raw)
            writer.writerow([idx, limit, speaker, english, translation])

    return len(entries)


def json_dir_to_csv_dir(json_dir: str, csv_dir: str,
                        prefix_filter: str = '') -> int:
    """
    Convierte todos los JSON de json_dir en CSV dentro de csv_dir.
    Si prefix_filter es 'ID', solo procesa ficheros ID*.json.
    Si prefix_filter es '', solo procesa ficheros sin prefijo ID.
    """
    os.makedirs(csv_dir, exist_ok=True)
    total = 0
    for fname in sorted(os.listdir(json_dir)):
        if not fname.endswith('.json'):
            continue
        name = fname[:-5]
        # Filtro: solo ficheros sin prefijo ID (los de trabajo)
        if name.startswith('ID'):
            continue
        src = os.path.join(json_dir, fname)
        dst = os.path.join(csv_dir, name + '.csv')
        n = json_to_csv(src, dst)
        total += n
    return total


# ─────────────────────────────────────────────────────────────
# CSV → JSON
# ─────────────────────────────────────────────────────────────

def csv_to_json(csv_path: str, json_path: str) -> int:
    """
    Importa traducciones de un CSV y las escribe en el JSON correspondiente.
    Solo modifica el campo 'translation' y 'hablante'; el resto no se toca.
    Devuelve el número de entradas actualizadas.
    """
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    # Construir lookup por índice
    by_index = {entry['index']: entry for entry in data.get('dialog', [])}

    updated = 0
    with open(csv_path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                idx = int(row['index'])
            except (ValueError, KeyError):
                continue
            if idx not in by_index:
                continue
            translation = _unescape_newlines(row.get('translation', '').strip())
            entry = by_index[idx]
            if translation:
                entry['translation'] = translation
                updated += 1

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return updated


def csv_dir_to_json_dir(csv_dir: str, json_dir: str) -> int:
    """
    Importa todos los CSV de csv_dir a sus JSON correspondientes en json_dir.
    También propaga las traducciones al fichero ID0XXXX equivalente si existe.
    """
    total = 0
    for fname in sorted(os.listdir(csv_dir)):
        if not fname.endswith('.csv'):
            continue
        name = fname[:-4]  # ej. "3520"
        csv_path = os.path.join(csv_dir, fname)

        # Actualizar el JSON sin prefijo
        json_path = os.path.join(json_dir, name + '.json')
        if os.path.exists(json_path):
            n = csv_to_json(csv_path, json_path)
            total += n

        # Propagar al JSON con prefijo ID0XXXX (zero-padded a 5 dígitos)
        try:
            padded = f'ID{int(name):05d}'
        except ValueError:
            padded = None
        if padded:
            id_json = os.path.join(json_dir, padded + '.json')
            if os.path.exists(id_json):
                csv_to_json(csv_path, id_json)

    return total


# ─────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────

def check_lengths(csv_path: str) -> list:
    """
    Check that no translation exceeds its byte limit.
    Returns list of (index, limit, bytes_used, text) for violations.
    """
    violations = []
    with open(csv_path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            trans = _unescape_newlines(row.get('translation', '').strip())
            if not trans:
                continue
            try:
                limit = int(row['limit'])
            except (ValueError, KeyError):
                continue
            used = _byte_len(trans)
            if used > limit:
                violations.append((row['index'], limit, used, trans))
    return violations


def stats(csv_dir: str) -> dict:
    """
    Return translation progress statistics for a CSV directory.
    """
    total = 0
    done = 0
    files_done = 0
    files_total = 0
    for fname in sorted(os.listdir(csv_dir)):
        if not fname.endswith('.csv'):
            continue
        files_total += 1
        file_done = 0
        file_total = 0
        with open(os.path.join(csv_dir, fname), encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                file_total += 1
                if row.get('translation', '').strip():
                    file_done += 1

        total += file_total
        done += file_done
        if file_done == file_total and file_total > 0:
            files_done += 1
    return {
        'lines_total': total,
        'lines_done': done,
        'files_total': files_total,
        'files_done': files_done,
        'pct': round(100 * done / total, 1) if total else 0,
    }
