#!/usr/bin/env python3
"""TW1 PAR Editor v1.3 — View, edit, and export Two Worlds 1 .par parameter files
   Now with SDK field labels, duplicate/delete/rename entries"""

import struct
import os
import sys
import json
import io
import zlib
import copy
from pathlib import Path
from collections import OrderedDict

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
    HAS_TK = True
except ImportError:
    HAS_TK = False

# ═══════════════════════════════════════════════════════════════════════════════
# PAR FORMAT CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

PAR_MAGIC = b'PAR\x00'
PAR_VERSION_TW1 = 0x600

# Data type IDs
TYPE_INT32        = 0
TYPE_FLOAT32      = 1
TYPE_UINT32       = 2
TYPE_STRING       = 3
TYPE_ARRAY_INT32  = 4
TYPE_ARRAY_FLOAT  = 5
TYPE_ARRAY_UINT32 = 6
TYPE_ARRAY_STR    = 7

TYPE_NAMES = {
    0: "int32",
    1: "float32",
    2: "uint32",
    3: "string",
    4: "int32[]",
    5: "float32[]",
    6: "uint32[]",
    7: "string[]",
}

# ═══════════════════════════════════════════════════════════════════════════════
# PAR DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

class ParFile:
    """Represents a complete PAR file."""
    def __init__(self):
        self.version = PAR_VERSION_TW1
        self.lists = []       # [ParList, ...]
        self.filepath = ""
        self.wrapper_header = None   # zlib wrapper header (stream 1)
        self.was_compressed = False   # file was zlib-compressed on disk
        self.trailing_data = None     # bytes after parsed content

class ParList:
    """A list within the PAR file."""
    def __init__(self):
        self.unknown1 = 0
        self.unknown2 = 0
        self.entries = []     # [ParEntry, ...]

class ParEntry:
    """A single named entry with typed data fields."""
    def __init__(self):
        self.name = ""
        self.unknown_byte = 0
        self.unknown_u16a = 0
        self.unknown_u16b = 0
        self.fields = []      # [ParField, ...]

class ParField:
    """A single typed data field within an entry."""
    def __init__(self, dtype=0, value=None):
        self.dtype = dtype    # Type ID (0-7)
        self.value = value    # Python value (int, float, str, list)

# ═══════════════════════════════════════════════════════════════════════════════
# PAR BINARY READER
# ═══════════════════════════════════════════════════════════════════════════════

class ParReader:
    """Reads PAR binary format."""

    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.size = len(data)

    def read_bytes(self, n):
        if self.pos + n > self.size:
            raise ValueError(f"Read past end at offset 0x{self.pos:X}, need {n} bytes")
        result = self.data[self.pos:self.pos + n]
        self.pos += n
        return result

    def read_u8(self):
        return struct.unpack_from('<B', self.data, self._advance(1))[0]

    def read_i8(self):
        return struct.unpack_from('<b', self.data, self._advance(1))[0]

    def read_u16(self):
        return struct.unpack_from('<H', self.data, self._advance(2))[0]

    def read_u32(self):
        return struct.unpack_from('<I', self.data, self._advance(4))[0]

    def read_i32(self):
        return struct.unpack_from('<i', self.data, self._advance(4))[0]

    def read_f32(self):
        return struct.unpack_from('<f', self.data, self._advance(4))[0]

    def read_u64(self):
        return struct.unpack_from('<Q', self.data, self._advance(8))[0]

    def read_delphi_string(self):
        length = self.read_u32()
        if length > 1000000:
            raise ValueError(f"Unreasonable string length {length} at 0x{self.pos:X}")
        if length == 0:
            return ""
        raw = self.read_bytes(length)
        return raw.decode('ascii', errors='replace')

    def _advance(self, n):
        if self.pos + n > self.size:
            raise ValueError(f"Read past end at offset 0x{self.pos:X}")
        p = self.pos
        self.pos += n
        return p



def read_par(data):
    """Parse a PAR binary file. Returns ParFile."""
    r = ParReader(data)

    # Header
    magic = r.read_bytes(4)
    if magic != PAR_MAGIC:
        raise ValueError(f"Not a PAR file (header: {magic!r}, expected {PAR_MAGIC!r})")

    par = ParFile()
    par.version = r.read_u32()

    # Root list
    list_count = r.read_u32()
    _pad = r.read_u32()       # unknown pad

    for li in range(list_count):
        pl = ParList()
        pl.unknown1 = r.read_u32()
        pl.unknown2 = r.read_u32()

        # Prefixed Array<List Entry>
        entry_count = r.read_u32()

        for ei in range(entry_count):
            entry = ParEntry()
            entry.name = r.read_delphi_string()
            entry.unknown_byte = r.read_i8()

            data_entry_count = r.read_u16()
            entry.unknown_u16a = r.read_u16()
            entry.unknown_u16b = r.read_u16()

            # Data Type List
            type_list = []
            for _ in range(data_entry_count):
                type_list.append(r.read_u8())

            # Data Entry List
            for dtype in type_list:
                field = ParField(dtype)

                if dtype == TYPE_INT32:
                    field.value = r.read_i32()
                elif dtype == TYPE_FLOAT32:
                    field.value = r.read_f32()
                elif dtype == TYPE_UINT32:
                    field.value = r.read_u32()
                elif dtype == TYPE_STRING:
                    field.value = r.read_delphi_string()
                elif dtype == TYPE_ARRAY_INT32:
                    field.value = _read_extra_array(r, 'i')
                elif dtype == TYPE_ARRAY_FLOAT:
                    field.value = _read_extra_array(r, 'f')
                elif dtype == TYPE_ARRAY_UINT32:
                    field.value = _read_extra_array(r, 'I')
                elif dtype == TYPE_ARRAY_STR:
                    field.value = _read_extra_string_array(r)
                else:
                    raise ValueError(f"Unknown data type {dtype} at 0x{r.pos:X}")

                entry.fields.append(field)

            pl.entries.append(entry)
        par.lists.append(pl)

    # Preserve trailing data (some PAR files have extra data after the listed entries)
    if r.pos < r.size:
        par.trailing_data = data[r.pos:]

    return par


def _read_extra_array(reader, fmt_char):
    """Read Extra Prefixed Array<T> for numeric types."""
    check = reader.read_u64()
    if check == 0:
        return []
    length = reader.read_u32()
    values = []
    for _ in range(length):
        if fmt_char == 'i':
            values.append(reader.read_i32())
        elif fmt_char == 'f':
            values.append(reader.read_f32())
        elif fmt_char == 'I':
            values.append(reader.read_u32())
    return values


def _read_extra_string_array(reader):
    """Read Extra Prefixed Array<Delphi ASCII>."""
    check = reader.read_u64()
    if check == 0:
        return []
    length = reader.read_u32()
    values = []
    for _ in range(length):
        values.append(reader.read_delphi_string())
    return values


# ═══════════════════════════════════════════════════════════════════════════════
# PAR BINARY WRITER
# ═══════════════════════════════════════════════════════════════════════════════

class ParWriter:
    """Writes PAR binary format."""

    def __init__(self):
        self.buf = io.BytesIO()

    def write_bytes(self, b):
        self.buf.write(b)

    def write_u8(self, v):
        self.buf.write(struct.pack('<B', v & 0xFF))

    def write_i8(self, v):
        self.buf.write(struct.pack('<b', v))

    def write_u16(self, v):
        self.buf.write(struct.pack('<H', v & 0xFFFF))

    def write_u32(self, v):
        self.buf.write(struct.pack('<I', v & 0xFFFFFFFF))

    def write_i32(self, v):
        self.buf.write(struct.pack('<i', v))

    def write_f32(self, v):
        self.buf.write(struct.pack('<f', v))

    def write_u64(self, v):
        self.buf.write(struct.pack('<Q', v))

    def write_delphi_string(self, s):
        encoded = s.encode('ascii', errors='replace')
        self.write_u32(len(encoded))
        self.buf.write(encoded)

    def get_bytes(self):
        return self.buf.getvalue()


def write_par(par):
    """Write a ParFile to binary. Returns bytes."""
    w = ParWriter()

    # Header
    w.write_bytes(PAR_MAGIC)
    w.write_u32(par.version)

    # Root list
    w.write_u32(len(par.lists))
    w.write_u32(0)   # pad

    for pl in par.lists:
        w.write_u32(pl.unknown1)
        w.write_u32(pl.unknown2)

        # Prefixed Array<List Entry>
        w.write_u32(len(pl.entries))

        for entry in pl.entries:
            w.write_delphi_string(entry.name)
            w.write_i8(entry.unknown_byte)

            field_count = len(entry.fields)
            w.write_u16(field_count)
            w.write_u16(entry.unknown_u16a)
            w.write_u16(entry.unknown_u16b)

            # Data Type List
            for field in entry.fields:
                w.write_u8(field.dtype)

            # Data Entry List
            for field in entry.fields:
                dtype = field.dtype
                val = field.value

                if dtype == TYPE_INT32:
                    w.write_i32(int(val))
                elif dtype == TYPE_FLOAT32:
                    w.write_f32(float(val))
                elif dtype == TYPE_UINT32:
                    w.write_u32(int(val))
                elif dtype == TYPE_STRING:
                    w.write_delphi_string(str(val))
                elif dtype == TYPE_ARRAY_INT32:
                    _write_extra_array(w, val, 'i')
                elif dtype == TYPE_ARRAY_FLOAT:
                    _write_extra_array(w, val, 'f')
                elif dtype == TYPE_ARRAY_UINT32:
                    _write_extra_array(w, val, 'I')
                elif dtype == TYPE_ARRAY_STR:
                    _write_extra_string_array(w, val)

    result = w.get_bytes()

    # Append trailing data if present (for byte-perfect roundtrips)
    if getattr(par, 'trailing_data', None):
        result += par.trailing_data

    return result


def _write_extra_array(writer, values, fmt_char):
    """Write Extra Prefixed Array<T> for numeric types."""
    if not values:
        writer.write_u64(0)
        return
    writer.write_u64(1)
    writer.write_u32(len(values))
    for v in values:
        if fmt_char == 'i':
            writer.write_i32(int(v))
        elif fmt_char == 'f':
            writer.write_f32(float(v))
        elif fmt_char == 'I':
            writer.write_u32(int(v))


def _write_extra_string_array(writer, values):
    """Write Extra Prefixed Array<Delphi ASCII>."""
    if not values:
        writer.write_u64(0)
        return
    writer.write_u64(1)
    writer.write_u32(len(values))
    for v in values:
        writer.write_delphi_string(str(v))


# ═══════════════════════════════════════════════════════════════════════════════
# ZLIB WRAPPER (TW1 .par files are double-zlib: wrapper stream + PAR stream)
# ═══════════════════════════════════════════════════════════════════════════════

