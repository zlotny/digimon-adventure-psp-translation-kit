"""
EBOOT.BIN patcher. Finds EVERY English string across the entire executable.
No lossy categorization - just dumps all real English with descriptive filenames.
"""
import re
from typing import List, Dict


def find_all_real_english(eboot: bytes) -> List[Dict]:
    """Find EVERY real English string in the EBOOT, organized by proximity clusters."""
    strings = []
    for m in re.finditer(b'[\x20-\x7e]{8,}', eboot):
        s = m.group().decode('ascii', errors='ignore')
        off = m.start()
        if s.startswith(('E2','W2','http','www','\\\\')): continue
        lower = sum(1 for c in s if c.islower())
        if lower < 2: continue
        words = [w for w in s.split() if len(w) > 2]
        if len(words) < 2: continue
        special = sum(1 for c in s if c in '%$#{}[]&|<>')
        if special > len(s) * 0.2: continue
        strings.append((off, s))
    
    # Cluster by proximity (300 byte gap)
    clusters = []
    current = [strings[0]] if strings else []
    for off, s in strings[1:]:
        if off - current[-1][0] < 300:
            current.append((off, s))
        else:
            clusters.append(current)
            current = [(off, s)]
    if current: clusters.append(current)
    
    return clusters


def _describe_cluster(strlist: list) -> str:
    """Give a human-readable name for a cluster based on its content."""
    combined = ' '.join(x[1] for x in strlist[:3]).lower()
    if any('Digimon' in x[1] for x in strlist):
        if any(x[1].startswith('A ') for x in strlist[:10]):
            return 'field_guide'
        if any('evolution' in x[1].lower() or 'Episode' in x[1] for x in strlist[:5]):
            return 'episode_menu'
    if any(w in combined for w in ['tutorial','battle','attack','timeline','turn','analog']):
        return 'battle_tutorial'
    if any(x[1].startswith(('Great ','Super ','Slamming','Spiral ','Mega ')) for x in strlist[:10]):
        return 'skills_attacks'
    if any(w in combined for w in ['hp','max hp','evo.','exp','sp +','sp -']):
        return 'evolution_stats'
    if any(x[1].startswith(('Recover','Heal','Revive','Detox')) for x in strlist[:10]):
        return 'items'
    if any('Taichi' in x[1] or 'Yamato' in x[1] for x in strlist[:5]):
        return 'episode_menu'
    if len(strlist) >= 10 and any(x[1].startswith(('One enemy','Attacks','Spits','Fires')) for x in strlist[:10]):
        return 'skill_descriptions'
    return 'ui_other'


def build_eboot_full_json(eboot: bytes) -> Dict:
    """Build complete JSON: ALL English text from EBOOT, organized into logical files."""
    clusters = find_all_real_english(eboot)
    
    # Extract character names
    names = {}
    pos = 0x199838
    while pos < len(eboot):
        if eboot[pos] == 0: break
        end = eboot.find(b'\x00', pos)
        if end == -1 or end - pos < 2: break
        try:
            name = eboot[pos:end].decode('ascii')
            if sum(1 for c in name if c.isalpha()) >= 2:
                names[name] = name
            else: break
        except: break
        pos = end + 1
        if len(names) > 200: break
    
    human_kw = ['Taichi','Yamato','Sora','Koushirou','Mimi','Jou','Takeru',
                'Hikari','Yagami','Ishida','Takenouchi','Izumi','Tachikawa',
                'Kido','Takaishi','Hiroaki']
    
    result = {'source': 'EBOOT.BIN'}
    result['names'] = {'character': [], 'digimon': []}
    for n in sorted(names.keys()):
        cat = 'character' if any(h in n for h in human_kw) else 'digimon'
        result['names'][cat].append({'name': n, 'translation': n})
    
    # Group clusters by type
    grouped = {}
    for cl in clusters:
        cat = _describe_cluster(cl)
        if cat not in grouped:
            grouped[cat] = []
        for off, s in cl:
            grouped[cat].append(s)
    
    # Add as separate JSON files
    for cat, strs in sorted(grouped.items()):
        result[cat] = [{'text': s, 'translation': s} for s in strs]
    
    return result
