# TW1 PAR Editor

A GUI editor for Two Worlds 1 `.par` parameter files — the core data format that defines every NPC, weapon, spell, potion, and object in the game.

![Python 3.6+](https://img.shields.io/badge/python-3.6+-blue) ![License: MIT](https://img.shields.io/badge/license-MIT-green) ![Platform: Windows/Linux/Mac](https://img.shields.io/badge/platform-Win%20%7C%20Linux%20%7C%20Mac-lightgrey)

## Features

- **Full PAR parsing** — reads and writes the binary PAR format byte-perfectly (zlib-compressed dual-stream wrapper included)
- **1808 SDK field labels** — extracted from the official `TwoWorlds.xls` SDK spreadsheet, mapped to field indices per entry category
- **1666 tooltip descriptions** — hover over any field label to see what it does
- **Editable fields** — change int32, uint32, float32, and string values directly in the GUI
- **Duplicate / Rename / Delete entries** — right-click any entry in the tree to clone, rename, or remove it. Duplicating auto-increments names and updates mesh paths (v1.2)
- **Add new entries** — right-click a list node to add a blank entry with matching field structure (v1.2)
- **JSON export/import** — convert PAR to human-readable JSON (with labels) and back
- **Label system** — right-click to rename/add labels, persisted to `~/tw1_par_labels.json`
- **Validation** — roundtrip-tested on the original `TwoWorlds.par` (602 lists, 5087 entries, byte-identical)

## Quick Start

```
python tw1_par_editor.py
```

Or double-click `START_PAR_EDITOR.bat` on Windows.

**Requirements:** Python 3.6+ with tkinter (included in standard Python on Windows).

## Files

| File | Description |
|------|-------------|
| `tw1_par_editor.py` | Main editor script (GUI + parser + writer) |
| `tw1_sdk_labels.json` | 1808 field names from the SDK (auto-loaded) |
| `tw1_sdk_descriptions.json` | 1666 tooltip descriptions for field labels |
| `START_PAR_EDITOR.bat` | Windows launcher |

Place all files in the same directory. The editor auto-discovers the JSON files next to the script.

## Usage

See [GUIDE.md](GUIDE.md) for a detailed usage guide.

**Open:** File → Open PAR (or Ctrl+O) — supports both raw and zlib-compressed `.par` files

**Navigate:** Tree on the left shows Lists → Entries. Click an entry to see its fields on the right.

**Edit:** Change values in the input fields, then File → Save (Ctrl+S).

**Manage entries:** Right-click an entry → Duplicate / Rename / Delete. Right-click a list node → Add New Entry. Duplicating auto-suggests the next name and updates string fields referencing the old name.

**Labels:** SDK labels appear in cyan. Hover for German tooltip. Right-click to rename. Click `···` on unlabeled fields to add a name.

**Export:** File → Export JSON — creates a labeled, human-readable JSON version.

## PAR Format

See [PAR_FORMAT.md](PAR_FORMAT.md) for the complete reverse-engineered binary specification.

## Entry Categories

The PAR format groups entries by field count. Each category maps to an SDK sheet:

| Fields | SDK Sheet | Examples |
|--------|-----------|----------|
| 6 | SoundPack | SND_MENU_GO, SND_SWORD_01 |
| 16 | SimplePassives | HUGEGATE, QUD_FIREPLACE |
| 26 | BasicUnits | MO_RABBIT_01, MO_BIRD_01 |
| 53 | MagicCard | MAGIC_LIGHTING, MAGIC_HEAL |
| 65 | Units / ShopUnits | MO_WOLF_01, NPC_Q_005 |
| 67 | Weapon | WP_SWORD_01, WP_BOW_01 |
| 77 | Traps | TRAP_HOLD_01, TRAP_FIRE_01 |
| 101 | PotionArtefacts | POTION_HEALING_01 |
| 121 | Heroes | HEROSINGLE, HERO1 |

See `classmask.h` for the class type hierarchy used in the `classID` field.

## Building Mods

1. Extract `TwoWorlds.par` from the game's WD archives
2. Open in the editor, modify values or duplicate existing entries to create new objects
3. Save and repack into a `.wd` file for the `WDFiles` folder

**Adding new objects (e.g. a new road sign):**
1. Find a similar entry (e.g. `ROADSIGN_L_13`)
2. Right-click → Duplicate → name it `ROADSIGN_L_14`
3. Adjust mesh path and parameters
4. Save, add matching VDF/MTR to the WD archive, update `EditorDef.txt`

## Credits

- **Reality Pump Studios** — Two Worlds game engine and SDK
- PAR format reverse-engineered from binary analysis and SDK correlation
- Field labels extracted from `TwoWorlds.xls` (SDK)
- Class hierarchy from `classmask.h` (SDK)

## License

MIT
