"""
PEG Particle Viewer – ShankTools Plugin
Visualizes Shank 2 .peg particle effects with real-time preview.
Supports PEG <-> JSON conversion with lossless round-trip.
"""

import struct
import math
import time
import json
import base64
from pathlib import Path


# ══════════════════════════════════════════════════════════════
#  PEG Parser (binary-level)
# ══════════════════════════════════════════════════════════════

class PEGBlock:
    """
    A generic parsed block from the PEG body.
    Keeps the raw bytes so we can reconstruct the file losslessly.
    """
    def __init__(self):
        self.offset = 0
        self.raw = b""           # exact original bytes of this block
        self.block_type = ""     # "emitter", "end_marker", "unknown"
        # Emitter-specific
        self.sub_type = 0
        self.track_type = 0
        self.interp_mode = 0
        self.keyframe_count = 0
        self.keyframes = []      # list of dict {time, v0, v1, v2, v3}


class PEGFile:
    """Fully parsed .peg file — keeps everything needed for lossless rebuild."""
    def __init__(self):
        self.filepath = ""
        self.filename = ""
        self.raw_bytes = b""         # entire original file
        # Header (0x00-0x0F)
        self.magic = b"PGFX"
        self.version = 0
        self.flags = 0
        self.field_0c = 0
        # Derived
        self.loop = False
        # Body
        self.prefix_byte = 0
        self.blocks = []             # list of PEGBlock
        # Tail (everything after the parsed body: text block, padding…)
        self.tail_offset = 0
        self.tail_bytes = b""
        # Text info (parsed from tail for display only)
        self.textures = []
        self.effect_name = ""
        self.bank_name = ""


def _read_u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def _read_f32(data, off):
    return struct.unpack_from("<f", data, off)[0]


def _read_f32_hex(data, off):
    """Read 4 bytes and return the raw hex string (8 chars, little-endian dword)."""
    return data[off:off+4].hex()


def _write_u32(val):
    return struct.pack("<I", val)


def _write_f32(val):
    return struct.pack("<f", val)


def _hex_to_bytes(hex_str):
    """Convert hex string back to 4 bytes."""
    return bytes.fromhex(hex_str)


def parse_peg(filepath):
    """Parse a .peg file into a PEGFile with full round-trip data."""
    fp = Path(filepath)
    data = fp.read_bytes()
    peg = PEGFile()
    peg.filepath = str(fp)
    peg.filename = fp.name
    peg.raw_bytes = data

    if len(data) < 16:
        raise ValueError(f"File too small: {len(data)} bytes")

    peg.magic = data[0:4]
    if peg.magic != b"PGFX":
        raise ValueError(f"Bad magic: {peg.magic!r}")

    peg.version = _read_u32(data, 4)
    peg.flags = _read_u32(data, 8)
    peg.field_0c = _read_u32(data, 12)
    peg.loop = bool(peg.flags & 0x20000000)

    peg.prefix_byte = data[0x10]
    pos = 0x11

    # ── Parse blocks ──────────────────────────────────────────
    while pos + 16 <= len(data):
        d0 = _read_u32(data, pos)

        # End marker (0xFF byte pattern)
        if (d0 & 0xFF) == 0xFF and d0 <= 0xFF:
            blk = PEGBlock()
            blk.offset = pos
            blk.block_type = "end_marker"
            blk.raw = data[pos:pos + 4]
            peg.blocks.append(blk)
            pos += 4
            break

        # Try to read as emitter: sub_type(4) track_type(4) interp(4) kf_count(4) + kf_count*20
        sub_type = d0
        track_type = _read_u32(data, pos + 4)
        interp_mode = _read_u32(data, pos + 8)
        kf_count = _read_u32(data, pos + 12)

        # Sanity check
        if kf_count > 500 or kf_count == 0:
            break

        kf_end = pos + 16 + kf_count * 20
        if kf_end > len(data):
            break

        blk = PEGBlock()
        blk.offset = pos
        blk.block_type = "emitter"
        blk.sub_type = sub_type
        blk.track_type = track_type
        blk.interp_mode = interp_mode
        blk.keyframe_count = kf_count

        kf_start = pos + 16
        for ki in range(kf_count):
            ko = kf_start + ki * 20
            blk.keyframes.append({
                "time": _read_f32(data, ko),
                "v0":   _read_f32(data, ko + 4),
                "v1":   _read_f32(data, ko + 8),
                "v2":   _read_f32(data, ko + 12),
                "v3":   _read_f32(data, ko + 16),
                # Raw hex for lossless round-trip
                "time_hex": _read_f32_hex(data, ko),
                "v0_hex":   _read_f32_hex(data, ko + 4),
                "v1_hex":   _read_f32_hex(data, ko + 8),
                "v2_hex":   _read_f32_hex(data, ko + 12),
                "v3_hex":   _read_f32_hex(data, ko + 16),
            })

        blk.raw = data[pos:kf_end]
        peg.blocks.append(blk)
        pos = kf_end

    # ── Tail ──────────────────────────────────────────────────
    peg.tail_offset = pos
    peg.tail_bytes = data[pos:]

    # Extract readable strings from tail
    _parse_tail_strings(peg)

    return peg


def _parse_tail_strings(peg):
    """Pull out readable ASCII strings from the tail for display."""
    text_data = peg.tail_bytes
    strings = []
    current = bytearray()
    for byte in text_data:
        if 0x20 <= byte < 0x7F:
            current.append(byte)
        else:
            if len(current) >= 3:
                strings.append(current.decode("ascii", errors="replace"))
            current = bytearray()
    if len(current) >= 3:
        strings.append(current.decode("ascii", errors="replace"))

    for s in strings:
        if s.endswith(".tex"):
            peg.textures.append(s)
        elif "Bank" in s or "bank" in s:
            peg.bank_name = s
        elif not peg.effect_name and len(s) > 2:
            peg.effect_name = s


