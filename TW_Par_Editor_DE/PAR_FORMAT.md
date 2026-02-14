# PAR File Format — Reverse-Engineered Specification

Two Worlds 1 binary parameter file format, used by Reality Pump's engine (also shared with Earth 2150/2160).

## Overview

The PAR file stores all game object definitions: NPCs, weapons, spells, items, sounds, animations, etc. It is a flat list-of-lists structure with typed data fields. Field names are **not stored** in the binary — they come from the SDK's `TwoWorlds.xls` spreadsheet.

## On-Disk Format: Dual-Stream zlib Compression

The `.par` file on disk is **zlib-compressed** using a dual-stream layout:

```
[zlib stream 1] [zlib stream 2]
```

**Stream 1** — Small wrapper header (~200 bytes decompressed):
- Contains `translateGameParams` configuration
- Contains a GUID string
- Not part of the actual PAR data

**Stream 2** — Actual PAR binary data (~1.7 MB decompressed from ~100 KB):
- Starts with PAR magic bytes
- Contains all object definitions

Both streams use standard zlib compression (header byte `0x78`). To read: decompress stream 1, use `unused_data` from the decompressor to find stream 2, decompress stream 2.

Some PAR files may also appear uncompressed (starting directly with `PAR\x00`).

## PAR Binary Structure

All values are **little-endian**. Strings use Delphi-style length-prefixed encoding (uint32 length + ASCII bytes, no null terminator).

### Header

```
Offset  Size  Type     Description
0x00    4     char[4]  Magic: "PAR\x00" (0x50 0x41 0x52 0x00)
0x04    4     uint32   Version: 0x00000600 for Two Worlds 1
0x08    4     uint32   List count (N)
0x0C    4     uint32   Padding (always 0)
```

### List (repeated N times)

```
Offset  Size  Type     Description
+0x00   4     uint32   Unknown1 (observed: 0, 1, 2, ...)
+0x04   4     uint32   Unknown2 (observed: 0)
+0x08   4     uint32   Entry count (M)
  [M entries follow]
```

### Entry (repeated M times per list)

```
Offset  Size  Type          Description
+0x00   4+n   DelphiString  Entry name (e.g. "MO_WOLF_01", "MAGIC_HEAL")
+var    1     int8          Unknown byte (observed: 0, 1)
+var    2     uint16        Field count (F)
+var    2     uint16        Unknown u16a
+var    2     uint16        Unknown u16b
+var    F     uint8[F]      Type list: one type ID per field
  [F data values follow, types matching the type list]
```

### Data Types

```
ID  Name       Size     Encoding
0   int32      4        Signed 32-bit integer (little-endian)
1   float32    4        IEEE 754 single-precision float
2   uint32     4        Unsigned 32-bit integer
3   string     4+n      Delphi string: uint32 length + ASCII bytes
4   int32[]    4+4n     uint32 count + int32 values
5   float32[]  4+4n     uint32 count + float32 values
6   uint32[]   4+4n     uint32 count + uint32 values
7   string[]   4+var    uint32 count + Delphi strings
```

### Array Format Detail

```
+0x00   4     uint32   Element count (K)
+0x04   var   type[K]  K values of the element type
```

For string arrays (type 7), each element is a Delphi string (uint32 length + bytes).

### Delphi String Format

```
+0x00   4     uint32   String length in bytes (0 for empty string)
+0x04   n     char[n]  ASCII string data (no null terminator)
```

## Field-Count Categories

The PAR format has no explicit type/schema system. Instead, all entries with the same number of fields share the same column layout. The SDK defines these layouts via Excel sheets:

```
Field Count → SDK Sheet → Object Type
───────────────────────────────────────
  1         SoundPacksSet, CameraTracks, SpecialUpdatesLinks
  2         PierceMissileSlots
  6         SoundPack, UnitTalks
  9         MeshButtonViewParams
 16         SimplePassives
 17         Dynamics
 21         UnitMeshes
 22         Equipment
 26         BasicUnits, BasicUnitsAnimations
 30         Passives, Markers, RollingStones
 33         Containers
 35         Gates
 39         CustomArtefacts
 42         Teleports
 43         EquipmentArtefacts
 47         SpecialArtefacts
 49         Missiles, AlchemyFormulaArtefacts
 52         InventoryDialogParams
 53         MagicCard
 64         CustomScalers
 65         Units, ShopUnits
 67         Weapon
 68         CommonGameParams
 76         MagicClub
 77         Traps
101         PotionArtefacts
121         Heroes
158         HeroTalks
215         UnitsAnimationsFiles
216         UnitsAnimations
```

