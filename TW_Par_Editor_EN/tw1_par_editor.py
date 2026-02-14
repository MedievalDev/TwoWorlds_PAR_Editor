#!/usr/bin/env python3
"""TW1 PAR Editor v1.1 — View, edit, and export Two Worlds 1 .par parameter files
   Now with SDK field labels from TwoWorlds.xls"""

import struct
import os
import sys
import json
import io
import zlib
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


def decompress_par_file(raw_data):
    """Decompress a PAR file from disk. Handles zlib-compressed wrapper format.
    Returns (par_data, wrapper_header) where wrapper_header is None if not compressed."""
    if raw_data[:2] == b'\x78\x9c' or raw_data[:2] == b'\x78\x01' or raw_data[:2] == b'\x78\xda':
        # zlib compressed — Two Worlds uses dual-stream format:
        #   Stream 1: small wrapper header (translateGameParams + GUID)
        #   Stream 2: actual PAR binary data
        dec1 = zlib.decompressobj()
        wrapper = dec1.decompress(raw_data)
        remaining = dec1.unused_data

        if remaining and (remaining[:1] == b'\x78'):
            dec2 = zlib.decompressobj()
            par_data = dec2.decompress(remaining)
            return par_data, wrapper, True
        else:
            # Single stream — the decompressed data IS the PAR
            return wrapper, None, True
    elif raw_data[:4] == PAR_MAGIC:
        return raw_data, None, False
    else:
        raise ValueError(f"Unknown file format (header: {raw_data[:4].hex()})")


def compress_par_file(par_data, wrapper_header=None):
    """Compress PAR data back to the on-disk format with zlib wrapper."""
    if wrapper_header is not None:
        stream1 = zlib.compress(wrapper_header, 6)
        stream2 = zlib.compress(par_data, 6)
        return stream1 + stream2
    else:
        return zlib.compress(par_data, 6)



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
        self.root.title("TW1 PAR Editor v1.1")
        self.root.geometry("1200x750")
        self.root.minsize(900, 550)

        self.par = None           # Current ParFile
        self.filepath = ""        # Current file path
        self.modified = False     # Unsaved changes flag
        self.search_results = []  # (list_idx, entry_idx) tuples
        self.search_idx = 0       # Current result index

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

        # ── Main Paned Window ──
        paned = tk.PanedWindow(self.root, orient='horizontal', bg=self.BG,
                                sashwidth=4, sashrelief='flat')
        paned.pack(fill='both', expand=True, padx=4, pady=(0, 4))

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

        # ── Status Bar ──
        self.status = ttk.Label(self.root, text="Ready", style='Status.TLabel')

        # Show label info
        total_labels = sum(len(v) for v in self.field_labels.labels.values())
        total_descs = sum(len(v) for v in self.field_descs.descs.values())
        if total_labels > 100:
            desc_info = f", {total_descs} descriptions" if total_descs > 0 else ""
            self.status.configure(text=f"Ready — {total_labels} SDK field labels{desc_info} loaded")
        elif total_labels > 0:
            self.status.configure(text=f"Ready — {total_labels} labels (place tw1_sdk_labels.json next to editor for full SDK names)")
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
        self.root.title(f"TW1 PAR Editor v1.1 — {name}{mod}")

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
            print("TW1 PAR Editor v1.1")
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