# ══════════════════════════════════════════════════════════════
#  PEG -> JSON  (export)
# ══════════════════════════════════════════════════════════════

def peg_to_dict(peg):
    """
    Convert PEGFile to a JSON-serialisable dict.
    Stores the ENTIRE original file as base64 so rebuild is lossless.
    Each float value has a companion _hex field with the exact original bytes.
    Users edit the float values; the _hex fields are used as fallback
    for unmodified values to guarantee bit-perfect round-trip.
    """
    blocks_out = []
    for blk in peg.blocks:
        if blk.block_type == "emitter":
            blocks_out.append({
                "type":           "emitter",
                "sub_type":       blk.sub_type,
                "track_type":     blk.track_type,
                "interp_mode":    blk.interp_mode,
                "keyframe_count": blk.keyframe_count,
                "keyframes": [
                    {
                        "time":     round(kf["time"], 6),
                        "time_hex": kf["time_hex"],
                        "v0":       round(kf["v0"], 6),
                        "v0_hex":   kf["v0_hex"],
                        "v1":       round(kf["v1"], 6),
                        "v1_hex":   kf["v1_hex"],
                        "v2":       round(kf["v2"], 6),
                        "v2_hex":   kf["v2_hex"],
                        "v3":       round(kf["v3"], 6),
                        "v3_hex":   kf["v3_hex"],
                    }
                    for kf in blk.keyframes
                ],
            })
        elif blk.block_type == "end_marker":
            blocks_out.append({
                "type":      "end_marker",
                "raw_hex":   blk.raw.hex(),
            })

    return {
        "_format":          "ShankTools_PEG_v1",
        "_source_file":     peg.filename,
        "_original_base64": base64.b64encode(peg.raw_bytes).decode("ascii"),
        "header": {
            "magic":      peg.magic.decode("ascii", errors="replace"),
            "version":    peg.version,
            "flags":      peg.flags,
            "flags_hex":  f"0x{peg.flags:08X}",
            "field_0c":   peg.field_0c,
            "loop":       peg.loop,
        },
        "prefix_byte":  peg.prefix_byte,
        "blocks":       blocks_out,
        "text_info": {
            "textures":    peg.textures,
            "effect_name": peg.effect_name,
            "bank_name":   peg.bank_name,
        },
    }


def peg_to_json(peg, indent=2):
    """Return a JSON string from a PEGFile."""
    return json.dumps(peg_to_dict(peg), indent=indent, ensure_ascii=False)


def export_peg_to_json(peg_path, json_path=None):
    """Read a .peg, write a .json next to it (or at json_path)."""
    peg = parse_peg(peg_path)
    if json_path is None:
        json_path = Path(peg_path).with_suffix(".json")
    Path(json_path).write_text(peg_to_json(peg), encoding="utf-8")
    return json_path


# ══════════════════════════════════════════════════════════════
#  JSON -> PEG  (rebuild — lossless)
# ══════════════════════════════════════════════════════════════

def _resolve_float_bytes(kf_json, field_name, original_data, original_offset):
    """
    Decide which 4 bytes to write for a keyframe float field.

    Logic:
      1. If the JSON has a _hex field AND the float value matches what
         that hex decodes to (within rounding tolerance) → use hex bytes
         (bit-perfect original).
      2. If the float value was CHANGED by the user (doesn't match the hex)
         → pack the new float value via struct.
      3. If there's no _hex field at all → fall back to packing the float.
    """
    hex_key = f"{field_name}_hex"
    float_val = kf_json.get(field_name)

    if float_val is None:
        # Field missing from JSON — keep original bytes
        return original_data[original_offset:original_offset + 4]

    hex_str = kf_json.get(hex_key)

    if hex_str and len(hex_str) == 8:
        # Decode the hex to get the original float
        try:
            orig_bytes = bytes.fromhex(hex_str)
            orig_float = struct.unpack("<f", orig_bytes)[0]

            # Check if the user's float value matches the original
            # (within the rounding tolerance used during export)
            if round(orig_float, 6) == round(float_val, 6):
                # Value unchanged → return exact original bytes
                return orig_bytes
            else:
                # Value was edited → pack the new float
                return struct.pack("<f", float_val)
        except (ValueError, struct.error):
            pass

    # No hex or invalid hex → pack the float value
    return struct.pack("<f", float_val)