def decompress_par_file(raw_data):
    """Decompress a .par file from disk.
    
    TW1 .par files consist of two concatenated zlib streams:
      Stream 1 (wrapper): 44 bytes with marker, name, GUID
      Stream 2 (payload): the actual PAR binary data
    
    Returns (par_data, wrapper_bytes_or_None, was_compressed).
    If data is not zlib-compressed, returns (raw_data, None, False).
    """
    # Check for zlib header (0x78 = CMF byte for deflate)
    if len(raw_data) < 4 or raw_data[0] != 0x78:
        # Not compressed — check if it's raw PAR
        if raw_data[:4] == PAR_MAGIC:
            return raw_data, None, False
        raise ValueError(f"Unknown format (header: {raw_data[:4].hex()})")

    # Decompress stream 1 (wrapper)
    dec1 = zlib.decompressobj()
    wrapper = dec1.decompress(raw_data)
    remaining = dec1.unused_data

    if not remaining:
        # Single stream — check if it's PAR directly
        if wrapper[:4] == PAR_MAGIC:
            return wrapper, None, True
        raise ValueError(f"Single zlib stream but not PAR (header: {wrapper[:4].hex()})")

    # Decompress stream 2 (PAR payload)
    dec2 = zlib.decompressobj()
    par_data = dec2.decompress(remaining)

    if par_data[:4] != PAR_MAGIC:
        raise ValueError(f"Stream 2 is not PAR (header: {par_data[:4].hex()})")

    return par_data, wrapper, True


def compress_par_file(par_data, wrapper=None):
    """Compress PAR data back to .par file format.
    
    If wrapper is provided, creates dual-stream zlib (wrapper + PAR).
    Otherwise just compresses the PAR data as a single stream.
    """
    if wrapper is not None:
        # Dual-stream: compress wrapper, then compress PAR, concatenate
        stream1 = zlib.compress(wrapper)
        stream2 = zlib.compress(par_data)
        return stream1 + stream2
    else:
        return zlib.compress(par_data)


# ═══════════════════════════════════════════════════════════════════════════════
# JSON EXPORT / IMPORT
# ═══════════════════════════════════════════════════════════════════════════════

def par_to_dict(par, field_labels=None):
    """Convert ParFile to a serializable dict."""
    result = OrderedDict()
    result["_format"] = "TW1_PAR"
    result["_version"] = par.version

    lists = []
    for li, pl in enumerate(par.lists):
        list_data = OrderedDict()
        list_data["_index"] = li
        list_data["_unknown1"] = pl.unknown1
        list_data["_unknown2"] = pl.unknown2
        list_data["_entry_count"] = len(pl.entries)

        entries = []
        for entry in pl.entries:
            ed = OrderedDict()
            ed["name"] = entry.name
            ed["_unknown_byte"] = entry.unknown_byte
            ed["_unknown_u16a"] = entry.unknown_u16a
            ed["_unknown_u16b"] = entry.unknown_u16b

            fields = []
            field_count = len(entry.fields)
            for fi, field in enumerate(entry.fields):
                fd = OrderedDict()
                # Add label if available
                if field_labels:
                    lbl = field_labels.get(field_count, fi)
                    if lbl:
                        fd["label"] = lbl
                fd["type"] = TYPE_NAMES.get(field.dtype, f"unknown({field.dtype})")
                fd["type_id"] = field.dtype
                fd["value"] = field.value
                fields.append(fd)

            ed["fields"] = fields
            entries.append(ed)

        list_data["entries"] = entries
        lists.append(list_data)

    result["lists"] = lists

    # Preserve trailing data for byte-perfect roundtrips
    if par.trailing_data:
        import base64
        result["_trailing_data"] = base64.b64encode(par.trailing_data).decode('ascii')

    # Preserve wrapper header for compressed roundtrips
    if par.wrapper_header:
        import base64
        result["_wrapper_header"] = base64.b64encode(par.wrapper_header).decode('ascii')
        result["_was_compressed"] = True

    return result


