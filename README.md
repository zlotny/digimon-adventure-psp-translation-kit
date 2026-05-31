# Digimon Adventure PSP — Translation Toolkit

A Python toolkit to create fan translations of **Digimon Adventure (PSP)** for any target language.

It extracts dialog and UI text from the [English fan patch (v1.2)](https://digimonadventurenglish.weebly.com), converts everything to editable CSV files, and repackages the translated content into a playable ISO and a distributable xdelta patch.

---

## What you need

Two ISOs placed in the **root of this repository**, with these exact filenames:

| File | Description |
|------|-------------|
| `3161 - Digimon Adventure (Japan).iso` | Original Japanese dump (No-Intro name) |
| `3161 - Digimon Adventure (Japan) - English Patch 1.2.iso` | Japanese ISO with the English fan patch v1.2 applied |

To create the English-patched ISO from the Japanese one and the fan patch xdelta:

```bash
xdelta3 -d -s "3161 - Digimon Adventure (Japan).iso" \
    "Digimon Adventure (English Patch Ver. 1.2).xdelta" \
    "3161 - Digimon Adventure (Japan) - English Patch 1.2.iso"
```

> Both ISO files are gitignored and will never be committed to this repository.

---

## Setup

**1. Clone and enter the repo**

```bash
git clone https://github.com/zlotny/digimon-adventure-psp-translation-kit
cd digimon-adventure-psp-translation-kit
```

**2. Create a virtual environment and install dependencies**

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**3. Install xdelta3** (needed to generate distributable patches)

```bash
# macOS
brew install xdelta

# Debian / Ubuntu
sudo apt install xdelta3

# Windows — download from https://github.com/jmacd/xdelta-gpl/releases
```

**4. Extract the game files**

The ISOs must be unpacked into `orig_iso/` and `patched_iso/` before the toolkit can read them. Use [7-Zip](https://www.7-zip.org/) (cross-platform) or `hdiutil` on macOS:

```bash
# Using 7z (all platforms)
7z x "3161 - Digimon Adventure (Japan).iso" -o orig_iso/
7z x "3161 - Digimon Adventure (Japan) - English Patch 1.2.iso" -o patched_iso/

# macOS alternative (no extra install)
mkdir -p orig_iso patched_iso
hdiutil attach -mountpoint orig_iso "3161 - Digimon Adventure (Japan).iso"
hdiutil attach -mountpoint patched_iso "3161 - Digimon Adventure (Japan) - English Patch 1.2.iso"
```

**5. Run the full extraction**

```bash
python digimon_toolkit/cli.py extract-all
```

This creates `orig_data/`, `patched_data/`, and the `translations/` working tree. It takes a couple of minutes.

---

## Translation workflow

### Daily session

```bash
# 1. Check how much is left
python digimon_toolkit/cli.py progress

# 2. Edit CSVs in translations/csv/dialog/
#    Fill in the 'translation' column. Leave it empty to keep the English line.

# 3. Import changes to the JSON backend
python digimon_toolkit/cli.py from-csv

# 4. Build the ISO and xdelta patch
python digimon_toolkit/cli.py apply
```

Output files land in `output/`:

| File | Description |
|------|-------------|
| `Digimon Adventure (Translated).iso` | Full ISO — load in PPSSPP to test |
| `translation_patch.xdelta` | Distributable patch (applied over the Japanese ISO) |

### CSV format

One file per game scene, in `translations/csv/dialog/`.

```
index,limit,original,translation
0,71,"During the summer of that year,\nstrange events happened all over\nEarth.",
5,7,Taichi!,
```

| Column | Edit? | Notes |
|--------|-------|-------|
| `index` | No | Entry ID within the file |
| `limit` | No | Max bytes for the translation |
| `original` | No | English source text |
| `translation` | **Yes** | Your translation |

- `\n` inside text = in-game line break (counts as 1 byte toward `limit`).
- Translations exceeding `limit` are silently truncated in-game.
- You can write accented characters freely (á, é, ñ…); the toolkit strips them to ASCII at build time. If a future font hack adds native accent support, remove the `strip_accents` call in `cli.py`.

---

## CLI reference

```bash
python digimon_toolkit/cli.py extract-cpk              # Extract orig_data/ and patched_data/
python digimon_toolkit/cli.py extract-text             # Parse ESDF text → JSON in translations/
python digimon_toolkit/cli.py extract-images           # Extract patched UI textures to output/images/
python digimon_toolkit/cli.py extract-image <id>       # Extract images from a single file (e.g. 0156)
python digimon_toolkit/cli.py inject-image <id> <N> <png>  # Replace image N in file <id>
python digimon_toolkit/cli.py extract-all              # Run all three extract steps
python digimon_toolkit/cli.py to-csv                   # Export JSON → CSV (translations/csv/)
python digimon_toolkit/cli.py from-csv                 # Import CSV → JSON
python digimon_toolkit/cli.py progress                 # Show translation progress
python digimon_toolkit/cli.py apply                    # Build ISO + xdelta patch
```

---

## Credits

- **[English fan patch v1.2](https://digimonadventurenglish.weebly.com)** — the team who translated the game into English, providing the source text for this toolkit.
- **CriPakTools** by [esperknight](https://github.com/esperknight/CriPakTools) (originally by Falo and Nanashi3) — the reference implementation for CRI CPK archive parsing that informed `cpk.py` and `utf.py`.
- **LibPSPThemes** — swizzle algorithm reference used in `psp_image.py`.

---

## License

MIT — see [LICENSE](LICENSE).