def rebuild_peg_from_json(json_path, peg_path=None):
    """
    Read a .json exported by this tool and rebuild the .peg.

    Strategy (lossless):
      1. Decode the embedded _original_base64 → get EXACT original bytes.
      2. Re-parse that original to find block offsets.
      3. For each keyframe float, compare the JSON float against its _hex
         companion. If unchanged → write original bytes. If changed → pack new float.
      4. Header flags, tail, padding — everything else stays byte-identical.

    This guarantees bit-perfect round-trip for unmodified values.
    """
    json_path = Path(json_path)
    js = json.loads(json_path.read_text(encoding="utf-8"))

    if js.get("_format") != "ShankTools_PEG_v1":
        raise ValueError("Not a ShankTools PEG JSON (missing _format)")

    # ── Recover original bytes ────────────────────────────────
    original = base64.b64decode(js["_original_base64"])
    data = bytearray(original)  # mutable copy

    # ── Re-parse original to get block offsets ────────────────
    pos = 0x11
    ref_blocks = []

    while pos + 16 <= len(original):
        d0 = _read_u32(original, pos)
        if (d0 & 0xFF) == 0xFF and d0 <= 0xFF:
            ref_blocks.append({"type": "end_marker", "offset": pos, "size": 4})
            pos += 4
            break
        kf_count = _read_u32(original, pos + 12)
        if kf_count > 500 or kf_count == 0:
            break
        blk_size = 16 + kf_count * 20
        if pos + blk_size > len(original):
            break
        ref_blocks.append({
            "type": "emitter", "offset": pos, "size": blk_size,
            "kf_count": kf_count,
        })
        pos += blk_size

    # ── Patch header flags ────────────────────────────────────
    jh = js.get("header", {})
    if "flags" in jh:
        struct.pack_into("<I", data, 8, jh["flags"])
    if "field_0c" in jh:
        struct.pack_into("<I", data, 12, jh["field_0c"])
    if "version" in jh:
        struct.pack_into("<I", data, 4, jh["version"])

    # ── Patch prefix byte ─────────────────────────────────────
    if "prefix_byte" in js:
        data[0x10] = js["prefix_byte"] & 0xFF

    # ── Patch emitter blocks ──────────────────────────────────
    json_emitters = [b for b in js.get("blocks", []) if b.get("type") == "emitter"]
    ref_emitters = [b for b in ref_blocks if b["type"] == "emitter"]

    for ji, je in enumerate(json_emitters):
        if ji >= len(ref_emitters):
            break

        rb = ref_emitters[ji]
        off = rb["offset"]

        # Patch emitter header (sub_type, track_type, interp_mode)
        struct.pack_into("<I", data, off,      je.get("sub_type", _read_u32(original, off)))
        struct.pack_into("<I", data, off + 4,  je.get("track_type", _read_u32(original, off + 4)))
        struct.pack_into("<I", data, off + 8,  je.get("interp_mode", _read_u32(original, off + 8)))

        # Keyframes — MUST keep same count to preserve offsets
        jkfs = je.get("keyframes", [])
        orig_kf_count = rb["kf_count"]

        if len(jkfs) != orig_kf_count:
            continue

        kf_base = off + 16
        for ki, kf in enumerate(jkfs):
            ko = kf_base + ki * 20

            # Each field: use _hex bytes if value unchanged, else pack new float
            for fi, field_name in enumerate(["time", "v0", "v1", "v2", "v3"]):
                field_offset = ko + fi * 4
                new_bytes = _resolve_float_bytes(kf, field_name, original, field_offset)
                data[field_offset:field_offset + 4] = new_bytes

    # ── Write output ──────────────────────────────────────────
    if peg_path is None:
        peg_path = json_path.with_suffix(".peg")
    peg_path = Path(peg_path)
    peg_path.write_bytes(bytes(data))
    return peg_path


# ══════════════════════════════════════════════════════════════
#  Info / Display Helpers
# ══════════════════════════════════════════════════════════════

def format_peg_info(peg):
    lines = []
    lines.append(f"{'═' * 56}")
    lines.append(f"  FILE: {peg.filename}  ({len(peg.raw_bytes)} bytes)")
    lines.append(f"{'═' * 56}")
    lines.append(f"  magic  = {peg.magic}")
    lines.append(f"  ver    = {peg.version}")
    lines.append(f"  flags  = 0x{peg.flags:08X}  loop={peg.loop}")
    lines.append(f"  f_0C   = 0x{peg.field_0c:08X}")
    lines.append(f"  prefix = 0x{peg.prefix_byte:02X}")
    lines.append("")

    emitter_idx = 0
    for blk in peg.blocks:
        if blk.block_type == "emitter":
            lines.append(f"  ── Emitter {emitter_idx} ──")
            lines.append(f"    sub_type  = {blk.sub_type}")
            lines.append(f"    track     = {blk.track_type}")
            lines.append(f"    interp    = {blk.interp_mode}")
            lines.append(f"    keyframes = {blk.keyframe_count}")
            for ki, kf in enumerate(blk.keyframes):
                lines.append(
                    f"      [{ki:2d}] t={kf['time']:8.4f}  "
                    f"({kf['v0']:7.4f}, {kf['v1']:7.4f}, "
                    f"{kf['v2']:7.4f}, {kf['v3']:7.4f})"
                )
            emitter_idx += 1
        elif blk.block_type == "end_marker":
            lines.append(f"  ── End marker ── (0x{blk.raw.hex()})")
    lines.append("")

    if peg.textures:
        lines.append(f"  Textures : {', '.join(peg.textures)}")
    if peg.effect_name:
        lines.append(f"  Effect   : {peg.effect_name}")
    if peg.bank_name:
        lines.append(f"  Bank     : {peg.bank_name}")

    return "\n".join(lines)


def lerp(a, b, t):
    return a + (b - a) * t