def export_json(par, filepath, field_labels=None):
    """Export ParFile as JSON."""
    data = par_to_dict(par, field_labels)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def import_json(filepath):
    """Import ParFile from JSON."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    par = ParFile()
    par.version = data.get("_version", PAR_VERSION_TW1)

    # Restore trailing data if present
    if "_trailing_data" in data:
        import base64
        par.trailing_data = base64.b64decode(data["_trailing_data"])

    # Restore wrapper header if present
    if "_wrapper_header" in data:
        import base64
        par.wrapper_header = base64.b64decode(data["_wrapper_header"])
        par.was_compressed = data.get("_was_compressed", True)

    for list_data in data.get("lists", []):
        pl = ParList()
        pl.unknown1 = list_data.get("_unknown1", 0)
        pl.unknown2 = list_data.get("_unknown2", 0)

        for ed in list_data.get("entries", []):
            entry = ParEntry()
            entry.name = ed.get("name", "")
            entry.unknown_byte = ed.get("_unknown_byte", 0)
            entry.unknown_u16a = ed.get("_unknown_u16a", 0)
            entry.unknown_u16b = ed.get("_unknown_u16b", 0)

            for fd in ed.get("fields", []):
                field = ParField()
                field.dtype = fd.get("type_id", 0)
                field.value = fd.get("value")

                # Ensure correct Python types
                if field.dtype in (TYPE_INT32, TYPE_UINT32):
                    if field.value is not None:
                        field.value = int(field.value)
                elif field.dtype == TYPE_FLOAT32:
                    if field.value is not None:
                        field.value = float(field.value)
                elif field.dtype == TYPE_STRING:
                    if field.value is not None:
                        field.value = str(field.value)

                entry.fields.append(field)

            pl.entries.append(entry)
        par.lists.append(pl)

    return par


# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
# FIELD LABEL SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

# Labels are stored per field-count category (e.g. all 65-field entries share labels)
# This is because the PAR format uses the same column layout for all entries
# with the same number of fields.
#
# Label sources (in order of priority):
#   1. User overrides (~/tw1_par_labels.json)
#   2. SDK labels (tw1_sdk_labels.json - generated from TwoWorlds.xls)
#   3. Minimal fallback defaults (hardcoded below)

DEFAULT_LABELS = {
    6: {0: "soundCue", 1: "volume", 2: "distanceMinA", 3: "distanceMaxA",
        4: "soundFlags", 5: "playPriority"},
    65: {0: "classID", 1: "mesh", 15: "moveWalkSpeed", 16: "moveRunSpeed",
         34: "initParamHP", 35: "initParamDamage", 36: "initParamAttack",
         37: "initParamDefence"},
}


def _find_sdk_labels_path():
    """Find tw1_sdk_labels.json next to the script or in common locations."""
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tw1_sdk_labels.json'),
        os.path.join(os.path.expanduser('~'), 'tw1_sdk_labels.json'),
        os.path.join(os.getcwd(), 'tw1_sdk_labels.json'),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


class FieldLabels:
    """Manages field labels per field-count category.
    Loads SDK labels from tw1_sdk_labels.json, then user overrides on top."""

    def __init__(self, user_filepath=None):
        self.labels = {}       # {field_count: {field_idx: "label"}}
        self.user_filepath = user_filepath

        # 1. Minimal fallback defaults
        for fc, fields in DEFAULT_LABELS.items():
            self.labels[fc] = dict(fields)

        # 2. Load SDK labels (from tw1_sdk_labels.json)
        sdk_path = _find_sdk_labels_path()
        if sdk_path:
            self._load_json(sdk_path)

        # 3. Load user overrides on top
        if user_filepath and os.path.isfile(user_filepath):
            self._load_json(user_filepath)

    def get(self, field_count, field_idx):
        """Get label for a field, or None."""
        fc_labels = self.labels.get(field_count, {})
        return fc_labels.get(field_idx)

    def set(self, field_count, field_idx, label):
        """Set a user label (saved to user file)."""
        if field_count not in self.labels:
            self.labels[field_count] = {}
        self.labels[field_count][field_idx] = label
        self._save_user()

    def remove(self, field_count, field_idx):
        """Remove a label."""
        if field_count in self.labels and field_idx in self.labels[field_count]:
            del self.labels[field_count][field_idx]
            self._save_user()

    def _load_json(self, filepath):
        """Load labels from a JSON file, merging into existing."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for fc_str, fields in data.items():
                fc = int(fc_str)
                if fc not in self.labels:
                    self.labels[fc] = {}
                for fi_str, lbl in fields.items():
                    self.labels[fc][int(fi_str)] = lbl
        except Exception:
            pass

    def _save_user(self):
        """Save user overrides to user file."""
        if not self.user_filepath:
            return
        data = {}
        for fc, fields in self.labels.items():
            data[str(fc)] = {str(fi): lbl for fi, lbl in fields.items()}
        try:
            with open(self.user_filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


class FieldDescriptions:
    """Loads German field descriptions from tw1_sdk_descriptions.json."""

    def __init__(self):
        self.descs = {}  # {field_count: {field_idx: "description"}}
        # Look for descriptions file next to script, home, cwd
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tw1_sdk_descriptions.json'),
            os.path.join(os.path.expanduser('~'), 'tw1_sdk_descriptions.json'),
            os.path.join(os.getcwd(), 'tw1_sdk_descriptions.json'),
        ]
        for path in candidates:
            if os.path.isfile(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    for fc_str, fields in data.items():
                        fc = int(fc_str)
                        self.descs[fc] = {int(fi): d for fi, d in fields.items()}
                except Exception:
                    pass
                break

    def get(self, field_count, field_idx):
        return self.descs.get(field_count, {}).get(field_idx)


class ToolTip:
    """Hover-Tooltip für Tkinter-Widgets."""

    def __init__(self, widget, text='', delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tip_window = None
        self._after_id = None
        widget.bind('<Enter>', self._schedule)
        widget.bind('<Leave>', self._hide)
        widget.bind('<ButtonPress>', self._hide)

    def _schedule(self, event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        if not self.text or self.tip_window:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f'+{x}+{y}')
        label = tk.Label(tw, text=self.text, justify='left',
                         background='#FFFFDD', foreground='#333333',
                         relief='solid', borderwidth=1,
                         font=('Segoe UI', 9), wraplength=420, padx=6, pady=4)
        label.pack()

    def _hide(self, event=None):
        self._cancel()
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

    def update_text(self, text):
        self.text = text


class ListboxToolTip:
    """Tooltip für Tkinter Listbox — zeigt Beschreibung je nach Zeile unter dem Cursor."""

    def __init__(self, listbox, delay=350):
        self.listbox = listbox
        self.delay = delay
        self.tip_window = None
        self._after_id = None
        self._last_index = None
        self._get_desc = None  # callback: index -> description or None
        listbox.bind('<Motion>', self._on_motion)
        listbox.bind('<Leave>', self._hide)
        listbox.bind('<ButtonPress>', self._hide)

    def set_callback(self, fn):
        """Set callback fn(index) -> str or None."""
        self._get_desc = fn

    def _on_motion(self, event):
        idx = self.listbox.nearest(event.y)
        if idx < 0 or idx == self._last_index:
            return
        self._last_index = idx
        self._cancel()
        self._hide()
        self._after_id = self.listbox.after(self.delay, lambda: self._show(idx, event))

    def _cancel(self):
        if self._after_id:
            self.listbox.after_cancel(self._after_id)
            self._after_id = None

    def _show(self, idx, event):
        if not self._get_desc or self.tip_window:
            return
        text = self._get_desc(idx)
        if not text:
            return
        x = self.listbox.winfo_rootx() + 20
        y = self.listbox.winfo_rooty() + event.y + 20
        self.tip_window = tw = tk.Toplevel(self.listbox)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f'+{x}+{y}')
        label = tk.Label(tw, text=text, justify='left',
                         background='#FFFFDD', foreground='#333333',
                         relief='solid', borderwidth=1,
                         font=('Segoe UI', 9), wraplength=420, padx=6, pady=4)
        label.pack()

    def _hide(self, event=None):
        self._cancel()
        self._last_index = None
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


# ═══════════════════════════════════════════════════════════════════════════════
# GUI
# ═══════════════════════════════════════════════════════════════════════════════

class ParEditorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TW1 PAR Editor v1.3")
        self.root.geometry("1200x750")
        self.root.minsize(900, 550)

        self.par = None           # Current ParFile
        self.filepath = ""        # Current file path
        self.modified = False     # Unsaved changes flag
        self.search_results = []  # (list_idx, entry_idx) tuples
        self.search_idx = 0       # Current result index

        # Compare & Merge state
        self.cmp_source = None     # ParFile
        self.cmp_input = None      # ParFile
        self.cmp_original = None   # ParFile (optional reference)
        self.cmp_diffs = []        # list of diff dicts
        self.cmp_checks = {}       # diff_idx -> BooleanVar
        self._cmp_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__))
                                              if '__file__' in dir() else '.',
                                              'tw1_par_compare_config.json')
        self._cmp_original_path = self._load_cmp_config()

        # Field labels (saved next to the PAR file or in home dir)
        default_labels_path = os.path.join(os.path.expanduser('~'), 'tw1_par_labels.json')
        self.field_labels = FieldLabels(default_labels_path)
        self.field_descs = FieldDescriptions()

        self._setup_theme()
        self._build_ui()
        self._bind_keys()

    # ── Theme ──

    def _setup_theme(self):
        self.BG = "#1e1e1e"
        self.FG = "#d4d4d4"
        self.BG2 = "#252526"
        self.BG3 = "#2d2d30"
        self.BG4 = "#333337"
        self.ACCENT = "#0e639c"
        self.GREEN = "#4ec9b0"
        self.YELLOW = "#dcdcaa"
        self.RED = "#f44747"
        self.ORANGE = "#ce9178"
        self.BLUE = "#569cd6"
        self.PURPLE = "#c586c0"

        self.root.configure(bg=self.BG)

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', background=self.BG, foreground=self.FG,
                        fieldbackground=self.BG2)
        style.configure('TFrame', background=self.BG)
        style.configure('TLabel', background=self.BG, foreground=self.FG,
                        font=('Segoe UI', 10))
        style.configure('TButton', background=self.BG3, foreground=self.FG,
                        font=('Segoe UI', 10), borderwidth=1, relief='flat',
                        padding=(10, 4))
        style.map('TButton', background=[('active', self.ACCENT)])
        style.configure('Accent.TButton', background=self.ACCENT,
                        foreground='#ffffff')
        style.map('Accent.TButton', background=[('active', '#1177bb')])
        style.configure('Small.TButton', background=self.BG3, foreground=self.FG,
                        font=('Segoe UI', 9), padding=(6, 2))
        style.configure('Treeview', background=self.BG2, foreground=self.FG,
                        fieldbackground=self.BG2, font=('Consolas', 10),
                        rowheight=22)
        style.configure('Treeview.Heading', background=self.BG3,
                        foreground=self.FG, font=('Segoe UI', 10, 'bold'))
        style.map('Treeview', background=[('selected', self.ACCENT)])
        style.configure('TLabelframe', background=self.BG, foreground=self.FG)
        style.configure('TLabelframe.Label', background=self.BG,
                        foreground=self.YELLOW, font=('Segoe UI', 10, 'bold'))
        style.configure('Title.TLabel', background=self.BG,
                        foreground=self.ORANGE, font=('Segoe UI', 14, 'bold'))
        style.configure('Info.TLabel', background=self.BG,
                        foreground=self.BLUE, font=('Consolas', 10))
        style.configure('Dim.TLabel', background=self.BG,
                        foreground='#666666', font=('Segoe UI', 9))
        style.configure('Status.TLabel', background=self.BG3,
                        foreground=self.FG, font=('Segoe UI', 9),
                        padding=(8, 4))
        style.configure('TPanedwindow', background=self.BG)
        style.configure('TNotebook', background=self.BG)
        style.configure('TNotebook.Tab', background=self.BG3, foreground=self.FG,
                         padding=(12, 6), font=('Segoe UI', 10))
        style.map('TNotebook.Tab',
                  background=[('selected', self.BG2)],
                  foreground=[('selected', self.GREEN)])

    # ── UI Build ──

    def _build_ui(self):
        # ── Menu Bar ──
        menubar = tk.Menu(self.root, bg=self.BG3, fg=self.FG,
                          activebackground=self.ACCENT, activeforeground='#fff',
                          relief='flat', font=('Segoe UI', 10))

        file_menu = tk.Menu(menubar, tearoff=0, bg=self.BG3, fg=self.FG,
                            activebackground=self.ACCENT, activeforeground='#fff',
                            font=('Segoe UI', 10))
        file_menu.add_command(label="Open PAR...", command=self._open_par,
                              accelerator="Ctrl+O")
        file_menu.add_command(label="Open JSON...", command=self._open_json)
        file_menu.add_separator()
        file_menu.add_command(label="Save", command=self._save,
                              accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self._save_as,
                              accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Export JSON...", command=self._export_json)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        # Compare menu
        compare_menu = tk.Menu(menubar, tearoff=0, bg=self.BG3, fg=self.FG,
                               activebackground=self.ACCENT, activeforeground='#fff',
                               font=('Segoe UI', 10))
        compare_menu.add_command(label="Open Compare Tab",
                                 command=lambda: self.notebook.select(1))
        compare_menu.add_separator()
        compare_menu.add_command(label="Set Original PAR...",
                                 command=self._cmp_set_original)
        menubar.add_cascade(label="Compare", menu=compare_menu)

        self.root.config(menu=menubar)

        # ── Toolbar ──
        toolbar = ttk.Frame(self.root, padding=(8, 6))
        toolbar.pack(fill='x')

        ttk.Button(toolbar, text="\u2B9C Open", command=self._open_par,
                   style='Small.TButton').pack(side='left', padx=(0, 4))
        ttk.Button(toolbar, text="\u25A0 Save", command=self._save,
                   style='Small.TButton').pack(side='left', padx=(0, 4))
        ttk.Button(toolbar, text="\u2913 Export JSON", command=self._export_json,
                   style='Small.TButton').pack(side='left', padx=(0, 16))

        # Search
        ttk.Label(toolbar, text="Search:").pack(side='left', padx=(0, 4))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var,
                                       font=('Consolas', 10), width=30)
        self.search_entry.pack(side='left', padx=(0, 4))
        ttk.Button(toolbar, text="\u25B6", command=self._search_next,
                   style='Small.TButton', width=3).pack(side='left', padx=(0, 2))
        self.search_label = ttk.Label(toolbar, text="", style='Dim.TLabel')
        self.search_label.pack(side='left', padx=(4, 0))

        # File info on right
        self.file_label = ttk.Label(toolbar, text="No file loaded",
                                     style='Dim.TLabel')
        self.file_label.pack(side='right')

        # ── Notebook (Editor + Compare & Merge) ──
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=4, pady=(0, 4))

        # Tab 1: Editor
        editor_tab = ttk.Frame(self.notebook)
        self.notebook.add(editor_tab, text="  Editor  ")

        paned = tk.PanedWindow(editor_tab, orient='horizontal', bg=self.BG,
                                sashwidth=4, sashrelief='flat')
        paned.pack(fill='both', expand=True)

        # Left: Tree
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, width=420, minsize=250)

        tree_label = ttk.Label(left_frame, text="  Lists & Entries",
                                style='TLabel', font=('Segoe UI', 10, 'bold'))
        tree_label.pack(fill='x', pady=(0, 2))

        tree_container = ttk.Frame(left_frame)
        tree_container.pack(fill='both', expand=True)

        self.tree = ttk.Treeview(tree_container, show='tree',
                                  selectmode='browse')
        tree_scroll = ttk.Scrollbar(tree_container, orient='vertical',
                                     command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        tree_scroll.pack(side='right', fill='y')

        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.bind('<Button-3>', self._tree_context_menu)

        # Right: Detail Panel
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, minsize=400)

        self.detail_header = ttk.Label(right_frame,
                                        text="Select an entry to view details",
                                        style='Title.TLabel')
        self.detail_header.pack(fill='x', padx=8, pady=(4, 2))

        self.detail_info = ttk.Label(right_frame, text="", style='Info.TLabel')
        self.detail_info.pack(fill='x', padx=8, pady=(0, 4))

        # Scrollable detail area
        detail_container = ttk.Frame(right_frame)
        detail_container.pack(fill='both', expand=True, padx=4)

        self.detail_canvas = tk.Canvas(detail_container, bg=self.BG2,
                                        highlightthickness=0)
        detail_scroll = ttk.Scrollbar(detail_container, orient='vertical',
                                       command=self.detail_canvas.yview)
        self.detail_canvas.configure(yscrollcommand=detail_scroll.set)

        self.detail_inner = tk.Frame(self.detail_canvas, bg=self.BG2)
        self.detail_canvas.create_window((0, 0), window=self.detail_inner,
                                          anchor='nw', tags='inner')

        self.detail_canvas.pack(side='left', fill='both', expand=True)
        detail_scroll.pack(side='right', fill='y')

        self.detail_inner.bind('<Configure>', self._on_detail_configure)
        self.detail_canvas.bind('<Configure>', self._on_canvas_configure)
        # Mouse wheel scrolling
        self.detail_canvas.bind('<Enter>', self._bind_mousewheel)
        self.detail_canvas.bind('<Leave>', self._unbind_mousewheel)

        # Tab 2: Compare & Merge
        self._build_compare_tab()

        # ── Status Bar ──
        self.status = ttk.Label(self.root, text="Ready", style='Status.TLabel')

        # Show label info
        total_labels = sum(len(v) for v in self.field_labels.labels.values())
        total_descs = sum(len(v) for v in self.field_descs.descs.values())
        if total_labels > 100:
            desc_info = f", {total_descs} Beschreibungen" if total_descs > 0 else ""
            self.status.configure(text=f"Ready — {total_labels} SDK-Feldnamen{desc_info} geladen")
        elif total_labels > 0:
            self.status.configure(text=f"Ready — {total_labels} Labels (tw1_sdk_labels.json neben Editor legen für alle SDK-Namen)")
        self.status.pack(fill='x', side='bottom')

    def _bind_keys(self):
        self.root.bind('<Control-o>', lambda e: self._open_par())
        self.root.bind('<Control-s>', lambda e: self._save())
        self.root.bind('<Control-Shift-S>', lambda e: self._save_as())
        self.root.bind('<Return>', lambda e: self._search_next()
                       if self.search_entry == self.root.focus_get() else None)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _bind_mousewheel(self, event):
        self.detail_canvas.bind_all('<MouseWheel>',
                                     lambda e: self.detail_canvas.yview_scroll(
                                         int(-1 * (e.delta / 120)), "units"))
        self.detail_canvas.bind_all('<Button-4>',
                                     lambda e: self.detail_canvas.yview_scroll(-3, "units"))
        self.detail_canvas.bind_all('<Button-5>',
                                     lambda e: self.detail_canvas.yview_scroll(3, "units"))

    def _unbind_mousewheel(self, event):
        self.detail_canvas.unbind_all('<MouseWheel>')
        self.detail_canvas.unbind_all('<Button-4>')
        self.detail_canvas.unbind_all('<Button-5>')

    def _on_detail_configure(self, event):
        self.detail_canvas.configure(scrollregion=self.detail_canvas.bbox('all'))

    def _on_canvas_configure(self, event):
        self.detail_canvas.itemconfig('inner', width=event.width)

    # ── File Operations ──

    def _open_par(self):
        path = filedialog.askopenfilename(
            title="Open PAR File",
            filetypes=[("PAR Files", "*.par"), ("All Files", "*.*")]
        )
        if not path:
            return
        self._load_par(path)

    def _load_par(self, path):
        try:
            with open(path, 'rb') as f:
                raw_data = f.read()

            par_data, wrapper, was_compressed = decompress_par_file(raw_data)
            self.par = read_par(par_data)
            self.par.filepath = path
            self.par.wrapper_header = wrapper
            self.par.was_compressed = was_compressed
            self.filepath = path
            self.modified = False
            self._populate_tree()
            self._update_title()

            total_entries = sum(len(pl.entries) for pl in self.par.lists)
            comp_str = "  [zlib]" if was_compressed else ""
            self.file_label.configure(
                text=f"{Path(path).name}{comp_str}  |  {len(self.par.lists)} lists, "
                     f"{total_entries} entries  |  "
                     f"v0x{self.par.version:X}")
            self._set_status(f"Opened {Path(path).name} — "
                            f"{len(self.par.lists)} lists, {total_entries} entries"
                            f"{' (zlib compressed)' if was_compressed else ''}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open:\n{e}")

    def _open_json(self):
        path = filedialog.askopenfilename(
            title="Open JSON File",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        if not path:
            return
        try:
            self.par = import_json(path)
            self.filepath = path.replace('.json', '.par')
            self.par.filepath = self.filepath
            self.modified = True
            self._populate_tree()
            self._update_title()

            total_entries = sum(len(pl.entries) for pl in self.par.lists)
            self.file_label.configure(
                text=f"Imported from JSON  |  {len(self.par.lists)} lists, "
                     f"{total_entries} entries")
            self._set_status(f"Imported from {Path(path).name}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to import:\n{e}")

    def _save(self):
        if not self.par:
            return
        if not self.filepath or self.filepath.endswith('.json'):
            self._save_as()
            return
        self._do_save(self.filepath)

    def _save_as(self):
        if not self.par:
            return
        path = filedialog.asksaveasfilename(
            title="Save PAR File",
            defaultextension=".par",
            filetypes=[("PAR Files", "*.par"), ("All Files", "*.*")],
            initialfile=Path(self.filepath).name if self.filepath else "TwoWorlds.par"
        )
        if not path:
            return
        self._do_save(path)

    def _do_save(self, path):
        try:
            self._apply_current_edits()
            par_data = write_par(self.par)

            # Re-compress if the original was compressed
            if self.par.was_compressed:
                out_data = compress_par_file(par_data, self.par.wrapper_header)
            else:
                out_data = par_data

            with open(path, 'wb') as f:
                f.write(out_data)
            self.filepath = path
            self.par.filepath = path
            self.modified = False
            self._update_title()
            comp_str = " (zlib)" if self.par.was_compressed else ""
            self._set_status(f"Saved {Path(path).name} ({len(out_data)} bytes{comp_str})")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    def _export_json(self):
        if not self.par:
            messagebox.showinfo("No Data", "Open a PAR file first.")
            return
        default_name = Path(self.filepath).stem + ".json" if self.filepath else "TwoWorlds.json"
        path = filedialog.asksaveasfilename(
            title="Export as JSON",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            initialfile=default_name
        )
        if not path:
            return
        try:
            self._apply_current_edits()
            export_json(self.par, path, self.field_labels)
            self._set_status(f"Exported to {Path(path).name}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export:\n{e}")

    def _on_close(self):
        if self.modified:
            r = messagebox.askyesnocancel("Unsaved Changes",
                                           "Save changes before closing?")
            if r is None:
                return
            if r:
                self._save()
        self.root.destroy()

    def _update_title(self):
        name = Path(self.filepath).name if self.filepath else "Untitled"
        mod = " *" if self.modified else ""
        self.root.title(f"TW1 PAR Editor v1.3 — {name}{mod}")

    def _set_status(self, msg):
        self.status.configure(text=msg)

    # ── Tree Population ──

    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._clear_detail()

        if not self.par:
            return

        for li, pl in enumerate(self.par.lists):
            # List node — show first entry name as category hint
            entry_count = len(pl.entries)
            if entry_count == 0:
                list_label = f"List {li}  (empty)"
            elif entry_count == 1:
                list_label = f"List {li}  ({pl.entries[0].name})"
            else:
                first = pl.entries[0].name
                list_label = f"List {li}  ({first}...)  [{entry_count}]"

            list_id = self.tree.insert('', 'end', iid=f"L{li}",
                                        text=f"  {list_label}",
                                        open=False)

            # Entry nodes
            for ei, entry in enumerate(pl.entries):
                field_count = len(entry.fields)
                # Find best preview: prefer first string field, else first value
                preview = ""
                for f in entry.fields[:5]:
                    if f.dtype == TYPE_STRING and f.value:
                        s = str(f.value)
                        if len(s) > 35:
                            s = s[-32:] 
                            preview = f"...{s}"
                        else:
                            preview = s
                        break
                if not preview and field_count > 0:
                    preview = self._field_preview(entry.fields[0])

                entry_text = f"  {entry.name}"
                if preview:
                    entry_text = f"  {entry.name}  \u2502 {preview}"

                self.tree.insert(list_id, 'end',
                                  iid=f"L{li}E{ei}",
                                  text=entry_text)

    def _field_preview(self, field):
        """Short preview string for a field value."""
        if field.dtype == TYPE_STRING:
            s = str(field.value)
            if len(s) > 30:
                return f'"{s[:27]}..."'
            return f'"{s}"'
        elif field.dtype == TYPE_FLOAT32:
            return f"{field.value:.4f}"
        elif field.dtype in (TYPE_ARRAY_INT32, TYPE_ARRAY_FLOAT,
                             TYPE_ARRAY_UINT32, TYPE_ARRAY_STR):
            arr = field.value if field.value else []
            return f"[{len(arr)} items]"
        else:
            return str(field.value)

    # ── Tree Selection → Detail ──

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return

        item_id = sel[0]

        # Parse item ID
        if item_id.startswith('L') and 'E' in item_id:
            # Entry node: L{li}E{ei}
            parts = item_id[1:].split('E')
            li = int(parts[0])
            ei = int(parts[1])
            self._apply_current_edits()
            self._show_entry(li, ei)
        elif item_id.startswith('L'):
            # List node
            li = int(item_id[1:])
            self._apply_current_edits()
            self._show_list_info(li)

    def _show_list_info(self, li):
        """Show info about a list (no editable fields)."""
        self._clear_detail()

        if not self.par or li >= len(self.par.lists):
            return

        pl = self.par.lists[li]
        self.detail_header.configure(text=f"List {li}")
        self.detail_info.configure(
            text=f"{len(pl.entries)} entries  |  "
                 f"unknown1=0x{pl.unknown1:X}  unknown2=0x{pl.unknown2:X}")

        self.current_entry = None
        self.current_li = li
        self.current_ei = -1
        self.edit_widgets = []

    def _show_entry(self, li, ei):
        """Show entry details in the right panel with editable fields."""
        self._clear_detail()

        if not self.par or li >= len(self.par.lists):
            return
        pl = self.par.lists[li]
        if ei >= len(pl.entries):
            return

        entry = pl.entries[ei]
        self.current_entry = entry
        self.current_li = li
        self.current_ei = ei
        self.edit_widgets = []

        field_count = len(entry.fields)
        self.detail_header.configure(text=entry.name)
        self.detail_info.configure(
            text=f"List {li}, Entry {ei}  |  "
                 f"{field_count} fields  |  "
                 f"byte=0x{entry.unknown_byte & 0xFF:02X}  "
                 f"u16a={entry.unknown_u16a}  u16b={entry.unknown_u16b}")

        parent = self.detail_inner

        for fi, field in enumerate(entry.fields):
            row = tk.Frame(parent, bg=self.BG2)
            row.pack(fill='x', padx=8, pady=2)

            # Field index, label, and type
            type_name = TYPE_NAMES.get(field.dtype, f"?{field.dtype}")
            label_name = self.field_labels.get(field_count, fi)

            header_frame = tk.Frame(row, bg=self.BG2)
            header_frame.pack(fill='x')

            idx_label = tk.Label(header_frame, text=f"[{fi}]",
                                  bg=self.BG2, fg='#555555',
                                  font=('Consolas', 9), width=5, anchor='e')
            idx_label.pack(side='left')

            # Show label if available
            if label_name:
                name_label = tk.Label(header_frame, text=label_name,
                                       bg=self.BG2, fg='#4fc1e9',
                                       font=('Consolas', 10, 'bold'),
                                       anchor='w')
                name_label.pack(side='left', padx=(4, 4))
                # Right-click to rename
                name_label.bind('<Button-3>',
                    lambda e, fc=field_count, fidx=fi: self._label_context(e, fc, fidx))
                # Tooltip with German description
                tip_text = self.field_descs.get(field_count, fi)
                if tip_text:
                    ToolTip(name_label, f"{label_name}\n{tip_text}")
            else:
                # Clickable placeholder to add label
                name_label = tk.Label(header_frame, text="···",
                                       bg=self.BG2, fg='#444444',
                                       font=('Consolas', 9),
                                       cursor='hand2', anchor='w')
                name_label.pack(side='left', padx=(4, 4))
                name_label.bind('<Button-1>',
                    lambda e, fc=field_count, fidx=fi: self._add_label(fc, fidx))
                name_label.bind('<Button-3>',
                    lambda e, fc=field_count, fidx=fi: self._label_context(e, fc, fidx))

            type_label = tk.Label(header_frame, text=type_name,
                                   bg=self.BG2, fg=self.PURPLE,
                                   font=('Consolas', 10), width=10, anchor='w')
            type_label.pack(side='left', padx=(0, 8))

            # Value widget
            if field.dtype in (TYPE_INT32, TYPE_UINT32):
                var = tk.StringVar(value=str(field.value))
                w = tk.Entry(header_frame, textvariable=var, bg=self.BG4,
                             fg=self.GREEN, font=('Consolas', 10),
                             insertbackground=self.FG, relief='flat',
                             highlightthickness=1,
                             highlightcolor=self.ACCENT,
                             highlightbackground=self.BG3)
                w.pack(side='left', fill='x', expand=True, ipady=2)
                self.edit_widgets.append((fi, field.dtype, var))

            elif field.dtype == TYPE_FLOAT32:
                var = tk.StringVar(value=f"{field.value:.6f}")
                w = tk.Entry(header_frame, textvariable=var, bg=self.BG4,
                             fg=self.YELLOW, font=('Consolas', 10),
                             insertbackground=self.FG, relief='flat',
                             highlightthickness=1,
                             highlightcolor=self.ACCENT,
                             highlightbackground=self.BG3)
                w.pack(side='left', fill='x', expand=True, ipady=2)
                self.edit_widgets.append((fi, field.dtype, var))

            elif field.dtype == TYPE_STRING:
                var = tk.StringVar(value=str(field.value))
                w = tk.Entry(header_frame, textvariable=var, bg=self.BG4,
                             fg=self.ORANGE, font=('Consolas', 10),
                             insertbackground=self.FG, relief='flat',
                             highlightthickness=1,
                             highlightcolor=self.ACCENT,
                             highlightbackground=self.BG3)
                w.pack(side='left', fill='x', expand=True, ipady=2)
                self.edit_widgets.append((fi, field.dtype, var))

            elif field.dtype in (TYPE_ARRAY_INT32, TYPE_ARRAY_FLOAT,
                                  TYPE_ARRAY_UINT32, TYPE_ARRAY_STR):
                arr = field.value if field.value else []
                arr_label = tk.Label(
                    header_frame,
                    text=f"[{len(arr)} items]",
                    bg=self.BG2, fg=self.BLUE,
                    font=('Consolas', 10))
                arr_label.pack(side='left', padx=(0, 8))

                # Show array contents below
                if arr:
                    arr_frame = tk.Frame(row, bg=self.BG2)
                    arr_frame.pack(fill='x', padx=(90, 0))

                    arr_text = tk.Text(arr_frame, bg=self.BG4, fg=self.FG,
                                        font=('Consolas', 9), relief='flat',
                                        height=min(len(arr), 8),
                                        insertbackground=self.FG,
                                        highlightthickness=1,
                                        highlightcolor=self.ACCENT,
                                        highlightbackground=self.BG3,
                                        wrap='none')
                    for ai, av in enumerate(arr):
                        if field.dtype == TYPE_ARRAY_FLOAT:
                            line = f"{av:.6f}"
                        else:
                            line = str(av)
                        arr_text.insert('end', line + ('\n' if ai < len(arr)-1 else ''))
                    arr_text.pack(fill='x', pady=1)
                    self.edit_widgets.append((fi, field.dtype, arr_text))

            # Separator line
            sep = tk.Frame(parent, bg=self.BG3, height=1)
            sep.pack(fill='x', padx=4, pady=1)

    def _label_context(self, event, field_count, field_idx):
        """Show right-click context menu for field labels."""
        menu = tk.Menu(self.root, tearoff=0, bg=self.BG3, fg=self.FG,
                       activebackground=self.ACCENT, activeforeground='#fff',
                       font=('Segoe UI', 10))
        current = self.field_labels.get(field_count, field_idx)
        if current:
            menu.add_command(
                label=f"Rename '{current}'...",
                command=lambda: self._rename_label(field_count, field_idx, current))
            menu.add_command(
                label="Remove label",
                command=lambda: self._remove_label(field_count, field_idx))
        else:
            menu.add_command(
                label="Set label...",
                command=lambda: self._add_label(field_count, field_idx))
        menu.tk_popup(event.x_root, event.y_root)

    def _add_label(self, field_count, field_idx):
        """Add a new label for a field."""
        name = simpledialog.askstring(
            "Set Field Label",
            f"Label for field [{field_idx}] in {field_count}-field entries:",
            parent=self.root)
        if name and name.strip():
            self.field_labels.set(field_count, field_idx, name.strip())
            self._set_status(f"Label [{field_idx}] = '{name.strip()}' "
                            f"(for all {field_count}-field entries)")
            # Refresh display
            if self.current_entry:
                self._show_entry(self.current_li, self.current_ei)

    def _rename_label(self, field_count, field_idx, current):
        """Rename an existing label."""
        name = simpledialog.askstring(
            "Rename Field Label",
            f"Rename field [{field_idx}]:",
            initialvalue=current,
            parent=self.root)
        if name and name.strip():
            self.field_labels.set(field_count, field_idx, name.strip())
            self._set_status(f"Renamed [{field_idx}] → '{name.strip()}'")
            if self.current_entry:
                self._show_entry(self.current_li, self.current_ei)

    def _remove_label(self, field_count, field_idx):
        """Remove a label."""
        self.field_labels.remove(field_count, field_idx)
        self._set_status(f"Removed label for [{field_idx}]")
        if self.current_entry:
            self._show_entry(self.current_li, self.current_ei)

    # ── Tree Context Menu (Right-Click) ──

    def _tree_context_menu(self, event):
        """Show right-click context menu on tree items."""
        item_id = self.tree.identify_row(event.y)
        if not item_id or not self.par:
            return

        # Select the item under cursor
        self.tree.selection_set(item_id)
        self.tree.focus(item_id)

        menu = tk.Menu(self.root, tearoff=0, bg=self.BG3, fg=self.FG,
                       activebackground=self.ACCENT, activeforeground='#fff',
                       font=('Segoe UI', 10))

        if item_id.startswith('L') and 'E' in item_id:
            # Entry node: L{li}E{ei}
            parts = item_id[1:].split('E')
            li, ei = int(parts[0]), int(parts[1])
            entry = self.par.lists[li].entries[ei]

            menu.add_command(
                label=f"\u2398 Duplicate '{entry.name}'...",
                command=lambda: self._duplicate_entry(li, ei))
            menu.add_command(
                label=f"\u270E Rename '{entry.name}'...",
                command=lambda: self._rename_entry(li, ei))
            menu.add_separator()
            menu.add_command(
                label=f"\u2716 Delete '{entry.name}'",
                command=lambda: self._delete_entry(li, ei))

        elif item_id.startswith('L'):
            # List node
            li = int(item_id[1:])
            pl = self.par.lists[li]
            menu.add_command(
                label=f"Add New Entry to List {li}...",
                command=lambda: self._add_entry_to_list(li))
            if pl.entries:
                menu.add_command(
                    label=f"Duplicate Last Entry...",
                    command=lambda: self._duplicate_entry(li, len(pl.entries) - 1))

        menu.tk_popup(event.x_root, event.y_root)

    def _duplicate_entry(self, li, ei):
        """Deep-copy an entry, ask for new name, insert after original."""
        if not self.par or li >= len(self.par.lists):
            return
        pl = self.par.lists[li]
        if ei >= len(pl.entries):
            return

        src = pl.entries[ei]

        # Suggest a name: try incrementing trailing number
        suggested = self._suggest_next_name(src.name)

        new_name = simpledialog.askstring(
            "Duplicate Entry",
            f"Name for the copy of '{src.name}':",
            initialvalue=suggested,
            parent=self.root)
        if not new_name or not new_name.strip():
            return
        new_name = new_name.strip()

        # Check for duplicate names
        all_names = set()
        for plist in self.par.lists:
            for e in plist.entries:
                all_names.add(e.name)
        if new_name in all_names:
            if not messagebox.askyesno(
                "Name exists",
                f"'{new_name}' already exists.\nDuplicate anyway?"):
                return

        # Deep copy entry
        new_entry = ParEntry()
        new_entry.name = new_name
        new_entry.unknown_byte = src.unknown_byte
        new_entry.unknown_u16a = src.unknown_u16a
        new_entry.unknown_u16b = src.unknown_u16b
        for f in src.fields:
            nf = ParField(f.dtype)
            if isinstance(f.value, list):
                nf.value = copy.deepcopy(f.value)
            else:
                nf.value = f.value
            new_entry.fields.append(nf)

        # Update string fields that contain the old name (e.g. mesh path)
        old_lower = src.name.lower()
        new_lower = new_name.lower()
        for nf in new_entry.fields:
            if nf.dtype == TYPE_STRING and isinstance(nf.value, str):
                if old_lower in nf.value.lower():
                    # Case-preserving replace
                    idx = nf.value.lower().find(old_lower)
                    nf.value = nf.value[:idx] + new_name + nf.value[idx + len(old_lower):]

        # Insert after original
        pl.entries.insert(ei + 1, new_entry)

        self.modified = True
        self._update_title()
        self._populate_tree()

        # Select the new entry
        new_item_id = f"L{li}E{ei + 1}"
        parent_id = f"L{li}"
        self.tree.item(parent_id, open=True)
        self.tree.selection_set(new_item_id)
        self.tree.see(new_item_id)
        self.tree.focus(new_item_id)

        self._set_status(f"Duplicated '{src.name}' → '{new_name}'")

    def _rename_entry(self, li, ei):
        """Rename an entry."""
        if not self.par or li >= len(self.par.lists):
            return
        entry = self.par.lists[li].entries[ei]
        old_name = entry.name

        new_name = simpledialog.askstring(
            "Rename Entry",
            f"New name for '{old_name}':",
            initialvalue=old_name,
            parent=self.root)
        if not new_name or not new_name.strip() or new_name.strip() == old_name:
            return
        new_name = new_name.strip()

        entry.name = new_name

        # Optionally update string fields referencing old name
        old_lower = old_name.lower()
        updated_fields = 0
        for f in entry.fields:
            if f.dtype == TYPE_STRING and isinstance(f.value, str):
                if old_lower in f.value.lower():
                    idx = f.value.lower().find(old_lower)
                    f.value = f.value[:idx] + new_name + f.value[idx + len(old_lower):]
                    updated_fields += 1

        self.modified = True
        self._update_title()
        self._populate_tree()

        # Reselect
        item_id = f"L{li}E{ei}"
        parent_id = f"L{li}"
        self.tree.item(parent_id, open=True)
        self.tree.selection_set(item_id)
        self.tree.see(item_id)

        extra = f" (+{updated_fields} fields)" if updated_fields else ""
        self._set_status(f"Renamed '{old_name}' → '{new_name}'{extra}")

    def _delete_entry(self, li, ei):
        """Delete an entry after confirmation."""
        if not self.par or li >= len(self.par.lists):
            return
        pl = self.par.lists[li]
        if ei >= len(pl.entries):
            return

        name = pl.entries[ei].name
        if not messagebox.askyesno(
            "Delete Entry",
            f"Delete '{name}' from List {li}?\n\nThis cannot be undone."):
            return

        pl.entries.pop(ei)
        self.modified = True
        self._update_title()
        self._clear_detail()
        self._populate_tree()
        self._set_status(f"Deleted '{name}' from List {li}")

    def _add_entry_to_list(self, li):
        """Add a new empty entry to a list. Copies field structure from existing entries."""
        if not self.par or li >= len(self.par.lists):
            return
        pl = self.par.lists[li]

        new_name = simpledialog.askstring(
            "New Entry",
            f"Name for new entry in List {li}:",
            parent=self.root)
        if not new_name or not new_name.strip():
            return
        new_name = new_name.strip()

        new_entry = ParEntry()
        new_entry.name = new_name

        # Copy field structure from first entry in same list (same types, zero/empty values)
        if pl.entries:
            template = pl.entries[0]
            new_entry.unknown_byte = template.unknown_byte
            new_entry.unknown_u16a = template.unknown_u16a
            new_entry.unknown_u16b = template.unknown_u16b
            for f in template.fields:
                nf = ParField(f.dtype)
                if f.dtype == TYPE_INT32:
                    nf.value = 0
                elif f.dtype == TYPE_FLOAT32:
                    nf.value = 0.0
                elif f.dtype == TYPE_UINT32:
                    nf.value = 0
                elif f.dtype == TYPE_STRING:
                    nf.value = ""
                elif f.dtype in (TYPE_ARRAY_INT32, TYPE_ARRAY_FLOAT,
                                 TYPE_ARRAY_UINT32, TYPE_ARRAY_STR):
                    nf.value = []
                new_entry.fields.append(nf)

        pl.entries.append(new_entry)

        self.modified = True
        self._update_title()
        self._populate_tree()

        new_ei = len(pl.entries) - 1
        item_id = f"L{li}E{new_ei}"
        parent_id = f"L{li}"
        self.tree.item(parent_id, open=True)
        self.tree.selection_set(item_id)
        self.tree.see(item_id)

        self._set_status(f"Added '{new_name}' to List {li}")

    def _suggest_next_name(self, name):
        """Suggest next name by incrementing trailing number."""
        import re
        m = re.match(r'^(.*?)(\d+)$', name)
        if m:
            prefix = m.group(1)
            num = int(m.group(2))
            width = len(m.group(2))
            return f"{prefix}{num + 1:0{width}d}"
        return name + "_COPY"

    def _clear_detail(self):
        """Clear the detail panel."""
        for w in self.detail_inner.winfo_children():
            w.destroy()
        self.detail_header.configure(text="Select an entry")
        self.detail_info.configure(text="")
        self.edit_widgets = []
        self.current_entry = None

    def _apply_current_edits(self):
        """Apply edits from the detail panel back to the data model."""
        if not self.current_entry or not self.edit_widgets:
            return

        entry = self.current_entry
        changed = False

        for fi, dtype, widget in self.edit_widgets:
            if fi >= len(entry.fields):
                continue
            field = entry.fields[fi]

            try:
                if dtype in (TYPE_INT32, TYPE_UINT32):
                    new_val = int(widget.get())
                    if new_val != field.value:
                        field.value = new_val
                        changed = True

                elif dtype == TYPE_FLOAT32:
                    new_val = float(widget.get())
                    if new_val != field.value:
                        field.value = new_val
                        changed = True

                elif dtype == TYPE_STRING:
                    new_val = widget.get()
                    if new_val != field.value:
                        field.value = new_val
                        changed = True

                elif dtype in (TYPE_ARRAY_INT32, TYPE_ARRAY_FLOAT,
                               TYPE_ARRAY_UINT32, TYPE_ARRAY_STR):
                    # widget is a Text widget
                    text = widget.get('1.0', 'end').strip()
                    if text:
                        lines = [l.strip() for l in text.split('\n')
                                 if l.strip()]
                        if dtype == TYPE_ARRAY_INT32:
                            new_val = [int(l) for l in lines]
                        elif dtype == TYPE_ARRAY_FLOAT:
                            new_val = [float(l) for l in lines]
                        elif dtype == TYPE_ARRAY_UINT32:
                            new_val = [int(l) for l in lines]
                        elif dtype == TYPE_ARRAY_STR:
                            new_val = lines
                        else:
                            new_val = field.value
                    else:
                        new_val = []

                    if new_val != field.value:
                        field.value = new_val
                        changed = True

            except (ValueError, TypeError):
                pass   # Keep old value on invalid input

        if changed:
            self.modified = True
            self._update_title()

    # ── Search ──

    def _search_next(self):
        query = self.search_var.get().strip().lower()
        if not query or not self.par:
            self.search_label.configure(text="")
            return

        # Build results list on first search or query change
        if (not hasattr(self, '_last_query') or
                self._last_query != query):
            self._last_query = query
            self.search_results = []
            self.search_idx = 0

            for li, pl in enumerate(self.par.lists):
                for ei, entry in enumerate(pl.entries):
                    if query in entry.name.lower():
                        self.search_results.append((li, ei))
                    else:
                        # Search in string field values too
                        for field in entry.fields:
                            if field.dtype == TYPE_STRING:
                                if query in str(field.value).lower():
                                    self.search_results.append((li, ei))
                                    break

        if not self.search_results:
            self.search_label.configure(text="No results")
            return

        # Cycle through results
        if self.search_idx >= len(self.search_results):
            self.search_idx = 0

        li, ei = self.search_results[self.search_idx]
        self.search_idx += 1

        self.search_label.configure(
            text=f"{self.search_idx}/{len(self.search_results)}")

        # Select in tree
        item_id = f"L{li}E{ei}"
        parent_id = f"L{li}"

        self.tree.item(parent_id, open=True)
        self.tree.selection_set(item_id)
        self.tree.see(item_id)
        self.tree.focus(item_id)

    # ══════════════════════════════════════════════════════════════════════
    # COMPARE & MERGE TAB
    # ══════════════════════════════════════════════════════════════════════

    def _load_cmp_config(self):
        """Load saved original PAR path from config."""
        try:
            with open(self._cmp_config_path, 'r') as f:
                cfg = json.load(f)
            return cfg.get('original_par_path', '')
        except:
            return ''

    def _save_cmp_config(self):
        """Save original PAR path to config."""
        try:
            with open(self._cmp_config_path, 'w') as f:
                json.dump({'original_par_path': self._cmp_original_path}, f)
        except:
            pass

    def _build_compare_tab(self):
        """Build the Compare & Merge tab UI."""
        cmp_tab = ttk.Frame(self.notebook)
        self.notebook.add(cmp_tab, text="  Compare & Merge  ")

        # ── Top: File loaders ──
        loader_frame = tk.Frame(cmp_tab, bg=self.BG3, padx=8, pady=8)
        loader_frame.pack(fill='x')

        # Source
        sf = tk.Frame(loader_frame, bg=self.BG3)
        sf.pack(fill='x', pady=(0, 4))
        tk.Label(sf, text="Source PAR:", bg=self.BG3, fg=self.GREEN,
                 font=('Segoe UI', 10, 'bold'), width=14, anchor='w').pack(side='left')
        ttk.Button(sf, text="Load...", command=self._cmp_load_source,
                   style='Small.TButton').pack(side='left', padx=(0, 8))
        self.cmp_source_label = tk.Label(sf, text="(none)", bg=self.BG3,
                                          fg=self.FG, font=('Consolas', 9), anchor='w')
        self.cmp_source_label.pack(side='left', fill='x', expand=True)

        # Input
        inf = tk.Frame(loader_frame, bg=self.BG3)
        inf.pack(fill='x', pady=(0, 4))
        tk.Label(inf, text="Input PAR:", bg=self.BG3, fg=self.YELLOW,
                 font=('Segoe UI', 10, 'bold'), width=14, anchor='w').pack(side='left')
        ttk.Button(inf, text="Load...", command=self._cmp_load_input,
                   style='Small.TButton').pack(side='left', padx=(0, 8))
        self.cmp_input_label = tk.Label(inf, text="(none)", bg=self.BG3,
                                         fg=self.FG, font=('Consolas', 9), anchor='w')
        self.cmp_input_label.pack(side='left', fill='x', expand=True)

        # Original (optional)
        of = tk.Frame(loader_frame, bg=self.BG3)
        of.pack(fill='x')
        tk.Label(of, text="Original PAR:", bg=self.BG3, fg="#888",
                 font=('Segoe UI', 10), width=14, anchor='w').pack(side='left')
        ttk.Button(of, text="Load...", command=self._cmp_set_original,
                   style='Small.TButton').pack(side='left', padx=(0, 4))
        ttk.Button(of, text="Clear", command=self._cmp_clear_original,
                   style='Small.TButton').pack(side='left', padx=(0, 8))
        self.cmp_original_label = tk.Label(of, text=self._cmp_original_path or "(optional — unmodified TwoWorlds.par)",
                                            bg=self.BG3, fg="#888",
                                            font=('Consolas', 9), anchor='w')
        self.cmp_original_label.pack(side='left', fill='x', expand=True)

        # ── Compare button + filter bar ──
        action_frame = tk.Frame(cmp_tab, bg=self.BG, padx=8, pady=6)
        action_frame.pack(fill='x')

        ttk.Button(action_frame, text="\u25B6 Compare",
                   command=self._cmp_run_compare,
                   style='Accent.TButton').pack(side='left', padx=(0, 16))

        # Filter toggles
        self.cmp_show_changed = tk.BooleanVar(value=True)
        self.cmp_show_input_only = tk.BooleanVar(value=True)
        self.cmp_show_source_only = tk.BooleanVar(value=True)

        self.cmp_filter_changed = tk.Checkbutton(
            action_frame, text="\u25CF Changed (0)", bg=self.BG, fg=self.YELLOW,
            selectcolor=self.BG2, activebackground=self.BG, activeforeground=self.YELLOW,
            variable=self.cmp_show_changed, command=self._cmp_apply_filter,
            font=('Segoe UI', 9, 'bold'))
        self.cmp_filter_changed.pack(side='left', padx=(0, 12))

        self.cmp_filter_input = tk.Checkbutton(
            action_frame, text="\u25CF Input only (0)", bg=self.BG, fg=self.GREEN,
            selectcolor=self.BG2, activebackground=self.BG, activeforeground=self.GREEN,
            variable=self.cmp_show_input_only, command=self._cmp_apply_filter,
            font=('Segoe UI', 9, 'bold'))
        self.cmp_filter_input.pack(side='left', padx=(0, 12))

        self.cmp_filter_source = tk.Checkbutton(
            action_frame, text="\u25CF Source only (0)", bg=self.BG, fg=self.BLUE,
            selectcolor=self.BG2, activebackground=self.BG, activeforeground=self.BLUE,
            variable=self.cmp_show_source_only, command=self._cmp_apply_filter,
            font=('Segoe UI', 9, 'bold'))
        self.cmp_filter_source.pack(side='left', padx=(0, 12))

        # Select all / none
        ttk.Button(action_frame, text="Select All",
                   command=self._cmp_select_all,
                   style='Small.TButton').pack(side='right', padx=(4, 0))
        ttk.Button(action_frame, text="Deselect All",
                   command=self._cmp_deselect_all,
                   style='Small.TButton').pack(side='right', padx=(4, 0))

        # ── Diff Treeview ──
        tree_frame = ttk.Frame(cmp_tab)
        tree_frame.pack(fill='both', expand=True, padx=4)

        cols = ('path', 'original', 'source', 'input', 'check')
        self.cmp_tree = ttk.Treeview(tree_frame, columns=cols, show='headings',
                                      selectmode='browse')
        self.cmp_tree.heading('path', text='Path (List \u2192 Entry \u2192 Field)')
        self.cmp_tree.heading('original', text='Original')
        self.cmp_tree.heading('source', text='Source')
        self.cmp_tree.heading('input', text='Input')
        self.cmp_tree.heading('check', text='\u2610')

        self.cmp_tree.column('path', width=380, minwidth=200)
        self.cmp_tree.column('original', width=150, minwidth=80)
        self.cmp_tree.column('source', width=150, minwidth=80)
        self.cmp_tree.column('input', width=150, minwidth=80)
        self.cmp_tree.column('check', width=40, minwidth=40, anchor='center')

        cmp_scroll = ttk.Scrollbar(tree_frame, orient='vertical',
                                    command=self.cmp_tree.yview)
        self.cmp_tree.configure(yscrollcommand=cmp_scroll.set)
        self.cmp_tree.pack(side='left', fill='both', expand=True)
        cmp_scroll.pack(side='right', fill='y')

        # Click on check column to toggle
        self.cmp_tree.bind('<ButtonRelease-1>', self._cmp_on_tree_click)

        # Tag colors
        self.cmp_tree.tag_configure('changed', foreground=self.YELLOW)
        self.cmp_tree.tag_configure('input_only', foreground=self.GREEN)
        self.cmp_tree.tag_configure('source_only', foreground=self.BLUE)
        self.cmp_tree.tag_configure('checked', background='#2a3a2a')

        # ── Bottom: Merge actions ──
        merge_frame = tk.Frame(cmp_tab, bg=self.BG3, padx=8, pady=8)
        merge_frame.pack(fill='x', side='bottom')

        self.cmp_merge_info = tk.Label(merge_frame, text="Load Source and Input, then click Compare",
                                        bg=self.BG3, fg=self.FG, font=('Segoe UI', 9))
        self.cmp_merge_info.pack(side='left')

        ttk.Button(merge_frame, text="\u2913 Save Merged PAR...",
                   command=self._cmp_save,
                   style='Accent.TButton').pack(side='right', padx=(8, 0))
        ttk.Button(merge_frame, text="\u25B6 Merge Selected into Source",
                   command=self._cmp_merge,
                   style='Accent.TButton').pack(side='right')

    # ── Compare: File Loading ──

    def _cmp_load_par_file(self, title="Open PAR"):
        """Load and parse a PAR file, return ParFile or None."""
        path = filedialog.askopenfilename(
            title=title,
            filetypes=[("PAR Files", "*.par"), ("All Files", "*.*")])
        if not path:
            return None, ''
        try:
            with open(path, 'rb') as f:
                raw = f.read()
            par_data, wrapper, was_compressed = decompress_par_file(raw)
            par = read_par(par_data)
            par.filepath = path
            par.wrapper_header = wrapper
            par.was_compressed = was_compressed
            return par, path
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load PAR:\n{e}")
            return None, ''

    def _cmp_load_source(self):
        par, path = self._cmp_load_par_file("Open Source PAR")
        if par:
            self.cmp_source = par
            total = sum(len(pl.entries) for pl in par.lists)
            self.cmp_source_label.configure(
                text=f"{Path(path).name}  ({len(par.lists)} lists, {total} entries)")

    def _cmp_load_input(self):
        par, path = self._cmp_load_par_file("Open Input PAR")
        if par:
            self.cmp_input = par
            total = sum(len(pl.entries) for pl in par.lists)
            self.cmp_input_label.configure(
                text=f"{Path(path).name}  ({len(par.lists)} lists, {total} entries)")

    def _cmp_set_original(self):
        par, path = self._cmp_load_par_file("Set Original (unmodified) PAR")
        if par:
            self.cmp_original = par
            self._cmp_original_path = path
            self._save_cmp_config()
            self.cmp_original_label.configure(text=Path(path).name, fg=self.FG)

    def _cmp_clear_original(self):
        self.cmp_original = None
        self._cmp_original_path = ''
        self._save_cmp_config()
        self.cmp_original_label.configure(
            text="(optional — unmodified TwoWorlds.par)", fg="#888")

    def _cmp_load_original_from_config(self):
        """Auto-load original PAR from saved config path."""
        if self._cmp_original_path and os.path.isfile(self._cmp_original_path):
            try:
                with open(self._cmp_original_path, 'rb') as f:
                    raw = f.read()
                par_data, wrapper, was_compressed = decompress_par_file(raw)
                self.cmp_original = read_par(par_data)
                self.cmp_original.filepath = self._cmp_original_path
                self.cmp_original_label.configure(
                    text=Path(self._cmp_original_path).name, fg=self.FG)
            except:
                pass

    # ── Compare: Core Logic ──

    def _cmp_field_value_str(self, field):
        """Format a field value for display."""
        if field is None:
            return "—"
        v = field.value
        if isinstance(v, float):
            return f"{v:.4f}" if v != int(v) else f"{v:.1f}"
        if isinstance(v, list):
            if len(v) <= 4:
                return str(v)
            return f"[{len(v)} items]"
        return str(v)

    def _cmp_fields_equal(self, f1, f2):
        """Compare two ParFields for equality."""
        if f1.dtype != f2.dtype:
            return False
        if isinstance(f1.value, float) and isinstance(f2.value, float):
            return abs(f1.value - f2.value) < 1e-7
        return f1.value == f2.value

    def _cmp_run_compare(self):
        """Run the comparison between source and input."""
        if not self.cmp_source:
            messagebox.showwarning("Compare", "Load a Source PAR first.")
            return
        if not self.cmp_input:
            messagebox.showwarning("Compare", "Load an Input PAR first.")
            return

        # Auto-load original from config if not loaded yet
        if not self.cmp_original and self._cmp_original_path:
            self._cmp_load_original_from_config()

        self.cmp_diffs = []
        self.cmp_checks = {}

        src = self.cmp_source
        inp = self.cmp_input
        orig = self.cmp_original  # may be None

        # Match lists by index (PAR list structure is stable across mods)
        max_lists = max(len(src.lists), len(inp.lists))

        for li in range(max_lists):
            src_list = src.lists[li] if li < len(src.lists) else None
            inp_list = inp.lists[li] if li < len(inp.lists) else None
            orig_list = orig.lists[li] if (orig and li < len(orig.lists)) else None

            if src_list is None and inp_list is not None:
                # Entire list only in input
                for ei, entry in enumerate(inp_list.entries):
                    self.cmp_diffs.append({
                        'type': 'input_only',
                        'list_idx': li,
                        'entry_name': entry.name,
                        'field_idx': -1,
                        'field_label': '',
                        'source_val': '—',
                        'input_val': f'({len(entry.fields)} fields)',
                        'original_val': '—',
                        'inp_li': li, 'inp_ei': ei,
                        'src_li': -1, 'src_ei': -1,
                    })
                continue

            if inp_list is None and src_list is not None:
                # Entire list only in source
                for ei, entry in enumerate(src_list.entries):
                    self.cmp_diffs.append({
                        'type': 'source_only',
                        'list_idx': li,
                        'entry_name': entry.name,
                        'field_idx': -1,
                        'field_label': '',
                        'source_val': f'({len(entry.fields)} fields)',
                        'input_val': '—',
                        'original_val': '—',
                        'src_li': li, 'src_ei': ei,
                        'inp_li': -1, 'inp_ei': -1,
                    })
                continue

            # Both lists exist — match entries by name
            src_by_name = {}
            for ei, e in enumerate(src_list.entries):
                src_by_name[e.name] = (ei, e)

            inp_by_name = {}
            for ei, e in enumerate(inp_list.entries):
                inp_by_name[e.name] = (ei, e)

            orig_by_name = {}
            if orig_list:
                for ei, e in enumerate(orig_list.entries):
                    orig_by_name[e.name] = (ei, e)

            # Field count for SDK labels
            field_count = 0
            if src_list.entries:
                field_count = len(src_list.entries[0].fields)
            elif inp_list.entries:
                field_count = len(inp_list.entries[0].fields)

            # Entries in both — compare fields
            all_names = set(list(src_by_name.keys()) + list(inp_by_name.keys()))
            for name in sorted(all_names):
                in_src = name in src_by_name
                in_inp = name in inp_by_name

                if in_src and not in_inp:
                    sei, se = src_by_name[name]
                    self.cmp_diffs.append({
                        'type': 'source_only',
                        'list_idx': li,
                        'entry_name': name,
                        'field_idx': -1,
                        'field_label': '',
                        'source_val': f'({len(se.fields)} fields)',
                        'input_val': '—',
                        'original_val': '—',
                        'src_li': li, 'src_ei': sei,
                        'inp_li': -1, 'inp_ei': -1,
                    })
                    continue

                if in_inp and not in_src:
                    iei, ie = inp_by_name[name]
                    self.cmp_diffs.append({
                        'type': 'input_only',
                        'list_idx': li,
                        'entry_name': name,
                        'field_idx': -1,
                        'field_label': '',
                        'source_val': '—',
                        'input_val': f'({len(ie.fields)} fields)',
                        'original_val': '—',
                        'inp_li': li, 'inp_ei': iei,
                        'src_li': -1, 'src_ei': -1,
                    })
                    continue

                # Both exist — compare field by field
                sei, se = src_by_name[name]
                iei, ie = inp_by_name[name]
                _, oe = orig_by_name.get(name, (-1, None))

                max_fields = max(len(se.fields), len(ie.fields))
                for fi in range(max_fields):
                    sf = se.fields[fi] if fi < len(se.fields) else None
                    inf_f = ie.fields[fi] if fi < len(ie.fields) else None
                    of = None
                    if oe and fi < len(oe.fields):
                        of = oe.fields[fi]

                    # Skip if identical
                    if sf and inf_f and self._cmp_fields_equal(sf, inf_f):
                        continue

                    # Get field label
                    label = self.field_labels.get(field_count, fi) or ''

                    self.cmp_diffs.append({
                        'type': 'changed',
                        'list_idx': li,
                        'entry_name': name,
                        'field_idx': fi,
                        'field_label': label,
                        'source_val': self._cmp_field_value_str(sf),
                        'input_val': self._cmp_field_value_str(inf_f),
                        'original_val': self._cmp_field_value_str(of) if of else '—',
                        'src_li': li, 'src_ei': sei,
                        'inp_li': li, 'inp_ei': iei,
                    })

        # Initialize checkboxes (all unchecked)
        for i in range(len(self.cmp_diffs)):
            self.cmp_checks[i] = False

        # Update filter counts and populate tree
        self._cmp_update_counts()
        self._cmp_apply_filter()

        total = len(self.cmp_diffs)
        self.cmp_merge_info.configure(
            text=f"Found {total} differences. Select entries to merge, then click Merge.")
        self._set_status(f"Compare: {total} differences found")

    def _cmp_update_counts(self):
        """Update filter button labels with counts."""
        counts = {'changed': 0, 'input_only': 0, 'source_only': 0}
        for d in self.cmp_diffs:
            counts[d['type']] += 1
        self.cmp_filter_changed.configure(text=f"\u25CF Changed ({counts['changed']})")
        self.cmp_filter_input.configure(text=f"\u25CF Input only ({counts['input_only']})")
        self.cmp_filter_source.configure(text=f"\u25CF Source only ({counts['source_only']})")

    # ── Compare: Treeview Display ──

    def _cmp_apply_filter(self):
        """Populate the compare treeview based on active filters."""
        self.cmp_tree.delete(*self.cmp_tree.get_children())

        show = set()
        if self.cmp_show_changed.get():
            show.add('changed')
        if self.cmp_show_input_only.get():
            show.add('input_only')
        if self.cmp_show_source_only.get():
            show.add('source_only')

        for i, d in enumerate(self.cmp_diffs):
            if d['type'] not in show:
                continue

            # Build path string
            if d['field_idx'] >= 0:
                flabel = d['field_label'] or f"field_{d['field_idx']}"
                path = f"List[{d['list_idx']}] \u2192 {d['entry_name']} \u2192 [{d['field_idx']}] {flabel}"
            else:
                path = f"List[{d['list_idx']}] \u2192 {d['entry_name']}  (entire entry)"

            check_str = '\u2611' if self.cmp_checks.get(i, False) else '\u2610'

            tag = d['type']
            if self.cmp_checks.get(i, False):
                tag = (d['type'], 'checked')

            iid = f"D{i}"
            self.cmp_tree.insert('', 'end', iid=iid,
                                  values=(path, d['original_val'],
                                          d['source_val'], d['input_val'],
                                          check_str),
                                  tags=tag)

    def _cmp_on_tree_click(self, event):
        """Handle click on the check column to toggle checkbox."""
        region = self.cmp_tree.identify_region(event.x, event.y)
        col = self.cmp_tree.identify_column(event.x)
        item = self.cmp_tree.identify_row(event.y)

        if not item:
            return

        # col '#5' is the check column
        if col == '#5' or (region == 'cell' and col == '#5'):
            idx = int(item[1:])  # "D0" -> 0
            d = self.cmp_diffs[idx]

            # Don't allow checking source_only (nothing to merge)
            if d['type'] == 'source_only':
                return

            self.cmp_checks[idx] = not self.cmp_checks.get(idx, False)

            check_str = '\u2611' if self.cmp_checks[idx] else '\u2610'
            tag = d['type']
            if self.cmp_checks[idx]:
                tag = (d['type'], 'checked')
            self.cmp_tree.item(item, values=(
                self.cmp_tree.item(item)['values'][0],
                self.cmp_tree.item(item)['values'][1],
                self.cmp_tree.item(item)['values'][2],
                self.cmp_tree.item(item)['values'][3],
                check_str), tags=tag)

            # Update merge info
            selected = sum(1 for v in self.cmp_checks.values() if v)
            self.cmp_merge_info.configure(
                text=f"{selected} of {len(self.cmp_diffs)} selected for merge")

    def _cmp_select_all(self):
        """Select all visible (non-source-only) diffs."""
        for i, d in enumerate(self.cmp_diffs):
            if d['type'] != 'source_only':
                self.cmp_checks[i] = True
        self._cmp_apply_filter()
        selected = sum(1 for v in self.cmp_checks.values() if v)
        self.cmp_merge_info.configure(
            text=f"{selected} of {len(self.cmp_diffs)} selected for merge")

    def _cmp_deselect_all(self):
        """Deselect all diffs."""
        for i in self.cmp_checks:
            self.cmp_checks[i] = False
        self._cmp_apply_filter()
        self.cmp_merge_info.configure(
            text=f"0 of {len(self.cmp_diffs)} selected for merge")

    # ── Compare: Merge Logic ──

    def _cmp_merge(self):
        """Apply selected changes from input into source."""
        if not self.cmp_source or not self.cmp_input:
            messagebox.showwarning("Merge", "Load Source and Input first.")
            return

        selected = [(i, d) for i, d in enumerate(self.cmp_diffs)
                     if self.cmp_checks.get(i, False)]

        if not selected:
            messagebox.showinfo("Merge", "No entries selected. Click the checkboxes to select changes.")
            return

        # Confirm
        n_changes = sum(1 for _, d in selected if d['type'] == 'changed')
        n_new = sum(1 for _, d in selected if d['type'] == 'input_only')
        msg = f"Apply {len(selected)} changes to Source?\n"
        if n_changes:
            msg += f"  \u2022 {n_changes} field value(s) updated\n"
        if n_new:
            msg += f"  \u2022 {n_new} new entry/entries added\n"

        if not messagebox.askyesno("Confirm Merge", msg):
            return

        src = self.cmp_source
        inp = self.cmp_input

        # Apply changes
        added_count = 0
        changed_count = 0

        for _, d in selected:
            if d['type'] == 'changed':
                # Update field value in source
                sli, sei = d['src_li'], d['src_ei']
                ili, iei = d['inp_li'], d['inp_ei']
                fi = d['field_idx']

                if (sli >= 0 and sei >= 0 and sli < len(src.lists)
                        and sei < len(src.lists[sli].entries)):
                    src_entry = src.lists[sli].entries[sei]
                    if (ili >= 0 and iei >= 0 and ili < len(inp.lists)
                            and iei < len(inp.lists[ili].entries)):
                        inp_entry = inp.lists[ili].entries[iei]
                        if fi < len(inp_entry.fields):
                            # Ensure source has enough fields
                            while len(src_entry.fields) <= fi:
                                src_entry.fields.append(ParField(0, 0))
                            inp_f = inp_entry.fields[fi]
                            src_entry.fields[fi] = ParField(inp_f.dtype,
                                copy.deepcopy(inp_f.value) if isinstance(inp_f.value, list)
                                else inp_f.value)
                            changed_count += 1

            elif d['type'] == 'input_only':
                # Add entire entry from input to source
                ili, iei = d['inp_li'], d['inp_ei']
                if ili >= 0 and iei >= 0 and ili < len(inp.lists):
                    inp_entry = inp.lists[ili].entries[iei]

                    # Ensure source has enough lists
                    while len(src.lists) <= ili:
                        new_list = ParList()
                        src.lists.append(new_list)

                    # Deep copy entry
                    new_entry = ParEntry()
                    new_entry.name = inp_entry.name
                    new_entry.unknown_byte = inp_entry.unknown_byte
                    new_entry.unknown_u16a = inp_entry.unknown_u16a
                    new_entry.unknown_u16b = inp_entry.unknown_u16b
                    for f in inp_entry.fields:
                        nf = ParField(f.dtype,
                            copy.deepcopy(f.value) if isinstance(f.value, list)
                            else f.value)
                        new_entry.fields.append(nf)

                    # Check if name already exists
                    exists = any(e.name == new_entry.name
                                 for e in src.lists[ili].entries)
                    if not exists:
                        src.lists[ili].entries.append(new_entry)
                        added_count += 1

        self.cmp_merge_info.configure(
            text=f"Merged: {changed_count} fields updated, {added_count} entries added. Save to write to disk.")
        self._set_status(f"Merge complete — {changed_count} changed, {added_count} added")

    def _cmp_save(self):
        """Save the merged source PAR to file."""
        if not self.cmp_source:
            messagebox.showwarning("Save", "No Source PAR loaded.")
            return

        path = filedialog.asksaveasfilename(
            title="Save Merged PAR",
            defaultextension=".par",
            filetypes=[("PAR Files", "*.par"), ("All Files", "*.*")],
            initialfile="TwoWorlds_merged.par")
        if not path:
            return

        try:
            par_data = write_par(self.cmp_source)
            if self.cmp_source.was_compressed:
                output = compress_par_file(par_data, self.cmp_source.wrapper_header)
            else:
                output = par_data
            with open(path, 'wb') as f:
                f.write(output)

            total = sum(len(pl.entries) for pl in self.cmp_source.lists)
            self.cmp_merge_info.configure(
                text=f"Saved to {Path(path).name} ({len(self.cmp_source.lists)} lists, {total} entries)")
            self._set_status(f"Saved merged PAR to {Path(path).name}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    # ── Helpers ──

    @property
    def current_entry(self):
        return self._current_entry

    @current_entry.setter
    def current_entry(self, val):
        self._current_entry = val

    _current_entry = None
    current_li = -1
    current_ei = -1
    edit_widgets = []


# ═══════════════════════════════════════════════════════════════════════════════
# CLI MODE
# ═══════════════════════════════════════════════════════════════════════════════

def cli_info(path):
    """Print info about a PAR file."""
    with open(path, 'rb') as f:
        raw_data = f.read()

    par_data, wrapper, was_compressed = decompress_par_file(raw_data)
    par = read_par(par_data)
    total = sum(len(pl.entries) for pl in par.lists)
    print(f"PAR File: {path}")
    if was_compressed:
        print(f"Compressed: zlib ({len(raw_data)} → {len(par_data)} bytes)")
        if wrapper:
            print(f"Wrapper:  {wrapper!r}")
    print(f"Version:  0x{par.version:X}")
    print(f"Lists:    {len(par.lists)}")
    print(f"Entries:  {total}")
    print()

    for li, pl in enumerate(par.lists):
        print(f"  List {li}: {len(pl.entries)} entries "
              f"(unk1=0x{pl.unknown1:X}, unk2=0x{pl.unknown2:X})")
        for ei, entry in enumerate(pl.entries):
            fields_str = ", ".join(
                TYPE_NAMES.get(f.dtype, '?') for f in entry.fields)
            print(f"    [{ei}] {entry.name}  ({fields_str})")


def cli_export(par_path, json_path):
    """Export PAR to JSON."""
    with open(par_path, 'rb') as f:
        raw_data = f.read()
    par_data, wrapper, was_compressed = decompress_par_file(raw_data)
    par = read_par(par_data)
    export_json(par, json_path)
    total = sum(len(pl.entries) for pl in par.lists)
    print(f"Exported {len(par.lists)} lists, {total} entries to {json_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == '--info' and len(sys.argv) > 2:
            cli_info(sys.argv[2])
        elif cmd == '--export' and len(sys.argv) > 3:
            cli_export(sys.argv[2], sys.argv[3])
        elif cmd == '--help':
            print("TW1 PAR Editor v1.3")
            print()
            print("GUI:   python tw1_par_editor.py")
            print("Info:  python tw1_par_editor.py --info file.par")
            print("Export: python tw1_par_editor.py --export file.par output.json")
        else:
            # Try to open as file in GUI
            if HAS_TK:
                root = tk.Tk()
                app = ParEditorApp(root)
                if os.path.isfile(cmd):
                    app._load_par(cmd)
                root.mainloop()
            else:
                print("Usage: python tw1_par_editor.py [--info|--export] file.par")
    else:
        if not HAS_TK:
            print("Usage: python tw1_par_editor.py [--info|--export|--help] file.par")
            print("       or run without args for GUI (requires tkinter)")
            sys.exit(1)
        root = tk.Tk()
        app = ParEditorApp(root)
        root.mainloop()
