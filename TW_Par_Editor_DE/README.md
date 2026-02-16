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
- **Compare & Merge** — compare two PAR files field-by-field, see differences color-coded, and selectively merge changes from one into the other. Supports an optional unmodified PAR as baseline reference (v1.3)
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
| `tw1_par_compare_config.json` | Saved path to original PAR (auto-created) |

Place all files in the same directory. The editor auto-discovers the JSON files next to the script.

## Usage

See [GUIDE.md](GUIDE.md) for a detailed usage guide.

**Open:** File → Open PAR (or Ctrl+O) — supports both raw and zlib-compressed `.par` files

**Navigate:** Tree on the left shows Lists → Entries. Click an entry to see its fields on the right.

**Edit:** Change values in the input fields, then File → Save (Ctrl+S).

**Manage entries:** Right-click an entry → Duplicate / Rename / Delete. Right-click a list node → Add New Entry. Duplicating auto-suggests the next name and updates string fields referencing the old name.

**Labels:** SDK labels appear in cyan. Hover for German tooltip. Right-click to rename. Click `···` on unlabeled fields to add a name.

**Compare & Merge:** Switch to the "Compare & Merge" tab to compare two PAR files. Load a Source PAR (your working file), an Input PAR (the file with changes to merge), and optionally an unmodified Original PAR as baseline. Click Compare to see all differences, select the changes you want, and click Merge.

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

## Mesh Field Syntax

The `mesh` field (field index 1) in SimplePassives, Passives, and other object entries supports a powerful extended syntax that goes beyond simple file paths. The engine uses this syntax to define mesh variants, texture overrides, and LOD ranges — all within a single string field.

### Basic Format

```
<path>.vdf
```

Example: `Houses\VILLAGE 02\STABLE_02_04.vdf`

### Mesh Variants with Range Notation

```
<path>_0[1-4].vdf
```

This defines multiple mesh variants in a single entry. `STAIRS_02_0[1-4].vdf` expands to four meshes: `STAIRS_02_01.vdf`, `STAIRS_02_02.vdf`, `STAIRS_02_03.vdf`, `STAIRS_02_04.vdf`. In the Two Worlds Editor, these variants can be cycled through via right-click on the placed object. This is useful for objects that share the same parameters but have different visual appearances (e.g. different house styles, fence sections, stair variants).

### Texture Overrides

```
<path>.vdf:<texture1>.dds
```

Appending `:texture.dds` after the VDF path overrides the default texture embedded in the VDF file. This allows reusing the same 3D model with different textures without duplicating the mesh file.

### Multiple Texture Variants

```
<path>.vdf:<texture1>.dds|<texture2>.dds
```

The `|` separator defines additional texture variants. These correspond to the `#mesh2`, `#mesh3` columns visible in the SDK spreadsheet (`TwoWorlds.xls`). In the SDK spreadsheet, these appear as separate columns for readability, but in the PAR binary they are stored as a single concatenated string.

### Combined Example

```
Houses\TOWN 02\STAIRS_02_0[1-4].vdf:STAIRS_02.dds|STAIRS_04.dds
```

This single string defines:
- **4 mesh variants** (STAIRS_02_01 through STAIRS_02_04) — right-click to cycle
- **2 texture sets** (STAIRS_02.dds and STAIRS_04.dds) — alternative skins

### SDK Spreadsheet Mapping

The SDK spreadsheet (`TwoWorlds.xls`) splits this compound string across multiple columns for readability:

| PAR Field | Spreadsheet Column | Content |
|-----------|-------------------|---------|
| field[1] (before `:`) | `mesh` | VDF file path (with optional `[n-m]` range) |
| field[1] (after `:`, before `|`) | `#mesh2` | First texture override |
| field[1] (after `|`) | `#mesh3` | Second texture override |

These are **not separate PAR fields** — they are all part of the single `mesh` string in field index 1.

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