## Class Hierarchy (classmask.h)

The first field of most entries is `classID`, a bitmask identifying the object type. The hierarchy uses bitfield inheritance:

```
OTHER           0x00000001
├─ WORLD        0x00000021
├─ PLAYER       0x00000041
├─ UNITLAND     0x00000101
│  ├─ UNITHERO  0x01000101
│  └─ UNITHORSE 0x02000101
└─ ...

GENERIC         0x00000002
├─ STOREABLE    0x00000012
│  ├─ UNITBASE        0x00000212
│  │  └─ UNIT         0x00010212  → 65/68-field entries (NPCs, monsters)
│  │     ├─ HERO      0x01010212  → 121-field entries
│  │     └─ SHOPUNIT  0x02010212  → 65-field entries (merchants)
│  ├─ DYNAMIC         0x00000412  → 17-field entries (particles, effects)
│  ├─ SIMPLEPASSIVE   0x00000812  → 16-field entries (static objects)
│  │  └─ PASSIVE      0x00010812  → 30-field entries
│  │     ├─ ARTEFACT  0x00050812
│  │     │  ├─ EQUIPMENTARTEFACT      0x01050812  → 43 fields
│  │     │  ├─ POTIONARTEFACT         0x02050812  → 101 fields
│  │     │  ├─ SPECIALARTEFACT        0x04050812  → 47 fields
│  │     │  ├─ CUSTOMARTEFACT         0x08050812  → 39 fields
│  │     │  └─ ALCHEMYFORMULAARTEFACT 0x10050812  → 49 fields
│  │     ├─ TRAP        0x00090812  → 77 fields
│  │     ├─ GATE        0x00110812  → 35 fields
│  │     ├─ TELEPORT    0x00210812  → 42 fields
│  │     ├─ CONTAINER   0x00810812  → 33 fields
│  │     └─ HOUSE       0x00410812
│  └─ MISSILE     0x00001012  → 49-field entries
├─ EQUIPMENT  0x00000022  → 22-field entries (armor, shields)
│  ├─ WEAPON     0x00000122  → 67-field entries
│  │  └─ MAGICCLUB 0x00010122  → 76-field entries (magic staffs)
│  └─ MAGICCARD  0x00000422  → 53-field entries (spells)
└─ VIRTUAL    0x00000112
```

## Reference Fields

Fields prefixed with `$` in the SDK are **references** to other PAR entries. They store a uint32 hash/ID that maps to another entry's identifier. Examples:

- `$soundPackID` → references a SoundPack entry
- `$defaultWeaponID` → references a Weapon entry
- `$killExplosionID` → references a Dynamics entry (particle effect)
- `$deadBodyItemsID[]` → array of item references (loot table)

## Observations from TwoWorlds.par

```
File size (compressed):   99,750 bytes
File size (decompressed): 1,702,450 bytes
Lists:                    602
Total entries:            5,087
PAR version:              0x600
Wrapper:                  Yes (dual-stream zlib)
```

Entry distribution (top categories):
```
 16 fields (SimplePassives):   1053 entries
 65 fields (Units):             841 entries
 30 fields (Passives/Markers):  702 entries
 21 fields (UnitMeshes):        618 entries
  6 fields (SoundPack):         954 entries
  9 fields (ViewParams):        210 entries
```

## Engine Notes

- **Engine-Einheiten (A-suffix):** Fields ending with `A` (e.g. `sightRangeA`, `weaponMaxRangeA`) use engine distance units. Rough conversion: 1 meter ≈ 64 units.
- **Ticks:** Time values in ticks. Approximately 20 ticks = 1 second.
- **Bitmasken:** Many fields use bitmasks. Individual bits enable/disable specific behaviors.
- **Color values:** Stored as signed int32 in ARGB format (e.g. -16776961 = 0xFF0000FF = blue).
- **Delphi heritage:** The format uses Delphi-style strings and conventions, consistent with Reality Pump's Delphi-based toolchain.
