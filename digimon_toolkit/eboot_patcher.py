"""
EBOOT.BIN patcher. Finds EVERY English string across the entire executable.
No lossy categorization - just dumps all real English with descriptive filenames.
"""
from typing import List, Dict

_SJIS = {b'\x81\x9b': '○', b'\x81\x7e': '×', b'\x81\xa0': '□'}


def _read_nt_string(eboot: bytes, pos: int):
    """Read a null-terminated string at pos, allowing \\x0a newlines and SJIS symbols.
    Returns (decoded_text, byte_len) or None if a non-text byte is encountered."""
    j, out = pos, []
    while j < len(eboot):
        if eboot[j] == 0:
            return ''.join(out), j - pos
        b2 = eboot[j:j+2]
        if b2 in _SJIS:
            out.append(_SJIS[b2]); j += 2
        elif eboot[j] == 0x0a:
            out.append('\n'); j += 1
        elif 0x20 <= eboot[j] <= 0x7e:
            out.append(chr(eboot[j])); j += 1
        else:
            return None
    return None


def _is_real_english(s: str) -> bool:
    flat = s.replace('\n', ' ')
    if len(flat) < 8:
        return False
    lower = sum(1 for c in flat if c.islower())
    if lower < 2:
        return False
    words = [w for w in flat.split() if len(w) > 2]
    if len(words) < 2:
        return False
    stripped = flat.lstrip()
    if stripped.startswith(('E2', 'W2', 'http', 'www', '\\\\')):
        return False
    special = sum(1 for c in flat if c in '%$#{}[]&|<>')
    if special > len(flat) * 0.2:
        return False
    return True


def _encode_nt_length(s: str) -> int:
    """Byte length of the string as stored in EBOOT (SJIS symbols = 2 bytes, rest = 1)."""
    total = 0
    for ch in s:
        if ch in ('○', '×', '□'):
            total += 2
        else:
            total += 1  # \n → \x0a = 1 byte; ASCII = 1 byte
    return total


def find_all_real_english(eboot: bytes) -> List[List]:
    """Scan for null-terminated English strings (including \\x0a and SJIS symbols).
    Returns proximity clusters: each cluster is a list of (offset, text) tuples."""
    strings = []
    i = 0
    while i < len(eboot):
        # Only start at a null boundary (previous byte is \\x00 or very start)
        if i > 0 and eboot[i - 1] != 0:
            i += 1
            continue
        r = _read_nt_string(eboot, i)
        if r is None:
            i += 1
            continue
        s, blen = r
        if _is_real_english(s):
            strings.append((i, s))
        i += blen + 1  # skip past null terminator

    if not strings:
        return []

    # Cluster by proximity (300 byte gap between string starts)
    clusters = []
    current = [strings[0]]
    for off, s in strings[1:]:
        if off - current[-1][0] < 300:
            current.append((off, s))
        else:
            clusters.append(current)
            current = [(off, s)]
    if current:
        clusters.append(current)

    return clusters


def _describe_cluster(strlist: list) -> str:
    """Give a human-readable name for a cluster based on its content."""
    combined = ' '.join(x[1].replace('\n', ' ') for x in strlist[:3]).lower()
    if any('Digimon' in x[1] for x in strlist):
        if any(x[1].startswith('A ') for x in strlist[:10]):
            return 'field_guide'
        if any('evolution' in x[1].lower() or 'Episode' in x[1] for x in strlist[:5]):
            return 'episode_menu'
    if any(w in combined for w in ['tutorial', 'battle', 'attack', 'timeline', 'turn', 'analog']):
        return 'battle_tutorial'
    if any(x[1].startswith(('Great ', 'Super ', 'Slamming', 'Spiral ', 'Mega ')) for x in strlist[:10]):
        return 'skills_attacks'
    # Second cluster of skill names that lacks the common prefixes above
    if any(x[1].startswith(('Fox Tail', 'Puppy ', 'Gran Death', 'V-mon Head',
                              'Boom Boom', 'Soul Crusher', 'Rowdy Rocker',
                              'Baby Flame', 'Baby Burner')) for x in strlist):
        return 'skills_attacks'
    if any(w in combined for w in ['hp', 'max hp', 'evo.', 'exp', 'sp +', 'sp -']):
        return 'evolution_stats'
    if any(x[1].startswith(('Recover', 'Heal', 'Revive', 'Detox')) for x in strlist[:10]):
        return 'items'
    if any('Taichi' in x[1] or 'Yamato' in x[1] for x in strlist[:5]):
        return 'episode_menu'
    if len(strlist) >= 10 and any(x[1].startswith(('One enemy', 'Attacks', 'Spits', 'Fires')) for x in strlist[:10]):
        return 'skill_descriptions'
    return 'ui_other'


def build_eboot_full_json(eboot: bytes) -> Dict:
    """Build complete JSON: ALL English text from EBOOT, organized into logical files."""
    clusters = find_all_real_english(eboot)

    # Extract character names
    names = {}
    pos = 0x199838
    while pos < len(eboot):
        if eboot[pos] == 0:
            break
        end = eboot.find(b'\x00', pos)
        if end == -1 or end - pos < 2:
            break
        try:
            name = eboot[pos:end].decode('ascii')
            if sum(1 for c in name if c.isalpha()) >= 2:
                names[name] = name
            else:
                break
        except Exception:
            break
        pos = end + 1
        if len(names) > 200:
            break

    human_kw = ['Taichi', 'Yamato', 'Sora', 'Koushirou', 'Mimi', 'Jou', 'Takeru',
                'Hikari', 'Yagami', 'Ishida', 'Takenouchi', 'Izumi', 'Tachikawa',
                'Kido', 'Takaishi', 'Hiroaki']

    result = {'source': 'EBOOT.BIN'}
    result['names'] = {'character': [], 'digimon': []}
    for n in sorted(names.keys()):
        cat = 'character' if any(h in n for h in human_kw) else 'digimon'
        result['names'][cat].append({
            'name': n, 'translation': '',
            '_length': len(n.encode('ascii', errors='replace')),
        })

    # Group clusters by type — keep (offset, text) tuples
    grouped: Dict[str, list] = {}
    for cl in clusters:
        cat = _describe_cluster(cl)
        grouped.setdefault(cat, []).extend(cl)

    # Build output entries with correct byte lengths
    for cat, strs in sorted(grouped.items()):
        result[cat] = [
            {
                'text': s,
                'translation': '',
                '_offset': off,
                '_length': _encode_nt_length(s),
            }
            for off, s in strs
        ]

    return result
