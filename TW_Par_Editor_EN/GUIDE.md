# Guide — TW1 PAR Editor v1.2

## Installation

1. Install **Python 3.6+** (on Windows: [python.org](https://python.org), check "Add to PATH")
2. Place all four files in the same folder:
   - `tw1_par_editor.py`
   - `tw1_sdk_labels.json`
   - `tw1_sdk_descriptions.json`
   - `START_PAR_EDITOR.bat`
3. Double-click `START_PAR_EDITOR.bat` (or run `python tw1_par_editor.py`)

The editor shows on startup: **"1808 SDK field names, 1699 descriptions loaded"**

## Opening a PAR File

`File → Open PAR` (Ctrl+O)

The `TwoWorlds.par` is inside the game's WD archives. To extract:
- Use [TW2WDTool](https://www.moddb.com/games/two-worlds/downloads) or WDPackager from the SDK
- The `.par` is zlib-compressed — the editor handles this automatically

## Interface

**Left: Tree View**
- Each node = a list containing entries
- Format: `List 42 (MO_WOLF_01...) [12]` — first entry name + count
- Entries show name and model path

**Right: Detail Panel**
- All fields of the selected entry
- Format per row: `[Index] LabelName  Type  = Value`

## Understanding Fields

Each field has:
- **Index** `[0]` `[1]` ... — position in the data structure
- **Label** (cyan) — SDK field name, e.g. `initParamHP`, `moveRunSpeed`
- **Type** (purple) — data type: int32, float32, uint32, string, arrays
- **Value** (green/yellow/orange) — editable value

### Tooltip Descriptions

**Hover over a label** → after 400ms a tooltip appears with a description:

| Label | Tooltip |
|-------|---------|
| `classID` | Object class type (see classmask.h). Determines category: UNIT, WEAPON, PASSIVE etc. |
| `initParamHP` | Starting hit points of the unit. |
| `moveRunSpeed` | Run speed of the unit. Higher = faster. |
| `cardMagicSchool` | Magic school: 0=Air, 1=Fire, 2=Water, 3=Earth, 4=Necromancy. |
| `artPrice` | Base price at merchants (gold). |
| `wpDamSlashingMax` | Weapon slashing damage (maximum). |

### Editing Labels

- **No label?** → click `···` → enter a name
- **Right-click** a label → Rename / Remove
- Changes are saved to `~/tw1_par_labels.json`
- Labels apply per field-count category (all 65-field entries share the same labels)

## Managing Entries (Right-Click Menu)

Right-click any entry in the tree to access the context menu:

### Duplicate Entry

Creates a deep copy of the selected entry with a new name.

- The editor auto-suggests the next name by incrementing the trailing number (e.g. `ROADSIGN_L_13` → `ROADSIGN_L_14`)
- String fields containing the old name (e.g. mesh paths) are automatically updated to the new name
- The duplicate is inserted directly after the original
- A warning appears if the name already exists

**Example workflow — adding a new road sign:**
1. Open `TwoWorlds.par`
2. Search for `ROADSIGN_L_13`
3. Right-click → **Duplicate**
4. Confirm name `ROADSIGN_L_14`
5. Adjust mesh path and other fields in the detail panel
6. Save

### Rename Entry

Changes the entry name. String fields referencing the old name are updated automatically.

### Delete Entry

Removes an entry from its list (with confirmation dialog).

### Add New Entry (on List nodes)

Right-click a list node to add a blank entry with the same field structure as existing entries in that list.

## Editing Values

1. Select an entry in the tree
2. Change the value in the input field
3. `File → Save PAR` (Ctrl+S) — writes back byte-identically

**Supported types:**
- `int32` — signed integer (e.g. HP, damage, speed)
- `uint32` — unsigned integer (e.g. references with $ prefix)
- `float32` — floating point (e.g. scale factors)
- `string` — text (e.g. mesh paths, sound files)
- Arrays — display only, not directly editable

## JSON Export/Import

**Export:** `File → Export JSON` — creates a labeled, human-readable JSON file:
```json
{
  "name": "MO_WOLF_01",
  "fields": [
    { "index": 0, "label": "classID", "type": "int32", "value": 66066 },
    { "index": 1, "label": "mesh", "type": "string", "value": "DefaultMesh.vdf" },
    { "index": 34, "label": "initParamHP", "type": "int32", "value": 80 }
  ]
}
```

**Import:** `File → Import JSON` — loads JSON back as PAR data (save as .par afterwards)

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+O | Open PAR |
| Ctrl+S | Save PAR |
| Ctrl+Shift+S | Save as... |
| Ctrl+E | Export JSON |
| Ctrl+I | Import JSON |

## Entry Categories

| Fields | Type | Examples |
|--------|------|----------|
| 6 | Sounds | SND_MENU_GO, SND_SWORD_01 |
| 16 | Static Objects | HUGEGATE, QUD_FIREPLACE |
| 26 | Basic Creatures | MO_RABBIT_01, MO_BIRD_01 |
| 53 | Spells | MAGIC_LIGHTING, MAGIC_HEAL |
| 65 | NPCs / Monsters | MO_WOLF_01, NPC_Q_005, SHOPUNIT_1 |
| 67 | Weapons | WP_SWORD_01, WP_BOW_01 |
| 76 | Magic Staffs | WP_STAFF_01 |
| 77 | Traps | TRAP_HOLD_01 |
| 101 | Potions / Ingredients | POTION_HEALING_01 |
| 121 | Heroes | HEROSINGLE, HERO1 |

## classID Values (classmask.h)

The first field (`classID`) defines the object type. Key values:

| Hex | Decimal | Type |
|-----|---------|------|
| 0x00010212 | 66066 | UNIT (monster/NPC) |
| 0x01010212 | 16843282 | HERO |
| 0x02010212 | 33620498 | SHOPUNIT |
| 0x00000122 | 290 | WEAPON |
| 0x00000422 | 1058 | MAGICCARD |
| 0x02050812 | 33884178 | POTIONARTEFACT |
| 0x04050812 | 67438610 | SPECIALARTEFACT |
| 0x00810812 | 8456210 | CONTAINER |

## Tips

- **Backup!** Always keep a copy of the original PAR
- **JSON as working copy** — export to JSON, use a text editor for search/replace, then reimport
- **$ = Reference** — fields with `$` prefix are IDs pointing to other PAR entries
- **[] = Array** — fields with `[]` suffix contain multiple values
- **Ticks** — many time values are in engine ticks (roughly 20 ticks ≈ 1 second)