def sample_color_at(keyframes, t):
    if not keyframes:
        return (1.0, 1.0, 1.0, 1.0)
    if len(keyframes) == 1:
        kf = keyframes[0]
        return (kf["v0"], kf["v1"], kf["v2"], kf["v3"])
    if t <= keyframes[0]["time"]:
        kf = keyframes[0]
        return (kf["v0"], kf["v1"], kf["v2"], kf["v3"])
    if t >= keyframes[-1]["time"]:
        kf = keyframes[-1]
        return (kf["v0"], kf["v1"], kf["v2"], kf["v3"])
    for i in range(len(keyframes) - 1):
        k0 = keyframes[i]
        k1 = keyframes[i + 1]
        if k0["time"] <= t <= k1["time"]:
            dt = k1["time"] - k0["time"]
            frac = (t - k0["time"]) / dt if dt > 0 else 0
            return (
                lerp(k0["v0"], k1["v0"], frac),
                lerp(k0["v1"], k1["v1"], frac),
                lerp(k0["v2"], k1["v2"], frac),
                lerp(k0["v3"], k1["v3"], frac),
            )
    kf = keyframes[-1]
    return (kf["v0"], kf["v1"], kf["v2"], kf["v3"])


def clamp_byte(v):
    return max(0, min(255, int(v * 255)))


def rgba_to_hex(r, g, b, a=1.0):
    return f"#{clamp_byte(r):02X}{clamp_byte(g):02X}{clamp_byte(b):02X}"


# ══════════════════════════════════════════════════════════════
#  Registration & Full UI
# ══════════════════════════════════════════════════════════════

def register(tool):
    tool(
        icon="✨",
        title="PEG Particle Viewer",
        desc="View, inspect, and convert Shank 2 PEG particle effects (PEG ↔ JSON)",
        tool_info={
            "name": "PEG Particle Viewer",
            "icon": "✨",
            "custom_ui": True,
            "builder": build_peg_panel,
        },
    )


