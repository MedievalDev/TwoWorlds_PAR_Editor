# Anleitung — TW1 PAR Editor v1.3

## Installation

1. **Python 3.6+** installieren (bei Windows: [python.org](https://python.org), Haken bei „Add to PATH" setzen)
2. Alle vier Dateien in denselben Ordner legen:
   - `tw1_par_editor.py`
   - `tw1_sdk_labels.json`
   - `tw1_sdk_descriptions.json`
   - `START_PAR_EDITOR.bat`
3. `START_PAR_EDITOR.bat` doppelklicken (oder: `python tw1_par_editor.py`)

Der Editor zeigt beim Start in der Statusleiste: **„1808 SDK-Feldnamen, 1699 Beschreibungen geladen"**

## PAR-Datei öffnen

`Datei → Open PAR` (Ctrl+O)

Die `TwoWorlds.par` liegt in den WD-Archiven des Spiels. Zum Entpacken:
- [TW2WDTool](https://www.moddb.com/games/two-worlds/downloads) oder WDPackager aus dem SDK verwenden
- Die `.par` ist zlib-komprimiert — der Editor erkennt das automatisch

## Oberfläche

**Links: Baumansicht**
- Jeder Knoten = eine Liste mit Einträgen
- Format: `Liste 42 (MO_WOLF_01...) [12]` — erster Eintrag + Anzahl
- Einträge zeigen Name und Modell-Pfad

**Rechts: Detail-Ansicht**
- Alle Felder des ausgewählten Eintrags
- Format pro Zeile: `[Index] Labelname  Typ  = Wert`

## Felder verstehen

Jedes Feld hat:
- **Index** `[0]` `[1]` ... — Position in der Datenstruktur
- **Label** (cyan) — SDK-Feldname, z.B. `initParamHP`, `moveRunSpeed`
- **Typ** (lila) — Datentyp: int32, float32, uint32, string, arrays
- **Wert** (grün/gelb/orange) — editierbarer Wert

### Tooltip-Beschreibungen

**Maus über ein Label halten** → nach 400ms erscheint ein Tooltip mit deutscher Erklärung:

| Label | Tooltip |
|-------|---------|
| `classID` | Objekt-Klassentyp (classmask.h). Bestimmt Kategorie: UNIT, WEAPON, PASSIVE etc. |
| `initParamHP` | Start-Trefferpunkte der Einheit. |
| `moveRunSpeed` | Laufgeschwindigkeit der Einheit. Höher = schneller. |
| `cardMagicSchool` | Magie-Schule: 0=Luft, 1=Feuer, 2=Wasser, 3=Erde, 4=Nekromantie. |
| `artPrice` | Basispreis beim Händler (Gold). |
| `wpDamSlashingMax` | Waffen-Hieb-Schaden (Maximum). |

### Labels bearbeiten

- **Kein Label?** → auf `···` klicken → Namen eingeben
- **Rechtsklick** auf ein Label → Umbenennen / Entfernen
- Änderungen werden in `~/tw1_par_labels.json` gespeichert
- Labels gelten pro Feldanzahl-Kategorie (alle 65-Feld-Einträge teilen sich dieselben Labels)

## Werte editieren

1. Eintrag im Baum auswählen
2. Wert im Eingabefeld ändern
3. `Datei → Save PAR` (Ctrl+S) — speichert byte-identisch zurück

**Unterstützte Typen:**
- `int32` — Ganzzahl (z.B. HP, Schaden, Geschwindigkeit)
- `uint32` — Vorzeichenlose Ganzzahl (z.B. Referenzen mit $-Prefix)
- `float32` — Gleitkommazahl (z.B. Skalierungen)
- `string` — Text (z.B. Mesh-Pfade, Sound-Dateien)
- Arrays — nur Anzeige, nicht direkt editierbar

## JSON Export/Import

**Export:** `Datei → Export JSON` — erzeugt eine lesbare JSON-Datei mit Labels:
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

**Import:** `Datei → Import JSON` — lädt JSON zurück als PAR-Daten (zum Speichern als .par)

## Einträge verwalten (Rechtsklick-Menü)

Rechtsklick auf einen Eintrag im Baum öffnet ein Kontextmenü:

- **Duplicate** — Erstellt eine Kopie des Eintrags. Der nächste Name wird automatisch vorgeschlagen (z.B. `ROADSIGN_L_13` → `ROADSIGN_L_14`). String-Felder die den alten Namen enthalten (z.B. Mesh-Pfad) werden automatisch aktualisiert.
- **Rename** — Benennt den Eintrag um, aktualisiert auch String-Felder.
- **Delete** — Löscht den Eintrag (mit Bestätigungsdialog).

Rechtsklick auf einen **Listen-Knoten**:
- **Add New Entry** — Fügt einen leeren Eintrag mit gleicher Feld-Struktur hinzu.
- **Duplicate Last Entry** — Schnellzugriff zum Klonen des letzten Eintrags.

## Compare & Merge (PAR-Dateien vergleichen und zusammenführen)

Der "Compare & Merge"-Tab ermöglicht es, zwei PAR-Dateien Feld für Feld zu vergleichen und Änderungen selektiv zu übernehmen.

### Dateien laden

- **Source PAR** — Die PAR-Datei die du bearbeiten willst (deine Arbeitsdatei)
- **Input PAR** — Die PAR-Datei mit Änderungen die du übernehmen willst (z.B. eine andere Mod)
- **Original PAR** (optional) — Die unmodifizierte `TwoWorlds.par` als Referenz. Der Pfad wird in `tw1_par_compare_config.json` gespeichert und beim nächsten Start automatisch geladen

### Vergleichen

Klick auf **Compare** — das Tool matcht Einträge über ihren Namen (z.B. `SWORD_01` in Source wird mit `SWORD_01` in Input verglichen, egal an welcher Position sie stehen) und vergleicht dann jedes einzelne Feld.

### Farbcodierung

- **Gelb** — Gleicher Eintrag existiert in beiden Dateien, aber ein oder mehrere Feldwerte sind unterschiedlich (Konflikt)
- **Grün** — Eintrag existiert nur in der Input-Datei (neuer Eintrag)
- **Blau** — Eintrag existiert nur in der Source-Datei (nichts zu mergen)

Identische Einträge werden nicht angezeigt — nur die Unterschiede.

### Merge durchführen

1. Checkboxen (☐/☑) anklicken bei den Einträgen die du übernehmen willst
2. Mit **Select All** / **Deselect All** alle auf einmal setzen
3. **Merge Selected into Source** klicken — die ausgewählten Werte werden in die Source-Daten geschrieben
4. **Save Merged PAR** — speichert die zusammengeführte Datei als `.par`

### Anwendungsbeispiel

Du hast eine eigene Mod-PAR (Source) und möchtest Balancing-Änderungen aus einer anderen Mod (Input) übernehmen, ohne deine eigenen Änderungen zu verlieren:

1. Source laden: deine Mod-PAR
2. Input laden: die andere Mod-PAR
3. Original laden: die unmodifizierte `TwoWorlds.par`
4. Compare klicken
5. In der Tabelle siehst du genau welche Werte sich unterscheiden, und wenn das Original geladen ist auch den Originalwert als Referenz
6. Gewünschte Änderungen anhaken → Merge → Save

## Mesh-Feld Syntax

Das `mesh`-Feld (Feldindex 1) bei SimplePassives, Passives und anderen Objekten unterstützt eine erweiterte Syntax die über einfache Dateipfade hinausgeht. Die Engine nutzt diese Syntax um Mesh-Varianten, Textur-Overrides und LOD-Bereiche in einem einzigen String-Feld zu definieren.

### Einfacher Pfad

```
Houses\VILLAGE 02\STABLE_02_04.vdf
```

### Mesh-Varianten mit Bereichsangabe

```
Houses\TOWN 02\STAIRS_02_0[1-4].vdf
```

Die Notation `[1-4]` definiert mehrere Mesh-Varianten in einem einzigen Eintrag. Das Beispiel expandiert zu vier Meshes: `STAIRS_02_01.vdf` bis `STAIRS_02_04.vdf`. Im Two Worlds Editor können diese Varianten per Rechtsklick auf das platzierte Objekt durchgeschaltet werden. Ideal für Objekte die gleiche Parameter aber unterschiedliches Aussehen haben (z.B. verschiedene Hausstile, Zaunabschnitte, Treppen-Varianten).

### Textur-Override

```
Houses\VILLAGE 02\STABLE_02_04.vdf:ALTERNATIVE_TEXTUR.dds
```

Mit `:textur.dds` nach dem VDF-Pfad wird die Standard-Textur aus der VDF-Datei überschrieben. So kann dasselbe 3D-Modell mit verschiedenen Texturen wiederverwendet werden, ohne die Mesh-Datei zu duplizieren.

### Mehrere Textur-Varianten

```
Houses\TOWN 02\STAIRS_02_0[1-4].vdf:STAIRS_02.dds|STAIRS_04.dds
```

Der `|`-Separator definiert zusätzliche Textur-Varianten. Diese entsprechen den Spalten `#mesh2`, `#mesh3` usw. im SDK-Spreadsheet (`TwoWorlds.xls`).

### Zusammenfassung der Syntax

```
Basis:      pfad.vdf
Varianten:  pfad_[1-4].vdf
Textur:     pfad.vdf:textur.dds
Multi-Tex:  pfad.vdf:textur1.dds|textur2.dds
Kombiniert: pfad_[1-4].vdf:textur1.dds|textur2.dds
```

**Wichtig:** Im SDK-Spreadsheet (`TwoWorlds.xls`) werden die Textur-Teile in separate Spalten (`#mesh2`, `#mesh3`) aufgeteilt. In der PAR-Datei ist aber alles ein einziger zusammenhängender String im `mesh`-Feld (Feldindex 1). Der PAR Editor zeigt diesen String komplett an — zum Bearbeiten einfach den gesamten String inkl. `:` und `|` Trennzeichen editieren.

## Tastenkürzel

| Kürzel | Aktion |
|--------|--------|
| Ctrl+O | PAR öffnen |
| Ctrl+S | PAR speichern |
| Ctrl+Shift+S | Speichern unter... |
| Ctrl+E | JSON exportieren |
| Ctrl+I | JSON importieren |

## Wichtige Eintrags-Kategorien

| Felder | Typ | Beispiele |
|--------|-----|-----------|
| 6 | Sounds | SND_MENU_GO, SND_SWORD_01 |
| 16 | Statische Objekte | HUGEGATE, QUD_FIREPLACE |
| 26 | Basistiere | MO_RABBIT_01, MO_BIRD_01 |
| 53 | Zaubersprüche | MAGIC_LIGHTING, MAGIC_HEAL |
| 65 | NPCs/Monster | MO_WOLF_01, NPC_Q_005, SHOPUNIT_1 |
| 67 | Waffen | WP_SWORD_01, WP_BOW_01 |
| 76 | Magische Stäbe | WP_STAFF_01 |
| 77 | Fallen | TRAP_HOLD_01 |
| 101 | Tränke/Zutaten | POTION_HEALING_01 |
| 121 | Helden | HEROSINGLE, HERO1 |

## classID-Werte (classmask.h)

Das erste Feld (`classID`) definiert den Objekt-Typ. Wichtige Werte:

| Hex | Dezimal | Typ |
|-----|---------|-----|
| 0x00010212 | 66066 | UNIT (Monster/NPC) |
| 0x01010212 | 16843282 | HERO |
| 0x02010212 | 33620498 | SHOPUNIT |
| 0x00000122 | 290 | WEAPON |
| 0x00000422 | 1058 | MAGICCARD |
| 0x02050812 | 33884178 | POTIONARTEFACT |
| 0x04050812 | 67438610 | SPECIALARTEFACT |
| 0x00810812 | 8456210 | CONTAINER |

## Tipps

- **Backup!** Immer eine Kopie der Original-PAR behalten
- **JSON als Arbeitskopie** — Export als JSON, dort mit Texteditor suchen/ersetzen, dann reimportieren
- **$ = Referenz** — Felder mit `$` Prefix sind IDs die auf andere PAR-Einträge verweisen
- **[] = Array** — Felder mit `[]` Suffix enthalten mehrere Werte
- **Ticks** — Viele Zeitwerte sind in Engine-Ticks (ca. 20 Ticks = 1 Sekunde)