def build_peg_panel(parent, theme, status_cb, back_cb):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    # ── State ─────────────────────────────────────────────────
    loaded_pegs = {}
    selected_files = []
    current_peg = [None]
    anim_running = [False]
    anim_time = [0.0]
    anim_speed = [1.0]
    anim_after_id = [None]
    last_tick = [time.time()]

    # ── Main ──────────────────────────────────────────────────
    main = tk.Frame(parent, bg=theme["bg"])
    main.pack(fill="both", expand=True)

    # ── Top bar ───────────────────────────────────────────────
    top_bar = tk.Frame(main, bg=theme["bg_secondary"], height=50)
    top_bar.pack(fill="x")
    top_bar.pack_propagate(False)

    tk.Button(
        top_bar, text="← Back", bg=theme["btn_bg"], fg=theme["btn_fg"],
        font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2",
        activebackground=theme["btn_hover"], command=back_cb,
    ).pack(side="left", padx=10, pady=8)

    tk.Label(
        top_bar, text="✨ PEG Particle Viewer",
        bg=theme["bg_secondary"], fg=theme["text"],
        font=("Segoe UI", 14, "bold"),
    ).pack(side="left", padx=10, pady=10)

    # ── Content ───────────────────────────────────────────────
    content = tk.Frame(main, bg=theme["bg"])
    content.pack(fill="both", expand=True, padx=10, pady=8)

    # LEFT PANEL
    left_panel = tk.Frame(content, bg=theme["bg_panel"], width=340)
    left_panel.pack(side="left", fill="y", padx=(0, 6))
    left_panel.pack_propagate(False)

    # RIGHT PANEL
    right_panel = tk.Frame(content, bg=theme["bg"])
    right_panel.pack(side="left", fill="both", expand=True)

    # ══════════════════════════════════════════════════════════
    #  LEFT — File List
    # ══════════════════════════════════════════════════════════
    tk.Label(left_panel, text="PEG / JSON Files",
             bg=theme["bg_panel"], fg=theme["text"],
             font=("Segoe UI", 12, "bold")).pack(padx=10, pady=(10, 4), anchor="w")

    fl_frame = tk.Frame(left_panel, bg=theme["bg_panel"])
    fl_frame.pack(fill="both", expand=True, padx=10, pady=4)

    file_listbox = tk.Listbox(
        fl_frame, bg=theme["entry_bg"], fg=theme["entry_fg"],
        selectbackground=theme["accent"], selectforeground="#FFFFFF",
        font=("Consolas", 9), relief="flat", bd=0, selectmode="browse",
    )
    fl_sb = ttk.Scrollbar(fl_frame, orient="vertical", command=file_listbox.yview)
    file_listbox.configure(yscrollcommand=fl_sb.set)
    fl_sb.pack(side="right", fill="y")
    file_listbox.pack(side="left", fill="both", expand=True)

    def add_files():
        paths = filedialog.askopenfilenames(
            title="Select PEG / JSON files",
            filetypes=[("PEG & JSON", "*.peg *.json"), ("PEG", "*.peg"),
                       ("JSON", "*.json"), ("All", "*.*")],
        )
        for p in paths:
            p = Path(p)
            if p not in selected_files:
                selected_files.append(p)
                file_listbox.insert("end", p.name)
        _update_count()

    def add_folder():
        folder = filedialog.askdirectory(title="Select folder")
        if not folder:
            return
        folder = Path(folder)
        for ext in ("*.peg", "*.json"):
            for f in sorted(folder.glob(ext)):
                if f not in selected_files:
                    selected_files.append(f)
                    file_listbox.insert("end", f.name)
        _update_count()

    def remove_sel():
        for i in reversed(file_listbox.curselection()):
            file_listbox.delete(i)
            selected_files.pop(i)
        _update_count()

    def clear_all():
        file_listbox.delete(0, "end")
        selected_files.clear()
        loaded_pegs.clear()
        _update_count()

    def _update_count():
        pegs = sum(1 for f in selected_files if f.suffix.lower() == ".peg")
        jsns = sum(1 for f in selected_files if f.suffix.lower() == ".json")
        count_lbl.config(text=f"{len(selected_files)} file(s)  |  PEG: {pegs}  JSON: {jsns}")

    btn_frame = tk.Frame(left_panel, bg=theme["bg_panel"])
    btn_frame.pack(fill="x", padx=10, pady=4)
    for txt, cmd in [("+ Files", add_files), ("+ Folder", add_folder),
                     ("Remove", remove_sel), ("Clear", clear_all)]:
        tk.Button(
            btn_frame, text=txt, bg=theme["entry_bg"], fg=theme["text"],
            font=("Segoe UI", 9), relief="flat", cursor="hand2", command=cmd,
            activebackground=theme["btn_hover"], activeforeground="#FFF",
        ).pack(side="left", padx=2, pady=2, expand=True, fill="x")

    count_lbl = tk.Label(left_panel, text="0 file(s)",
                         bg=theme["bg_panel"], fg=theme["text_secondary"],
                         font=("Segoe UI", 9))
    count_lbl.pack(padx=10, pady=(0, 4), anchor="w")

    # ── Options ───────────────────────────────────────────────
    tk.Frame(left_panel, bg=theme["border"], height=1).pack(fill="x", padx=10, pady=4)
    tk.Label(left_panel, text="Options",
             bg=theme["bg_panel"], fg=theme["text"],
             font=("Segoe UI", 11, "bold")).pack(padx=10, pady=(6, 4), anchor="w")

    output_dir_var = tk.StringVar(value="")

    def pick_out():
        d = filedialog.askdirectory(title="Output directory")
        if d:
            output_dir_var.set(d)

    of = tk.Frame(left_panel, bg=theme["bg_panel"])
    of.pack(fill="x", padx=10, pady=2)
    tk.Label(of, text="Output folder:", bg=theme["bg_panel"], fg=theme["text"],
             font=("Segoe UI", 9)).pack(anchor="w")
    oef = tk.Frame(of, bg=theme["bg_panel"])
    oef.pack(fill="x")
    tk.Entry(oef, textvariable=output_dir_var, bg=theme["entry_bg"], fg=theme["entry_fg"],
             insertbackground=theme["text"], relief="flat", font=("Segoe UI", 9)
             ).pack(side="left", fill="x", expand=True, ipady=3)
    tk.Button(oef, text="...", bg=theme["entry_bg"], fg=theme["text"],
              font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
              width=3, command=pick_out).pack(side="right")
    tk.Label(of, text="(empty = same as input file)",
             bg=theme["bg_panel"], fg=theme["text_secondary"],
             font=("Segoe UI", 8)).pack(anchor="w")

    # ── Action Buttons ────────────────────────────────────────
    tk.Frame(left_panel, bg=theme["border"], height=1).pack(fill="x", padx=10, pady=6)
    af = tk.Frame(left_panel, bg=theme["bg_panel"])
    af.pack(fill="x", padx=10, pady=(0, 10))

    def _threaded(fn):
        import threading as _t
        _t.Thread(target=fn, daemon=True).start()

    def _out_path(src_path, new_suffix):
        out_dir = output_dir_var.get().strip()
        if out_dir:
            return Path(out_dir) / (src_path.stem + new_suffix)
        return src_path.with_suffix(new_suffix)

    def do_export_json():
        pegs = [f for f in selected_files if f.suffix.lower() == ".peg"]
        if not pegs:
            messagebox.showwarning("No PEG", "Add .peg files first.")
            return
        _log_clear()
        _log(f"Exporting {len(pegs)} PEG -> JSON ...\n")
        status_cb(f"Exporting {len(pegs)} file(s)...")

        def work():
            ok = 0
            for fp in pegs:
                try:
                    peg = parse_peg(fp)
                    out = _out_path(fp, ".json")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(peg_to_json(peg), encoding="utf-8")
                    _log(f"  OK  {fp.name} -> {out.name}")
                    ok += 1
                except Exception as ex:
                    _log(f"  ERR {fp.name}: {ex}")
            _log(f"\nDone: {ok}/{len(pegs)}")
            status_cb(f"Export: {ok}/{len(pegs)}")
        _threaded(work)

    def do_rebuild_peg():
        jsons = [f for f in selected_files if f.suffix.lower() == ".json"]
        if not jsons:
            messagebox.showwarning("No JSON", "Add .json files first.")
            return
        _log_clear()
        _log(f"Rebuilding {len(jsons)} JSON -> PEG ...\n")
        status_cb(f"Rebuilding {len(jsons)} file(s)...")

        def work():
            ok = 0
            for fp in jsons:
                try:
                    out = _out_path(fp, ".peg")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    rebuild_peg_from_json(fp, out)
                    _log(f"  OK  {fp.name} -> {out.name}")
                    ok += 1
                except Exception as ex:
                    _log(f"  ERR {fp.name}: {ex}")
            _log(f"\nDone: {ok}/{len(jsons)}")
            status_cb(f"Rebuild: {ok}/{len(jsons)}")
        _threaded(work)

    def do_info():
        sel = file_listbox.curselection()
        targets = [selected_files[i] for i in sel] if sel else [
            f for f in selected_files if f.suffix.lower() == ".peg"
        ]
        if not targets:
            messagebox.showwarning("No files", "Select or add .peg files.")
            return
        _log_clear()
        status_cb(f"Inspecting {len(targets)} file(s)...")

        def work():
            for fp in targets:
                if fp.suffix.lower() != ".peg":
                    _log(f"  SKIP {fp.name} (not .peg)")
                    continue
                try:
                    peg = parse_peg(fp)
                    _log(format_peg_info(peg))
                except Exception as ex:
                    _log(f"  ERR {fp.name}: {ex}")
                _log("")
            status_cb("Info done")
        _threaded(work)

    for txt, cmd, clr in [
        ("📄 Export PEG → JSON",  do_export_json,  theme["btn_bg"]),
        ("🔧 Rebuild JSON → PEG", do_rebuild_peg,  theme["accent"]),
        ("ℹ File Info",           do_info,          theme["entry_bg"]),
    ]:
        tk.Button(
            af, text=txt, bg=clr,
            fg=theme["btn_fg"] if clr != theme["entry_bg"] else theme["text"],
            font=("Segoe UI", 11, "bold"), relief="flat", cursor="hand2",
            command=cmd, activebackground=theme["btn_hover"],
            activeforeground="#FFF",
        ).pack(fill="x", pady=3, ipady=6)

    # ══════════════════════════════════════════════════════════
    #  RIGHT TOP — Visual Preview
    # ══════════════════════════════════════════════════════════
    preview_frame = tk.Frame(right_panel, bg=theme["bg_panel"])
    preview_frame.pack(fill="both", expand=True, pady=(0, 4))

    tk.Label(preview_frame, text="Particle Preview",
             bg=theme["bg_panel"], fg=theme["text"],
             font=("Segoe UI", 12, "bold")).pack(padx=12, pady=(10, 4), anchor="w")

    canvas_frame = tk.Frame(preview_frame, bg="#000000", bd=1, relief="sunken")
    canvas_frame.pack(fill="both", expand=True, padx=12, pady=(0, 4))

    canvas = tk.Canvas(canvas_frame, bg="#1A1A2E", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    grad_frame = tk.Frame(preview_frame, bg=theme["bg_panel"], height=50)
    grad_frame.pack(fill="x", padx=12, pady=(0, 4))
    grad_frame.pack_propagate(False)

    tk.Label(grad_frame, text="Color Timeline:",
             bg=theme["bg_panel"], fg=theme["text_secondary"],
             font=("Segoe UI", 8)).pack(anchor="w")

    gradient_canvas = tk.Canvas(grad_frame, bg="#222222", height=30,
                                highlightthickness=0)
    gradient_canvas.pack(fill="x", expand=True, pady=(0, 2))

    ctrl_frame = tk.Frame(preview_frame, bg=theme["bg_panel"])
    ctrl_frame.pack(fill="x", padx=12, pady=(0, 8))

    time_lbl = tk.Label(ctrl_frame, text="t = 0.000",
                        bg=theme["bg_panel"], fg=theme["accent"],
                        font=("Consolas", 10, "bold"))
    time_lbl.pack(side="left")

    color_swatch = tk.Frame(ctrl_frame, bg="#FFFFFF", width=40, height=20,
                            relief="solid", bd=1)
    color_swatch.pack(side="left", padx=8)
    color_swatch.pack_propagate(False)

    rgba_lbl = tk.Label(ctrl_frame, text="RGBA(—)",
                        bg=theme["bg_panel"], fg=theme["text_secondary"],
                        font=("Consolas", 9))
    rgba_lbl.pack(side="left", padx=4)

    tk.Label(ctrl_frame, text="Speed:", bg=theme["bg_panel"],
             fg=theme["text_secondary"], font=("Segoe UI", 9)).pack(side="right", padx=(4, 0))

    speed_scale = tk.Scale(ctrl_frame, from_=0.1, to=3.0, resolution=0.1,
                           orient="horizontal", variable=tk.DoubleVar(value=1.0),
                           bg=theme["bg_panel"], fg=theme["text"],
                           highlightthickness=0, length=100,
                           troughcolor=theme["entry_bg"], font=("Segoe UI", 7),
                           command=lambda v: anim_speed.__setitem__(0, float(v)))
    speed_scale.pack(side="right")

    def btn_toggle_play():
        if anim_running[0]:
            anim_running[0] = False
            play_btn.config(text="▶ Play")
        else:
            if not current_peg[0]:
                return
            anim_running[0] = True
            last_tick[0] = time.time()
            play_btn.config(text="⏸ Pause")
            _animate()

    def btn_stop():
        anim_running[0] = False
        anim_time[0] = 0.0
        play_btn.config(text="▶ Play")
        if anim_after_id[0]:
            parent.after_cancel(anim_after_id[0])
            anim_after_id[0] = None
        _render_frame(0.0)

    play_btn = tk.Button(ctrl_frame, text="▶ Play", bg=theme["accent"],
                         fg="#FFF", font=("Segoe UI", 9, "bold"),
                         relief="flat", cursor="hand2", command=btn_toggle_play)
    play_btn.pack(side="right", padx=4)

    tk.Button(ctrl_frame, text="⏹ Stop", bg=theme["entry_bg"],
              fg=theme["text"], font=("Segoe UI", 9, "bold"),
              relief="flat", cursor="hand2", command=btn_stop).pack(side="right", padx=2)

    def _get_max_time():
        peg = current_peg[0]
        if not peg:
            return 1.0
        mx = 1.0
        for blk in peg.blocks:
            if blk.block_type == "emitter" and blk.keyframes:
                mt = blk.keyframes[-1]["time"]
                if mt > mx:
                    mx = mt
        return mx

    def _get_first_emitter_kfs():
        peg = current_peg[0]
        if not peg:
            return None
        for blk in peg.blocks:
            if blk.block_type == "emitter" and blk.keyframes:
                return blk.keyframes
        return None

    def _animate():
        if not anim_running[0] or not current_peg[0]:
            return
        now = time.time()
        dt = now - last_tick[0]
        last_tick[0] = now
        anim_time[0] += dt * anim_speed[0]
        max_t = _get_max_time()
        peg = current_peg[0]

        if peg.loop:
            if anim_time[0] > max_t:
                anim_time[0] %= max_t
        else:
            if anim_time[0] > max_t:
                anim_time[0] = max_t
                anim_running[0] = False
                play_btn.config(text="▶ Play")

        _render_frame(anim_time[0])
        anim_after_id[0] = parent.after(16, _animate)

    def _render_frame(t):
        kfs = _get_first_emitter_kfs()
        if not kfs:
            return
        r, g, b, a = sample_color_at(kfs, t)

        time_lbl.config(text=f"t = {t:.3f}")
        rgba_lbl.config(text=f"RGBA({r:.3f}, {g:.3f}, {b:.3f}, {a:.3f})")
        hex_c = rgba_to_hex(r, g, b)
        color_swatch.config(bg=hex_c)

        canvas.delete("all")
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        if cw < 10 or ch < 10:
            return
        cx, cy = cw // 2, ch // 2

        gc = "#252540"
        for gx in range(0, cw, 40):
            canvas.create_line(gx, 0, gx, ch, fill=gc)
        for gy in range(0, ch, 40):
            canvas.create_line(0, gy, cw, gy, fill=gc)
        canvas.create_line(cx - 15, cy, cx + 15, cy, fill="#404060")
        canvas.create_line(cx, cy - 15, cx, cy + 15, fill="#404060")

        ar = max(5, int(a * 80))

        for i in range(5, 0, -1):
            gr_r = ar + i * 12
            ga = a * (0.15 / i)
            _r = clamp_byte(r * ga + 0.1 * (1 - ga))
            _g = clamp_byte(g * ga + 0.1 * (1 - ga))
            _b = clamp_byte(b * ga + 0.1 * (1 - ga))
            canvas.create_oval(cx - gr_r, cy - gr_r, cx + gr_r, cy + gr_r,
                               fill=f"#{_r:02X}{_g:02X}{_b:02X}", outline="")

        canvas.create_oval(cx - ar, cy - ar, cx + ar, cy + ar,
                           fill=hex_c, outline="")

        ir = max(3, ar // 3)
        bright = rgba_to_hex(min(1, r + 0.3), min(1, g + 0.3), min(1, b + 0.3))
        canvas.create_oval(cx - ir, cy - ir, cx + ir, cy + ir,
                           fill=bright, outline="")

        np_ = max(3, int(a * 12))
        for pi in range(np_):
            angle = (pi / np_) * math.pi * 2 + t * 2.0
            dist = ar + 20 + math.sin(t * 3 + pi) * 15
            px = cx + math.cos(angle) * dist
            py = cy + math.sin(angle) * dist
            pr = max(1, int(3 * a))
            pa = max(0.2, a * 0.6)
            canvas.create_oval(px - pr, py - pr, px + pr, py + pr,
                               fill=rgba_to_hex(r * pa, g * pa, b * pa), outline="")

        peg = current_peg[0]
        canvas.create_text(10, ch - 25,
                           text=f"Effect: {peg.effect_name or peg.filename}",
                           fill="#808090", font=("Consolas", 9), anchor="w")
        canvas.create_text(10, ch - 10,
                           text=f"Loop: {peg.loop}  |  α: {a:.2f}",
                           fill="#808090", font=("Consolas", 9), anchor="w")

        bx = cw - 30
        bh = ch - 40
        bt = 20
        canvas.create_rectangle(bx, bt, bx + 15, bt + bh,
                                fill="#222233", outline="#404060")
        fh = int(bh * a)
        canvas.create_rectangle(bx, bt + bh - fh, bx + 15, bt + bh,
                                fill=hex_c, outline="")
        canvas.create_text(bx + 7, bt - 8, text="α",
                           fill="#808090", font=("Consolas", 9))

    def _draw_gradient():
        gradient_canvas.delete("all")
        gw = gradient_canvas.winfo_width()
        gh = gradient_canvas.winfo_height()
        kfs = _get_first_emitter_kfs()
        if gw < 10 or not kfs:
            return
        max_t = kfs[-1]["time"]
        if max_t <= 0:
            max_t = 1.0
        step = max(1, gw // 200)
        for x in range(0, gw, step):
            t = (x / gw) * max_t
            r, g, b, a = sample_color_at(kfs, t)
            gradient_canvas.create_rectangle(x, 0, x + step, gh,
                                             fill=rgba_to_hex(r * a, g * a, b * a),
                                             outline="")
        for kf in kfs:
            kx = int((kf["time"] / max_t) * gw)
            gradient_canvas.create_line(kx, 0, kx, gh, fill="#FFFF00", width=1)
            gradient_canvas.create_oval(kx - 3, gh // 2 - 3, kx + 3, gh // 2 + 3,
                                        fill="#FFFF00", outline="#000")

    def on_file_select(event=None):
        sel = file_listbox.curselection()
        if not sel:
            return
        fp = selected_files[sel[0]]

        if fp.suffix.lower() == ".peg":
            if fp.name not in loaded_pegs:
                try:
                    peg = parse_peg(fp)
                    loaded_pegs[fp.name] = peg
                    _log(f"Loaded: {fp.name}")
                except Exception as ex:
                    _log(f"ERROR: {fp.name}: {ex}")
                    return
            current_peg[0] = loaded_pegs[fp.name]
            show_info(format_peg_info(current_peg[0]))
            status_cb(f"Viewing: {current_peg[0].filename}")
            btn_stop()
            parent.after(50, lambda: (_render_frame(0.0), _draw_gradient()))

        elif fp.suffix.lower() == ".json":
            try:
                js = json.loads(fp.read_text(encoding="utf-8"))
                if js.get("_format") == "ShankTools_PEG_v1":
                    orig = base64.b64decode(js["_original_base64"])
                    tmp = Path(fp).with_name("__tmp_preview__.peg")
                    tmp.write_bytes(orig)
                    peg = parse_peg(tmp)
                    tmp.unlink(missing_ok=True)
                    json_emitters = [b for b in js.get("blocks", [])
                                     if b.get("type") == "emitter"]
                    peg_emitters = [b for b in peg.blocks
                                    if b.block_type == "emitter"]
                    for ji, je in enumerate(json_emitters):
                        if ji < len(peg_emitters):
                            pe = peg_emitters[ji]
                            pe.sub_type = je.get("sub_type", pe.sub_type)
                            pe.track_type = je.get("track_type", pe.track_type)
                            pe.interp_mode = je.get("interp_mode", pe.interp_mode)
                            jkfs = je.get("keyframes", [])
                            if len(jkfs) == len(pe.keyframes):
                                for ki, jkf in enumerate(jkfs):
                                    pe.keyframes[ki] = {
                                        "time": jkf.get("time", pe.keyframes[ki]["time"]),
                                        "v0": jkf.get("v0", pe.keyframes[ki]["v0"]),
                                        "v1": jkf.get("v1", pe.keyframes[ki]["v1"]),
                                        "v2": jkf.get("v2", pe.keyframes[ki]["v2"]),
                                        "v3": jkf.get("v3", pe.keyframes[ki]["v3"]),
                                    }
                    jh = js.get("header", {})
                    if "flags" in jh:
                        peg.flags = jh["flags"]
                        peg.loop = bool(peg.flags & 0x20000000)

                    loaded_pegs[fp.name] = peg
                    current_peg[0] = peg
                    show_info(format_peg_info(peg))
                    status_cb(f"Preview JSON: {fp.name}")
                    btn_stop()
                    parent.after(50, lambda: (_render_frame(0.0), _draw_gradient()))
                    _log(f"Loaded JSON preview: {fp.name}")
                else:
                    _log(f"Not a ShankTools PEG JSON: {fp.name}")
            except Exception as ex:
                _log(f"ERROR reading JSON: {fp.name}: {ex}")

    file_listbox.bind("<<ListboxSelect>>", on_file_select)

    tk.Frame(left_panel, bg=theme["border"], height=1).pack(fill="x", padx=10, pady=4)
    tk.Label(left_panel, text="File Info",
             bg=theme["bg_panel"], fg=theme["text"],
             font=("Segoe UI", 11, "bold")).pack(padx=10, pady=(6, 2), anchor="w")

    info_container = tk.Frame(left_panel, bg=theme["bg_panel"])
    info_container.pack(fill="both", expand=False, padx=10, pady=(0, 10))

    info_text = tk.Text(info_container, bg=theme["entry_bg"], fg=theme["entry_fg"],
                        font=("Consolas", 8), relief="flat", bd=0,
                        wrap="word", state="disabled", height=10)
    info_sb = ttk.Scrollbar(info_container, orient="vertical", command=info_text.yview)
    info_text.configure(yscrollcommand=info_sb.set)
    info_sb.pack(side="right", fill="y")
    info_text.pack(side="left", fill="both", expand=True)

    def show_info(text):
        info_text.config(state="normal")
        info_text.delete("1.0", "end")
        info_text.insert("end", text)
        info_text.config(state="disabled")

    # ══════════════════════════════════════════════════════════
    #  RIGHT BOTTOM — Log
    # ══════════════════════════════════════════════════════════
    log_frame = tk.Frame(right_panel, bg=theme["bg_panel"], height=160)
    log_frame.pack(fill="x", pady=(4, 0))
    log_frame.pack_propagate(False)

    tk.Label(log_frame, text="Output Log",
             bg=theme["bg_panel"], fg=theme["text"],
             font=("Segoe UI", 10, "bold")).pack(padx=10, pady=(6, 2), anchor="w")

    log_text = tk.Text(log_frame, bg=theme["entry_bg"], fg=theme["entry_fg"],
                       insertbackground=theme["text"], font=("Consolas", 9),
                       relief="flat", bd=0, wrap="word", state="disabled", height=6)
    log_sc = ttk.Scrollbar(log_frame, orient="vertical", command=log_text.yview)
    log_text.configure(yscrollcommand=log_sc.set)
    log_sc.pack(side="right", fill="y", padx=(0, 4), pady=(0, 6))
    log_text.pack(fill="both", expand=True, padx=(10, 0), pady=(0, 6))

    def _log(msg):
        def _u():
            log_text.config(state="normal")
            log_text.insert("end", msg + "\n")
            log_text.see("end")
            log_text.config(state="disabled")
        parent.after(0, _u)

    def _log_clear():
        def _u():
            log_text.config(state="normal")
            log_text.delete("1.0", "end")
            log_text.config(state="disabled")
        parent.after(0, _u)

    _log("PEG Particle Viewer ready.")
    _log("Supports: PEG ↔ JSON lossless conversion.")
    _log("Add .peg or .json files, select to preview.")
    _log("-" * 40)

    def on_resize(event=None):
        if current_peg[0]:
            _render_frame(anim_time[0])
            _draw_gradient()

    canvas.bind("<Configure>", on_resize)
    gradient_canvas.bind("<Configure>", on_resize)

    return main