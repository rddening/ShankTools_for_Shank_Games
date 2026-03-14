import struct
import sys
import os
import shutil
import json
import time as _time

# ══════════════════════════════════════
#  Colors
# ══════════════════════════════════════

class Colors:
    H = '\033[95m'; B = '\033[94m'; C = '\033[96m'
    G = '\033[92m'; Y = '\033[93m'; R = '\033[91m'
    E = '\033[0m'; BOLD = '\033[1m'


CHUNK_MAGICS = {b'MHIT', b'MACT', b'MCOL'}


# ══════════════════════════════════════
#  Generic Chunk (raw blob)
# ══════════════════════════════════════

class RawChunk:
    """Stores a chunk as raw bytes for perfect roundtrip"""
    def __init__(self, magic, data):
        self.magic = magic
        self.raw = data

    @property
    def chunk_type(self):
        return self.magic.decode('ascii')

    @property
    def byte_size(self):
        return len(self.raw)

    def to_bytes(self):
        return self.raw

    @property
    def anim_hash(self):
        if len(self.raw) >= 8:
            return struct.unpack_from('<I', self.raw, 4)[0]
        return 0

    @property
    def event_hash(self):
        if len(self.raw) >= 12:
            return struct.unpack_from('<I', self.raw, 8)[0]
        return 0

    @property
    def start_time(self):
        if len(self.raw) >= 16:
            return struct.unpack_from('<f', self.raw, 12)[0]
        return 0.0

    @property
    def end_time(self):
        if len(self.raw) >= 20:
            return struct.unpack_from('<f', self.raw, 16)[0]
        return 0.0

    @property
    def duration(self):
        return self.end_time - self.start_time


# ══════════════════════════════════════
#  Phase (supports variable bbox_type)
# ══════════════════════════════════════

class Phase:
    def __init__(self, phase_time=0.0, bbox_type=4,
                 minX=0.0, minY=0.0, maxX=100.0, maxY=100.0,
                 raw_floats=None):
        self.phase_time = phase_time
        self.bbox_type = bbox_type
        if raw_floats is not None:
            self._raw_floats = list(raw_floats)
        else:
            self._raw_floats = None
        self.minX = float(minX)
        self.minY = float(minY)
        self.maxX = float(maxX)
        self.maxY = float(maxY)

    @property
    def num_floats(self):
        return self.bbox_type * 2

    @property
    def phase_byte_size(self):
        return 8 + self.bbox_type * 8

    def get_corners(self):
        return [
            (self.minX, self.minY),
            (self.minX, self.maxY),
            (self.maxX, self.maxY),
            (self.maxX, self.minY),
        ]

    def get_floats(self):
        if self._raw_floats is not None:
            return list(self._raw_floats)
        c = self.get_corners()
        return [c[0][0], c[0][1], c[1][0], c[1][1],
                c[2][0], c[2][1], c[3][0], c[3][1]]

    @property
    def width(self):
        return self.maxX - self.minX

    @property
    def height(self):
        return self.maxY - self.minY

    def scale(self, factor):
        cx = (self.minX + self.maxX) / 2
        cy = (self.minY + self.maxY) / 2
        hw = self.width / 2 * factor
        hh = self.height / 2 * factor
        self.minX = cx - hw; self.maxX = cx + hw
        self.minY = cy - hh; self.maxY = cy + hh
        if self._raw_floats is not None:
            scaled = []
            for i in range(0, len(self._raw_floats), 2):
                x = self._raw_floats[i]
                y = self._raw_floats[i + 1] if i + 1 < len(self._raw_floats) else 0.0
                scaled.append(cx + (x - cx) * factor)
                scaled.append(cy + (y - cy) * factor)
            self._raw_floats = scaled

    def move(self, dx=0, dy=0):
        self.minX += dx; self.maxX += dx
        self.minY += dy; self.maxY += dy
        if self._raw_floats is not None:
            for i in range(0, len(self._raw_floats), 2):
                self._raw_floats[i] += dx
                if i + 1 < len(self._raw_floats):
                    self._raw_floats[i + 1] += dy

    def to_bytes(self):
        result = struct.pack('<f', self.phase_time)
        result += struct.pack('<I', self.bbox_type)
        for fv in self.get_floats():
            result += struct.pack('<f', fv)
        return result

    @staticmethod
    def from_bytes(data, offset=0):
        ph = Phase.__new__(Phase)
        ph.phase_time = struct.unpack_from('<f', data, offset)[0]
        ph.bbox_type = struct.unpack_from('<I', data, offset + 4)[0]
        num_floats = ph.bbox_type * 2
        floats = []
        for i in range(num_floats):
            floats.append(struct.unpack_from('<f', data, offset + 8 + i * 4)[0])
        if ph.bbox_type == 4 and len(floats) == 8:
            ph._raw_floats = None
            ph.minX = floats[0]; ph.minY = floats[1]
            ph.maxX = floats[4]; ph.maxY = floats[3]
        else:
            ph._raw_floats = floats
            xs = [floats[i] for i in range(0, len(floats), 2)]
            ys = [floats[i] for i in range(1, len(floats), 2)]
            ph.minX = min(xs) if xs else 0.0
            ph.minY = min(ys) if ys else 0.0
            ph.maxX = max(xs) if xs else 0.0
            ph.maxY = max(ys) if ys else 0.0
        return ph

    def __repr__(self):
        extra = f" raw={self.bbox_type}pt" if self._raw_floats else ""
        return (f"Phase(t={self.phase_time:.3f}, "
                f"({self.minX:.0f},{self.minY:.0f})"
                f"->({self.maxX:.0f},{self.maxY:.0f}), "
                f"{self.width:.0f}x{self.height:.0f}{extra})")


# ══════════════════════════════════════
#  Collision Segment (line + 5-byte sep)
# ══════════════════════════════════════

class CollisionSegment:
    """A single collision line segment: (x1,y1) -> (x2,y2)"""
    def __init__(self, x1=0.0, y1=0.0, x2=0.0, y2=0.0):
        self.x1 = float(x1)
        self.y1 = float(y1)
        self.x2 = float(x2)
        self.y2 = float(y2)

    @property
    def length(self):
        dx = self.x2 - self.x1
        dy = self.y2 - self.y1
        return (dx * dx + dy * dy) ** 0.5

    def move(self, dx=0, dy=0):
        self.x1 += dx; self.x2 += dx
        self.y1 += dy; self.y2 += dy

    def scale(self, factor, cx=0, cy=0):
        self.x1 = cx + (self.x1 - cx) * factor
        self.y1 = cy + (self.y1 - cy) * factor
        self.x2 = cx + (self.x2 - cx) * factor
        self.y2 = cy + (self.y2 - cy) * factor

    def to_bytes(self):
        return struct.pack('<4f', self.x1, self.y1, self.x2, self.y2) + b'\x00' * 5

    @staticmethod
    def from_bytes(data, offset=0):
        x1, y1, x2, y2 = struct.unpack_from('<4f', data, offset)
        return CollisionSegment(x1, y1, x2, y2)

    BYTE_SIZE = 21  # 16 floats + 5 separator

    def __repr__(self):
        return f"Seg(({self.x1:.1f},{self.y1:.1f})->({self.x2:.1f},{self.y2:.1f}))"


# ══════════════════════════════════════
#  Collision Phase (time + segments)
# ══════════════════════════════════════

class CollisionPhase:
    """A single MCOL phase: timestamp + list of collision segments"""
    def __init__(self, phase_time=0.0, segments=None):
        self.phase_time = float(phase_time)
        self.segments = segments or []

    @property
    def num_segments(self):
        return len(self.segments)

    @property
    def phase_byte_size(self):
        return 8 + self.num_segments * CollisionSegment.BYTE_SIZE

    def get_bounds(self):
        if not self.segments:
            return (0, 0, 0, 0)
        xs = []
        ys = []
        for s in self.segments:
            xs.extend([s.x1, s.x2])
            ys.extend([s.y1, s.y2])
        return (min(xs), min(ys), max(xs), max(ys))

    def move(self, dx=0, dy=0):
        for s in self.segments:
            s.move(dx, dy)

    def scale(self, factor, cx=None, cy=None):
        if cx is None or cy is None:
            bx1, by1, bx2, by2 = self.get_bounds()
            if cx is None:
                cx = (bx1 + bx2) / 2
            if cy is None:
                cy = (by1 + by2) / 2
        for s in self.segments:
            s.scale(factor, cx, cy)

    def to_bytes(self):
        result = struct.pack('<f', self.phase_time)
        result += struct.pack('<I', self.num_segments)
        for seg in self.segments:
            result += seg.to_bytes()
        return result

    @staticmethod
    def from_bytes(data, offset, max_end):
        if offset + 8 > max_end:
            return None, offset, "phase header overflow"
        phase_time = struct.unpack_from('<f', data, offset)[0]
        num_segs = struct.unpack_from('<I', data, offset + 4)[0]
        if num_segs < 1 or num_segs > 200:
            return None, offset, f"bad num_segments={num_segs}"
        cursor = offset + 8
        segments = []
        for si in range(num_segs):
            if cursor + 16 > max_end:
                return None, cursor, "segment overflow"
            seg = CollisionSegment.from_bytes(data, cursor)
            cursor += 16
            if cursor + 5 > max_end:
                return None, cursor, "separator overflow"
            sep = data[cursor:cursor + 5]
            if sep != b'\x00\x00\x00\x00\x00':
                return None, cursor, f"bad separator at seg {si}"
            cursor += 5
            segments.append(seg)
        phase = CollisionPhase(phase_time, segments)
        return phase, cursor, None

    def __repr__(self):
        return f"ColPhase(t={self.phase_time:.3f}, segs={self.num_segments})"


# ══════════════════════════════════════
#  MCOL Parsed Entry
# ══════════════════════════════════════

class MCOLEntry:
    MAGIC = b'MCOL'

    def __init__(self):
        self.anim_hash = 0
        self.event_hash = 0
        self.start_time = 0.0
        self.end_time = 0.0
        self.element_id = 0
        self.phases = []
        self.ref_count = 0

    @property
    def chunk_type(self):
        return 'MCOL'

    @property
    def duration(self):
        return self.end_time - self.start_time

    @property
    def num_phases(self):
        return len(self.phases)

    @property
    def byte_size(self):
        phase_bytes = sum(ph.phase_byte_size for ph in self.phases)
        return 28 + phase_bytes + 4  # header + phases + ref_count

    def get_bounds(self):
        xs = []
        ys = []
        for ph in self.phases:
            for s in ph.segments:
                xs.extend([s.x1, s.x2])
                ys.extend([s.y1, s.y2])
        if not xs:
            return (0, 0, 0, 0)
        return (min(xs), min(ys), max(xs), max(ys))

    def move(self, dx=0, dy=0):
        for ph in self.phases:
            ph.move(dx, dy)

    def scale(self, factor):
        bx1, by1, bx2, by2 = self.get_bounds()
        cx = (bx1 + bx2) / 2
        cy = (by1 + by2) / 2
        for ph in self.phases:
            ph.scale(factor, cx, cy)

    def to_bytes(self):
        result = b'MCOL'
        result += struct.pack('<I', self.anim_hash)
        result += struct.pack('<I', self.event_hash)
        result += struct.pack('<f', self.start_time)
        result += struct.pack('<f', self.end_time)
        result += struct.pack('<I', self.element_id)
        result += struct.pack('<I', self.num_phases)
        for phase in self.phases:
            result += phase.to_bytes()
        result += struct.pack('<I', self.ref_count)
        return result

    @staticmethod
    def from_bytes(data, offset, size):
        e = MCOLEntry()
        e.anim_hash  = struct.unpack_from('<I', data, offset + 4)[0]
        e.event_hash = struct.unpack_from('<I', data, offset + 8)[0]
        e.start_time = struct.unpack_from('<f', data, offset + 12)[0]
        e.end_time   = struct.unpack_from('<f', data, offset + 16)[0]
        e.element_id = struct.unpack_from('<I', data, offset + 20)[0]
        num_phases   = struct.unpack_from('<I', data, offset + 24)[0]

        max_end = offset + size
        cursor = offset + 28
        for pi in range(num_phases):
            phase, cursor, err = CollisionPhase.from_bytes(data, cursor, max_end)
            if err:
                return None  # parse failed
            e.phases.append(phase)

        # ref_count footer
        if cursor + 4 <= max_end:
            e.ref_count = struct.unpack_from('<I', data, cursor)[0]
        else:
            e.ref_count = 0

        return e

    def __repr__(self):
        segs = set(ph.num_segments for ph in self.phases)
        return (f"MCOL(0x{self.event_hash:08X} "
                f"t={self.start_time:.3f}-{self.end_time:.3f} "
                f"ph={self.num_phases} segs={segs})")


# ══════════════════════════════════════
#  MHIT Parsed Entry
# ══════════════════════════════════════

class MHITEntry:
    MAGIC = b'MHIT'

    def __init__(self):
        self.anim_hash = 0
        self.event_hash = 0
        self.start_time = 0.0
        self.end_time = 0.0
        self.element_id = 0
        self.phases = []
        self.ref_hashes = []
        self._footer_extra = b''

    @property
    def chunk_type(self):
        return 'MHIT'

    @property
    def duration(self):
        return self.end_time - self.start_time

    @property
    def num_phases(self):
        return len(self.phases)

    @property
    def ref_count(self):
        return len(self.ref_hashes)

    @property
    def byte_size(self):
        phase_bytes = sum(ph.phase_byte_size for ph in self.phases)
        return (28 + phase_bytes + 4
                + (len(self.ref_hashes) * 4)
                + len(self._footer_extra))

    def to_bytes(self):
        result = b'MHIT'
        result += struct.pack('<I', self.anim_hash)
        result += struct.pack('<I', self.event_hash)
        result += struct.pack('<f', self.start_time)
        result += struct.pack('<f', self.end_time)
        result += struct.pack('<I', self.element_id)
        result += struct.pack('<I', len(self.phases))
        for phase in self.phases:
            result += phase.to_bytes()
        result += struct.pack('<I', len(self.ref_hashes))
        for rh in self.ref_hashes:
            result += struct.pack('<I', rh)
        if self._footer_extra:
            result += self._footer_extra
        return result

    @staticmethod
    def from_bytes(data, offset, size):
        e = MHITEntry()
        e.anim_hash  = struct.unpack_from('<I', data, offset + 4)[0]
        e.event_hash = struct.unpack_from('<I', data, offset + 8)[0]
        e.start_time = struct.unpack_from('<f', data, offset + 12)[0]
        e.end_time   = struct.unpack_from('<f', data, offset + 16)[0]
        e.element_id = struct.unpack_from('<I', data, offset + 20)[0]
        num_phases   = struct.unpack_from('<I', data, offset + 24)[0]

        phase_cursor = offset + 28
        for p in range(num_phases):
            if phase_cursor + 8 > offset + size:
                break
            bbox_type = struct.unpack_from('<I', data, phase_cursor + 4)[0]
            phase_size = 8 + bbox_type * 8
            if phase_cursor + phase_size > offset + size:
                break
            phase = Phase.from_bytes(data, phase_cursor)
            e.phases.append(phase)
            phase_cursor += phase_size

        footer_off = phase_cursor
        if footer_off + 4 <= offset + size:
            ref_count = struct.unpack_from('<I', data, footer_off)[0]
            for r in range(ref_count):
                rh_off = footer_off + 4 + (r * 4)
                if rh_off + 4 <= offset + size:
                    e.ref_hashes.append(
                        struct.unpack_from('<I', data, rh_off)[0])
            consumed = footer_off + 4 + (ref_count * 4) - offset
            if consumed < size:
                e._footer_extra = bytes(data[offset + consumed:offset + size])

        return e

    def __repr__(self):
        return (f"MHIT(0x{self.event_hash:08X} "
                f"t={self.start_time:.3f}-{self.end_time:.3f} "
                f"ph={self.num_phases} ref={self.ref_count})")


# ══════════════════════════════════════
#  Main CAnimMeta Class
# ══════════════════════════════════════

def _find_chunk_boundaries(data):
    positions = []
    pos = 12
    while pos <= len(data) - 4:
        tag = bytes(data[pos:pos + 4])
        if tag in CHUNK_MAGICS:
            positions.append((pos, tag))
            pos += 4
        else:
            pos += 1
    return positions


class CAnimMeta:
    def __init__(self):
        self.version = 1
        self.anim_hash = 0
        self.entry_count = 0
        self.chunks = []
        self._filepath = None
        self._trailing_bytes = b''

    def load(self, filepath):
        self._filepath = filepath
        with open(filepath, 'rb') as f:
            data = bytearray(f.read())

        if len(data) < 12:
            self.version = struct.unpack_from('<I', data, 0)[0] if len(data) >= 4 else 0
            self.anim_hash = struct.unpack_from('<I', data, 4)[0] if len(data) >= 8 else 0
            self.entry_count = 0
            self.chunks = []
            self._trailing_bytes = b''
            return self

        self.version    = struct.unpack_from('<I', data, 0)[0]
        self.anim_hash  = struct.unpack_from('<I', data, 4)[0]
        self.entry_count = struct.unpack_from('<I', data, 8)[0]

        chunk_positions = _find_chunk_boundaries(data)
        self.chunks = []

        for i, (cpos, cmagic) in enumerate(chunk_positions):
            if i + 1 < len(chunk_positions):
                csize = chunk_positions[i + 1][0] - cpos
            else:
                csize = len(data) - cpos

            raw_data = bytes(data[cpos:cpos + csize])

            if cmagic == b'MHIT':
                try:
                    entry = MHITEntry.from_bytes(data, cpos, csize)
                    if entry.to_bytes() == raw_data:
                        self.chunks.append(entry)
                    else:
                        self.chunks.append(RawChunk(cmagic, raw_data))
                except:
                    self.chunks.append(RawChunk(cmagic, raw_data))
            elif cmagic == b'MCOL':
                try:
                    entry = MCOLEntry.from_bytes(data, cpos, csize)
                    if entry is not None and entry.to_bytes() == raw_data:
                        self.chunks.append(entry)
                    else:
                        self.chunks.append(RawChunk(cmagic, raw_data))
                except:
                    self.chunks.append(RawChunk(cmagic, raw_data))
            else:
                self.chunks.append(RawChunk(cmagic, raw_data))

        if chunk_positions:
            last_pos, _ = chunk_positions[-1]
            last_size = len(data) - last_pos
            data_end = last_pos + last_size
        else:
            data_end = 12

        if data_end < len(data):
            self._trailing_bytes = bytes(data[data_end:])
        else:
            self._trailing_bytes = b''

        return self

    def save(self, filepath=None):
        if filepath is None:
            filepath = self._filepath

        if os.path.exists(filepath):
            backup = filepath + '.bak'
            if not os.path.exists(backup):
                shutil.copy2(filepath, backup)
                print(f"  Backup: {backup}")

        result = struct.pack('<I', self.version)
        result += struct.pack('<I', self.anim_hash)
        result += struct.pack('<I', len(self.chunks))
        for chunk in self.chunks:
            result += chunk.to_bytes()
        if self._trailing_bytes:
            result += self._trailing_bytes

        with open(filepath, 'wb') as f:
            f.write(result)
        print(f"  Saved: {filepath} ({len(result)} bytes)")
        return len(result)

    def get_mhit_entries(self):
        return [c for c in self.chunks if isinstance(c, MHITEntry)]

    def get_mcol_entries(self):
        return [c for c in self.chunks if isinstance(c, MCOLEntry)]

    def get_raw_chunks(self, ctype=None):
        if ctype:
            return [c for c in self.chunks
                    if isinstance(c, RawChunk) and c.chunk_type == ctype]
        return [c for c in self.chunks if isinstance(c, RawChunk)]

    def display(self):
        print(f"\n{'='*65}")
        print(f"  Version: {self.version}  |  Hash: 0x{self.anim_hash:08X}"
              f"  |  Chunks: {len(self.chunks)} (header says {self.entry_count})")

        type_counts = {}
        for c in self.chunks:
            t = c.chunk_type
            type_counts[t] = type_counts.get(t, 0) + 1
        parts = [f"{t}={n}" for t, n in sorted(type_counts.items())]
        print(f"  Types: {' '.join(parts)}")

        parsed = sum(1 for c in self.chunks
                     if isinstance(c, (MHITEntry, MCOLEntry)))
        raw = sum(1 for c in self.chunks if isinstance(c, RawChunk))
        print(f"  Parsed: {parsed} (MHIT+MCOL)  |  Raw blobs: {raw}")

        if self._trailing_bytes:
            print(f"  Trailing: {len(self._trailing_bytes)} bytes")
        print(f"{'='*65}")

        for i, c in enumerate(self.chunks):
            ct = c.chunk_type

            if isinstance(c, MHITEntry):
                e = c
                ct_color = Colors.G
                bbox_info = ""
                for ph in e.phases:
                    if ph.bbox_type != 4:
                        bbox_info = f"  {Colors.Y}[bbox={ph.bbox_type}]{Colors.E}"
                        break
                print(f"\n  [{i+1:>2}] {ct_color}{ct}{Colors.E}"
                      f"  Event:0x{e.event_hash:08X}"
                      f"  Time:{e.start_time:.3f}->{e.end_time:.3f}"
                      f"  ({e.duration:.3f}s)"
                      f"  ID:{e.element_id}"
                      f"  [{e.byte_size}B] PARSED{bbox_info}")
                for pi, ph in enumerate(e.phases):
                    bt_tag = f" [{ph.bbox_type}pt]" if ph.bbox_type != 4 else ""
                    print(f"       Phase{pi+1}: t={ph.phase_time:.3f}"
                          f"  ({ph.minX:.0f},{ph.minY:.0f})"
                          f"->({ph.maxX:.0f},{ph.maxY:.0f})"
                          f"  [{ph.width:.0f}x{ph.height:.0f}]{bt_tag}")
                if e.ref_hashes:
                    for rh in e.ref_hashes:
                        print(f"       Ref: 0x{rh:08X}")
                if e._footer_extra:
                    print(f"       Footer extra: {len(e._footer_extra)}B"
                          f" [{e._footer_extra.hex()}]")

            elif isinstance(c, MCOLEntry):
                e = c
                seg_counts = set(ph.num_segments for ph in e.phases)
                bx1, by1, bx2, by2 = e.get_bounds()
                print(f"\n  [{i+1:>2}] {Colors.C}MCOL{Colors.E}"
                      f"  Event:0x{e.event_hash:08X}"
                      f"  Time:{e.start_time:.3f}->{e.end_time:.3f}"
                      f"  ({e.duration:.3f}s)"
                      f"  ID:{e.element_id}"
                      f"  [{e.byte_size}B] PARSED")
                print(f"       Phases:{e.num_phases}"
                      f"  Segs/phase:{seg_counts}"
                      f"  Bounds:({bx1:.0f},{by1:.0f})->({bx2:.0f},{by2:.0f})"
                      f"  Ref:{e.ref_count}")

            else:
                ct_color = Colors.Y if ct == 'MACT' else Colors.C
                print(f"\n  [{i+1:>2}] {ct_color}{ct}{Colors.E}"
                      f"  Event:0x{c.event_hash:08X}"
                      f"  Time:{c.start_time:.3f}->{c.end_time:.3f}"
                      f"  [{c.byte_size}B] RAW")
                if ct == 'MACT' and c.byte_size > 26:
                    lua_start = 26
                    lua = c.raw[lua_start:]
                    try:
                        txt = lua.decode('ascii', errors='replace')
                        preview = txt[:80].replace('\r\n', '\\n').replace('\n', '\\n')
                        print(f"       Lua({len(lua)}B): \"{preview}...\"")
                    except:
                        print(f"       Lua({len(lua)}B): <binary>")

        total = 12 + sum(c.byte_size for c in self.chunks) + len(self._trailing_bytes)
        print(f"\n  Total: {total} bytes")
        print(f"{'='*65}\n")


# ══════════════════════════════════════
#  Detailed View with Boxes
# ══════════════════════════════════════

def draw_mini_bbox(phase):
    w = phase.width; h = phase.height
    scale = min(30 / max(abs(w), 1), 15 / max(abs(h), 1))
    dw = max(int(abs(w) * scale), 4)
    dh = max(int(abs(h) * scale / 2), 2)
    print(f"    +{'─'*dw}+  ({phase.minX:.0f},{phase.maxY:.0f})")
    for row in range(dh - 1):
        if row == dh // 2 - 1:
            label = f"{w:.0f}x{h:.0f}"
            pad = dw - len(label)
            left = pad // 2; right = pad - left
            print(f"    |{' '*left}{label}{' '*right}|")
        else:
            print(f"    |{' '*dw}|")
    print(f"    +{'─'*dw}+  ({phase.maxX:.0f},{phase.minY:.0f})")


def draw_collision_ascii(phase):
    """Draw a simple ASCII representation of collision segments"""
    bounds = phase.get_bounds()
    bx1, by1, bx2, by2 = bounds
    w = bx2 - bx1
    h = by2 - by1
    if w == 0 or h == 0:
        print(f"    (degenerate bounds)")
        return
    cols = 50
    rows = 15
    grid = [[' '] * cols for _ in range(rows)]
    for seg in phase.segments:
        # Draw line from (x1,y1) to (x2,y2) on grid
        steps = max(int(seg.length / max(w, h) * cols), 2)
        for t in range(steps + 1):
            frac = t / max(steps, 1)
            x = seg.x1 + (seg.x2 - seg.x1) * frac
            y = seg.y1 + (seg.y2 - seg.y1) * frac
            gc = int((x - bx1) / w * (cols - 1))
            gr = int((1 - (y - by1) / h) * (rows - 1))
            gc = max(0, min(cols - 1, gc))
            gr = max(0, min(rows - 1, gr))
            grid[gr][gc] = '█'
    print(f"    ┌{'─'*cols}┐ ({bx2:.0f},{by2:.0f})")
    for row in grid:
        print(f"    │{''.join(row)}│")
    print(f"    └{'─'*cols}┘ ({bx1:.0f},{by1:.0f})")


def detailed_view(meta):
    print(f"\n{'='*70}")
    print(f"{Colors.BOLD}{Colors.H}")
    print(f"  ╔════════════════════════════════════════════════╗")
    print(f"  ║  Shank 2 CANIM-META Detailed View  v7         ║")
    print(f"  ╚════════════════════════════════════════════════╝")
    print(f"{Colors.E}")

    print(f"{Colors.BOLD}[FILE HEADER]{Colors.E}")
    print(f"  Version:     {meta.version}")
    print(f"  Anim Hash:   {Colors.Y}0x{meta.anim_hash:08X}{Colors.E}")
    print(f"  Entry Count: {Colors.G}{len(meta.chunks)}{Colors.E}"
          f" (header: {meta.entry_count})")

    type_counts = {}
    for c in meta.chunks:
        t = c.chunk_type
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"  Types:       {type_counts}")

    total = 12 + sum(c.byte_size for c in meta.chunks) + len(meta._trailing_bytes)
    print(f"  File Size:   {total} bytes")

    if meta._trailing_bytes:
        print(f"  Trailing:    {len(meta._trailing_bytes)} bytes "
              f"{Colors.G}preserved{Colors.E}")

    for i, c in enumerate(meta.chunks):
        print(f"\n{'─'*70}")
        ct = c.chunk_type

        if isinstance(c, MHITEntry):
            e = c
            print(f"  {Colors.BOLD}{Colors.G}[MHIT]{Colors.E}"
                  f"  ENTRY {i+1}/{len(meta.chunks)}"
                  f"  {e.byte_size}B  PARSED")
            print(f"{'─'*70}")
            print(f"  Event Hash:  {Colors.Y}0x{e.event_hash:08X}{Colors.E}")
            print(f"  Start:       {Colors.C}{e.start_time:.6f}{Colors.E}")
            print(f"  End:         {Colors.C}{e.end_time:.6f}{Colors.E}")
            print(f"  Duration:    {e.duration:.6f}")
            print(f"  Element ID:  {e.element_id}")

            for pi, ph in enumerate(e.phases):
                color = Colors.G if pi == 0 else Colors.B
                print(f"\n  {color}Phase {pi+1}:{Colors.E}")
                print(f"    Time:  {ph.phase_time:.6f}")
                print(f"    Type:  {ph.bbox_type}"
                      f"  ({ph.bbox_type} points, {ph.phase_byte_size}B)")
                print(f"    BBox:  ({ph.minX:.0f},{ph.minY:.0f})"
                      f" -> ({ph.maxX:.0f},{ph.maxY:.0f})")
                print(f"    Size:  {ph.width:.0f} x {ph.height:.0f}")
                if ph._raw_floats is not None:
                    print(f"    Points ({ph.bbox_type}):")
                    for fi in range(0, len(ph._raw_floats), 2):
                        x = ph._raw_floats[fi]
                        y = ph._raw_floats[fi + 1] if fi + 1 < len(ph._raw_floats) else 0.0
                        print(f"      P{fi//2}: ({x:.2f}, {y:.2f})")
                draw_mini_bbox(ph)

            if e.ref_hashes:
                print(f"\n  Refs ({e.ref_count}):")
                for rh in e.ref_hashes:
                    print(f"    -> {Colors.Y}0x{rh:08X}{Colors.E}")

            if e._footer_extra:
                print(f"\n  Footer extra: {len(e._footer_extra)}B"
                      f" [{e._footer_extra.hex()}]")

        elif isinstance(c, MCOLEntry):
            e = c
            bx1, by1, bx2, by2 = e.get_bounds()
            print(f"  {Colors.BOLD}{Colors.C}[MCOL]{Colors.E}"
                  f"  ENTRY {i+1}/{len(meta.chunks)}"
                  f"  {e.byte_size}B  PARSED")
            print(f"{'─'*70}")
            print(f"  Anim Hash:   {Colors.Y}0x{e.anim_hash:08X}{Colors.E}")
            print(f"  Event Hash:  {Colors.Y}0x{e.event_hash:08X}{Colors.E}")
            print(f"  Start:       {Colors.C}{e.start_time:.6f}{Colors.E}")
            print(f"  End:         {Colors.C}{e.end_time:.6f}{Colors.E}")
            print(f"  Duration:    {e.duration:.6f}")
            print(f"  Element ID:  {e.element_id}")
            print(f"  Ref Count:   {e.ref_count}")
            print(f"  Bounds:      ({bx1:.1f},{by1:.1f})"
                  f" -> ({bx2:.1f},{by2:.1f})")
            print(f"  Phases:      {e.num_phases}")

            for pi, ph in enumerate(e.phases):
                color = Colors.G if pi == 0 else Colors.B
                pb = ph.get_bounds()
                print(f"\n  {color}Phase {pi+1}:{Colors.E}"
                      f"  t={ph.phase_time:.4f}"
                      f"  segs={ph.num_segments}"
                      f"  bounds=({pb[0]:.0f},{pb[1]:.0f})"
                      f"->({pb[2]:.0f},{pb[3]:.0f})")
                for si, seg in enumerate(ph.segments):
                    print(f"    Seg{si+1}: ({seg.x1:.1f},{seg.y1:.1f})"
                          f" -> ({seg.x2:.1f},{seg.y2:.1f})"
                          f"  len={seg.length:.1f}")

            # Draw first and last phase
            if e.phases:
                print(f"\n  {Colors.G}Phase 1 visualization:{Colors.E}")
                draw_collision_ascii(e.phases[0])
                if len(e.phases) > 1:
                    print(f"\n  {Colors.B}Phase {len(e.phases)} visualization:{Colors.E}")
                    draw_collision_ascii(e.phases[-1])

        else:
            ct_color = Colors.Y if ct == 'MACT' else Colors.C
            print(f"  {Colors.BOLD}{ct_color}[{ct}]{Colors.E}"
                  f"  ENTRY {i+1}/{len(meta.chunks)}"
                  f"  {c.byte_size}B  RAW BLOB")
            print(f"{'─'*70}")
            print(f"  Event Hash:  {Colors.Y}0x{c.event_hash:08X}{Colors.E}")
            print(f"  Start:       {Colors.C}{c.start_time:.6f}{Colors.E}")
            print(f"  End:         {Colors.C}{c.end_time:.6f}{Colors.E}")

            if ct == 'MACT' and c.byte_size > 26:
                elem = struct.unpack_from('<I', c.raw, 20)[0]
                u16v = struct.unpack_from('<H', c.raw, 24)[0]
                print(f"  Element ID:  {elem}")
                print(f"  Field @24:   {u16v}")
                lua = c.raw[26:]
                try:
                    txt = lua.decode('ascii', errors='replace')
                    lines = txt.split('\n')
                    print(f"  Lua Script ({len(lua)}B):")
                    for ln in lines[:20]:
                        print(f"    {Colors.B}{ln.rstrip()}{Colors.E}")
                    if len(lines) > 20:
                        print(f"    ... ({len(lines)-20} more lines)")
                except:
                    print(f"  Lua: <binary {len(lua)}B>")

            elif ct == 'MCOL':
                if c.byte_size >= 28:
                    elem = struct.unpack_from('<I', c.raw, 20)[0]
                    nph = struct.unpack_from('<I', c.raw, 24)[0]
                    print(f"  Element ID:  {elem}")
                    print(f"  Num Phases:  {nph}")
                    print(f"  (parse failed - stored as raw)")

            show = min(64, c.byte_size)
            print(f"  Hex ({show}B):")
            for off in range(0, show, 16):
                chunk = c.raw[off:off+16]
                h = ' '.join(f'{b:02X}' for b in chunk)
                a = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                print(f"    {off:04X}: {h:<48} {a}")

    print(f"\n{'='*70}")
    print(f"{Colors.BOLD}  SUMMARY{Colors.E}")
    print(f"{'='*70}")

    unique_events = set()
    for c in meta.chunks:
        if hasattr(c, 'event_hash'):
            unique_events.add(c.event_hash)
    print(f"  Unique events: {len(unique_events)}")

    bbox_types = {}
    for c in meta.chunks:
        if isinstance(c, MHITEntry):
            for ph in c.phases:
                bt = ph.bbox_type
                bbox_types[bt] = bbox_types.get(bt, 0) + 1
    if bbox_types:
        parts = [f"type{k}={v}" for k, v in sorted(bbox_types.items())]
        print(f"  BBox types:    {' '.join(parts)}")

    mcol_count = sum(1 for c in meta.chunks if isinstance(c, MCOLEntry))
    if mcol_count:
        total_segs = sum(
            sum(ph.num_segments for ph in c.phases)
            for c in meta.chunks if isinstance(c, MCOLEntry))
        total_phases = sum(c.num_phases for c in meta.chunks
                          if isinstance(c, MCOLEntry))
        print(f"  MCOL parsed:   {mcol_count} entries,"
              f" {total_phases} phases, {total_segs} segments")

    print(f"\n{'='*70}\n")


# ══════════════════════════════════════
#  Verify (byte-perfect check)
# ══════════════════════════════════════

def _rebuild_bytes(meta):
    rebuilt = struct.pack('<I', meta.version)
    rebuilt += struct.pack('<I', meta.anim_hash)
    rebuilt += struct.pack('<I', len(meta.chunks))
    for chunk in meta.chunks:
        rebuilt += chunk.to_bytes()
    if meta._trailing_bytes:
        rebuilt += meta._trailing_bytes
    return rebuilt


def verify_roundtrip(meta, original_path):
    with open(original_path, 'rb') as f:
        original = f.read()
    rebuilt = _rebuild_bytes(meta)
    if rebuilt == original:
        print(f"  {Colors.G}[VERIFY] PERFECT MATCH! {len(rebuilt)} bytes{Colors.E}")
        return True
    else:
        print(f"  {Colors.R}[VERIFY] MISMATCH!{Colors.E}")
        print(f"    Original: {len(original)} bytes")
        print(f"    Rebuilt:  {len(rebuilt)} bytes")
        min_len = min(len(original), len(rebuilt))
        first_diff = -1
        for i in range(min_len):
            if original[i] != rebuilt[i]:
                first_diff = i; break
        if first_diff >= 0:
            print(f"    First diff at: 0x{first_diff:04X}")
            s = max(0, first_diff - 4)
            e = min(min_len, first_diff + 16)
            print(f"    Orig: {original[s:e].hex()}")
            print(f"    Rebu: {rebuilt[s:e].hex()}")
        return False


def verify_silent(meta, original_path):
    with open(original_path, 'rb') as f:
        original = f.read()
    return _rebuild_bytes(meta) == original


# ══════════════════════════════════════
#  JSON Export / Import
# ══════════════════════════════════════

def export_json(meta, filepath):
    data = {
        'version': meta.version,
        'anim_hash': f"0x{meta.anim_hash:08X}",
        '_trailing_hex': meta._trailing_bytes.hex() if meta._trailing_bytes else "",
        'chunks': []
    }
    for c in meta.chunks:
        if isinstance(c, MHITEntry):
            cd = {
                'type': 'MHIT', 'parsed': True,
                'event_hash': f"0x{c.event_hash:08X}",
                'start_time': c.start_time, 'end_time': c.end_time,
                'element_id': c.element_id,
                'phases': [],
                'ref_hashes': [f"0x{rh:08X}" for rh in c.ref_hashes],
                '_footer_extra_hex': c._footer_extra.hex() if c._footer_extra else ""
            }
            for ph in c.phases:
                pd = {
                    'phase_time': ph.phase_time,
                    'bbox_type': ph.bbox_type,
                    'minX': ph.minX, 'minY': ph.minY,
                    'maxX': ph.maxX, 'maxY': ph.maxY
                }
                if ph._raw_floats is not None:
                    pd['raw_floats'] = ph._raw_floats
                cd['phases'].append(pd)

        elif isinstance(c, MCOLEntry):
            cd = {
                'type': 'MCOL', 'parsed': True,
                'anim_hash': f"0x{c.anim_hash:08X}",
                'event_hash': f"0x{c.event_hash:08X}",
                'start_time': c.start_time, 'end_time': c.end_time,
                'element_id': c.element_id,
                'ref_count': c.ref_count,
                'phases': []
            }
            for ph in c.phases:
                phd = {
                    'phase_time': ph.phase_time,
                    'segments': []
                }
                for seg in ph.segments:
                    phd['segments'].append({
                        'x1': seg.x1, 'y1': seg.y1,
                        'x2': seg.x2, 'y2': seg.y2
                    })
                cd['phases'].append(phd)

        else:
            cd = {
                'type': c.chunk_type, 'parsed': False,
                'event_hash': f"0x{c.event_hash:08X}",
                'start_time': c.start_time, 'end_time': c.end_time,
                'raw_hex': c.raw.hex(),
                'size': c.byte_size
            }
        data['chunks'].append(cd)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Exported: {filepath}")


def import_json(meta, filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    meta.version = data['version']
    meta.anim_hash = int(data['anim_hash'], 16)
    t = data.get('_trailing_hex', '')
    meta._trailing_bytes = bytes.fromhex(t) if t else b''

    meta.chunks = []
    for cd in data['chunks']:
        if cd.get('parsed') and cd['type'] == 'MHIT':
            e = MHITEntry()
            e.anim_hash = meta.anim_hash
            e.event_hash = int(cd['event_hash'], 16)
            e.start_time = cd['start_time']
            e.end_time = cd['end_time']
            e.element_id = cd['element_id']
            e.ref_hashes = [int(rh, 16) for rh in cd.get('ref_hashes', [])]
            fe = cd.get('_footer_extra_hex', '')
            e._footer_extra = bytes.fromhex(fe) if fe else b''
            for pd in cd['phases']:
                raw_f = pd.get('raw_floats', None)
                ph = Phase(
                    pd['phase_time'], pd.get('bbox_type', 4),
                    pd['minX'], pd['minY'], pd['maxX'], pd['maxY'],
                    raw_floats=raw_f
                )
                e.phases.append(ph)
            meta.chunks.append(e)

        elif cd.get('parsed') and cd['type'] == 'MCOL':
            e = MCOLEntry()
            e.anim_hash = int(cd.get('anim_hash', '0x0'), 16)
            e.event_hash = int(cd['event_hash'], 16)
            e.start_time = cd['start_time']
            e.end_time = cd['end_time']
            e.element_id = cd['element_id']
            e.ref_count = cd.get('ref_count', 0)
            for phd in cd['phases']:
                segs = []
                for sd in phd['segments']:
                    segs.append(CollisionSegment(
                        sd['x1'], sd['y1'], sd['x2'], sd['y2']))
                e.phases.append(CollisionPhase(phd['phase_time'], segs))
            meta.chunks.append(e)

        else:
            raw = bytes.fromhex(cd['raw_hex'])
            magic = raw[:4]
            meta.chunks.append(RawChunk(magic, raw))

    meta.entry_count = len(meta.chunks)
    print(f"  Imported: {len(meta.chunks)} chunks from {filepath}")


# ══════════════════════════════════════
#  Batch Analysis
# ══════════════════════════════════════

def batch_analyze(folder):
    files = sorted(f for f in os.listdir(folder)
                   if f.endswith('.canim-meta'))
    if not files:
        print(f"  {Colors.R}No .canim-meta files found in {folder}{Colors.E}")
        return

    print(f"\n  {Colors.BOLD}Found {len(files)} .canim-meta files in {folder}{Colors.E}\n")

    results = []
    t0 = _time.time()

    for fn in files:
        fp = os.path.join(folder, fn)
        try:
            fsize = os.path.getsize(fp)
            if fsize < 12:
                results.append({
                    'fn': fn, 'size': fsize, 'ok': True,
                    'chunks': 0, 'mhit': 0, 'mcol': 0, 'mact': 0,
                    'parsed': 0, 'trailing': 0, 'skipped': True
                })
                continue

            meta = CAnimMeta()
            meta.load(fp)
            ok = verify_silent(meta, fp)

            tc = {}
            parsed = 0
            bbox_types = set()
            for c in meta.chunks:
                t_name = c.chunk_type
                tc[t_name] = tc.get(t_name, 0) + 1
                if isinstance(c, (MHITEntry, MCOLEntry)):
                    parsed += 1
                if isinstance(c, MHITEntry):
                    for ph in c.phases:
                        bbox_types.add(ph.bbox_type)

            timed = [c for c in meta.chunks if hasattr(c, 'start_time')]
            if timed:
                min_t = min(c.start_time for c in timed)
                max_t = max(c.end_time for c in timed)
            else:
                min_t = max_t = 0.0

            results.append({
                'fn': fn, 'size': fsize, 'ok': ok,
                'chunks': len(meta.chunks),
                'mhit': tc.get('MHIT', 0),
                'mcol': tc.get('MCOL', 0),
                'mact': tc.get('MACT', 0),
                'parsed': parsed,
                'min_t': min_t, 'max_t': max_t,
                'trailing': len(meta._trailing_bytes),
                'bbox_types': bbox_types
            })
        except Exception as ex:
            results.append({
                'fn': fn, 'size': os.path.getsize(fp),
                'ok': False, 'error': str(ex)
            })

    elapsed = _time.time() - t0

    print(f"\n{Colors.BOLD}{Colors.H}")
    print(f"╔═══════════════════════════════════════════════════════════════════╗")
    print(f"║                  CANIM-META BATCH REPORT  v7                     ║")
    print(f"╚═══════════════════════════════════════════════════════════════════╝{Colors.E}")

    ok_c = sum(1 for r in results if r.get('ok') and not r.get('skipped'))
    skip_c = sum(1 for r in results if r.get('skipped'))
    err_c = sum(1 for r in results if 'error' in r)
    warn_c = sum(1 for r in results
                 if not r.get('ok') and 'error' not in r and not r.get('skipped'))

    total_chunks = sum(r.get('chunks', 0) for r in results if 'error' not in r)
    total_mhit = sum(r.get('mhit', 0) for r in results if 'error' not in r)
    total_mcol = sum(r.get('mcol', 0) for r in results if 'error' not in r)
    total_mact = sum(r.get('mact', 0) for r in results if 'error' not in r)
    total_parsed = sum(r.get('parsed', 0) for r in results if 'error' not in r)

    all_bbox = set()
    for r in results:
        if 'bbox_types' in r:
            all_bbox |= r['bbox_types']

    print(f"\n{Colors.BOLD}  FILES: {len(results)}{Colors.E}  "
          f"{Colors.G}✓{ok_c}{Colors.E}  "
          f"{Colors.Y}⚠{warn_c}{Colors.E}  "
          f"{Colors.R}✗{err_c}{Colors.E}"
          f"{'  ⊘'+str(skip_c) if skip_c else ''}")
    print(f"  Chunks: {total_chunks}"
          f" (MHIT={total_mhit} MCOL={total_mcol} MACT={total_mact})"
          f"  Parsed: {total_parsed}")
    if all_bbox:
        print(f"  BBox types seen: {sorted(all_bbox)}")
    print(f"  Completed in {elapsed:.2f}s")

    print(f"\n  {'FILE':<40} {'SIZE':>6} {'CHK':>4}"
          f" {'HIT':>3} {'COL':>3} {'ACT':>3}"
          f" {'TIME RANGE':>16} STATUS")
    print(f"  {'─'*40} {'─'*6} {'─'*4}"
          f" {'─'*3} {'─'*3} {'─'*3}"
          f" {'─'*16} {'─'*10}")

    for r in results:
        fn = r['fn']
        if 'error' in r:
            print(f"  {fn:<40} {r['size']:>6} "
                  f"{Colors.R}ERROR: {r['error']}{Colors.E}")
            continue
        if r.get('skipped'):
            print(f"  {fn:<40} {r['size']:>6} "
                  f"{'—':>4} {'—':>3} {'—':>3} {'—':>3} {'—':>16} "
                  f"{Colors.Y}⊘ SKIP ({r['size']}B){Colors.E}")
            continue

        tr = (f"{r['min_t']:.2f}-{r['max_t']:.2f}"
              if r['chunks'] > 0 else "—")
        st = (f"{Colors.G}✓{Colors.E}" if r['ok']
              else f"{Colors.Y}⚠ MISMATCH{Colors.E}")
        trail = f" t={r['trailing']}" if r.get('trailing', 0) else ""
        bt_info = ""
        if r.get('bbox_types') and r['bbox_types'] != {4}:
            bt_info = f" bt={sorted(r['bbox_types'])}"

        print(f"  {fn:<40} {r['size']:>6} {r['chunks']:>4}"
              f" {r.get('mhit',0):>3} {r.get('mcol',0):>3} {r.get('mact',0):>3}"
              f" {tr:>16} {st}{trail}{bt_info}")

    problems = [r for r in results
                if not r.get('ok') and 'error' not in r and not r.get('skipped')]
    if problems:
        print(f"\n{Colors.Y}  MISMATCHES:{Colors.E}")
        for r in problems:
            print(f"    {r['fn']}")

    print(f"\n{'='*70}\n")


# ══════════════════════════════════════
#  Edit Commands
# ══════════════════════════════════════

def _get_mhit(meta, idx):
    c = meta.chunks[idx]
    if not isinstance(c, MHITEntry):
        print(f"  Entry {idx+1} is {c.chunk_type} (not editable MHIT)")
        return None
    return c


def _get_mcol(meta, idx):
    c = meta.chunks[idx]
    if not isinstance(c, MCOLEntry):
        print(f"  Entry {idx+1} is {c.chunk_type} (not editable MCOL)")
        return None
    return c


def cmd_view(meta, args):
    meta.display()

def cmd_detail(meta, args):
    detailed_view(meta)

def cmd_verify(meta, args):
    if meta._filepath and os.path.exists(meta._filepath + '.bak'):
        verify_roundtrip(meta, meta._filepath + '.bak')
    elif meta._filepath:
        verify_roundtrip(meta, meta._filepath)

def cmd_time(meta, args):
    idx = int(args[0]) - 1
    c = meta.chunks[idx]
    if isinstance(c, MHITEntry):
        old_s, old_e = c.start_time, c.end_time
        c.start_time = float(args[1])
        c.end_time = float(args[2])
        print(f"  MHIT {idx+1}: {old_s:.3f}-{old_e:.3f}"
              f" => {c.start_time:.3f}-{c.end_time:.3f}")
    elif isinstance(c, MCOLEntry):
        old_s, old_e = c.start_time, c.end_time
        c.start_time = float(args[1])
        c.end_time = float(args[2])
        print(f"  MCOL {idx+1}: {old_s:.3f}-{old_e:.3f}"
              f" => {c.start_time:.3f}-{c.end_time:.3f}")
    else:
        print(f"  Entry {idx+1} is raw {c.chunk_type}, not editable")

def cmd_bbox(meta, args):
    idx = int(args[0]) - 1; pi = int(args[1]) - 1
    e = _get_mhit(meta, idx)
    if not e: return
    ph = e.phases[pi]
    old = f"({ph.minX:.0f},{ph.minY:.0f})->({ph.maxX:.0f},{ph.maxY:.0f})"
    ph.minX = float(args[2]); ph.minY = float(args[3])
    ph.maxX = float(args[4]); ph.maxY = float(args[5])
    if ph._raw_floats is not None:
        ph._raw_floats = None
        ph.bbox_type = 4
    new = f"({ph.minX:.0f},{ph.minY:.0f})->({ph.maxX:.0f},{ph.maxY:.0f})"
    print(f"  Entry {idx+1} Phase {pi+1}: {old} => {new}")

def cmd_scale(meta, args):
    idx = int(args[0]) - 1; factor = float(args[1])
    c = meta.chunks[idx]
    if isinstance(c, MHITEntry):
        for pi, ph in enumerate(c.phases):
            old_w, old_h = ph.width, ph.height
            ph.scale(factor)
            print(f"  MHIT {idx+1} Phase {pi+1}: "
                  f"{old_w:.0f}x{old_h:.0f} -> {ph.width:.0f}x{ph.height:.0f}")
    elif isinstance(c, MCOLEntry):
        bx1, by1, bx2, by2 = c.get_bounds()
        c.scale(factor)
        nbx1, nby1, nbx2, nby2 = c.get_bounds()
        print(f"  MCOL {idx+1}: bounds ({bx1:.0f},{by1:.0f})->({bx2:.0f},{by2:.0f})"
              f" => ({nbx1:.0f},{nby1:.0f})->({nbx2:.0f},{nby2:.0f})")
    else:
        print(f"  Entry {idx+1} is raw {c.chunk_type}, not editable")

def cmd_move(meta, args):
    idx = int(args[0]) - 1
    dx = float(args[1]); dy = float(args[2])
    c = meta.chunks[idx]
    if isinstance(c, MHITEntry):
        for pi, ph in enumerate(c.phases):
            ph.move(dx, dy)
            print(f"  MHIT {idx+1} Phase {pi+1}: moved ({dx:+.0f},{dy:+.0f})")
    elif isinstance(c, MCOLEntry):
        c.move(dx, dy)
        print(f"  MCOL {idx+1}: moved ({dx:+.0f},{dy:+.0f})")
    else:
        print(f"  Entry {idx+1} is raw {c.chunk_type}, not editable")

def cmd_dup(meta, args):
    idx = int(args[0]) - 1
    c = meta.chunks[idx]
    if isinstance(c, MHITEntry):
        new_e = MHITEntry()
        new_e.anim_hash = c.anim_hash
        new_e.event_hash = c.event_hash
        new_e.start_time = c.start_time
        new_e.end_time = c.end_time
        new_e.element_id = c.element_id
        new_e.ref_hashes = list(c.ref_hashes)
        new_e._footer_extra = c._footer_extra
        for ph in c.phases:
            new_ph = Phase(
                ph.phase_time, ph.bbox_type,
                ph.minX, ph.minY, ph.maxX, ph.maxY,
                raw_floats=list(ph._raw_floats) if ph._raw_floats else None
            )
            new_e.phases.append(new_ph)
        meta.chunks.append(new_e)
    elif isinstance(c, MCOLEntry):
        new_e = MCOLEntry()
        new_e.anim_hash = c.anim_hash
        new_e.event_hash = c.event_hash
        new_e.start_time = c.start_time
        new_e.end_time = c.end_time
        new_e.element_id = c.element_id
        new_e.ref_count = c.ref_count
        for ph in c.phases:
            new_segs = [CollisionSegment(s.x1, s.y1, s.x2, s.y2)
                        for s in ph.segments]
            new_e.phases.append(CollisionPhase(ph.phase_time, new_segs))
        meta.chunks.append(new_e)
    else:
        meta.chunks.append(RawChunk(c.magic, c.raw))
    print(f"  Duplicated entry {idx+1} -> {len(meta.chunks)}")

def cmd_del(meta, args):
    idx = int(args[0]) - 1
    removed = meta.chunks.pop(idx)
    print(f"  Deleted entry {idx+1} ({removed.chunk_type})")

def cmd_save(meta, args):
    path = args[0] if args else None
    meta.save(path)

def cmd_export(meta, args):
    path = (args[0] if args
            else meta._filepath.replace('.canim-meta', '.json'))
    export_json(meta, path)

def cmd_import(meta, args):
    import_json(meta, args[0])


COMMANDS = {
    'view':   (cmd_view,    'Quick view'),
    'detail': (cmd_detail,  'Detailed view with collision viz'),
    'verify': (cmd_verify,  'Verify byte-perfect roundtrip'),
    'time':   (cmd_time,    'time <entry> <start> <end>'),
    'bbox':   (cmd_bbox,    'bbox <entry> <phase> <x1> <y1> <x2> <y2>'),
    'scale':  (cmd_scale,   'scale <entry> <factor>'),
    'move':   (cmd_move,    'move <entry> <dx> <dy>'),
    'dup':    (cmd_dup,     'dup <entry>'),
    'del':    (cmd_del,     'del <entry>'),
    'save':   (cmd_save,    'save [filepath]'),
    'export': (cmd_export,  'export [filepath.json]'),
    'import': (cmd_import,  'import <filepath.json>'),
}

def interactive_mode(meta):
    meta.display()
    print("  Commands: " + ", ".join(COMMANDS.keys()) + ", help, quit")
    while True:
        try:
            line = input("  canim-meta> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not line: continue
        parts = line.split()
        cmd = parts[0].lower(); args = parts[1:]
        if cmd in ('quit', 'exit', 'q'): break
        elif cmd == 'help':
            for n, (f, d) in COMMANDS.items():
                print(f"    {n:<12} {d}")
        elif cmd in COMMANDS:
            try: COMMANDS[cmd][0](meta, args)
            except (IndexError, ValueError) as ex:
                print(f"  Error: {ex}")
                print(f"  Usage: {COMMANDS[cmd][1]}")
        else:
            print(f"  Unknown: {cmd}")


# ══════════════════════════════════════
#  CLI Entry
# ══════════════════════════════════════

if __name__ == '__main__':
    print(f"""
{Colors.BOLD}{Colors.H}
╔═══════════════════════════════════════════════╗
║   Shank 2 CANIM-META Tool v7                 ║
║   MHIT + MCOL parsed  │  collision segments  ║
╚═══════════════════════════════════════════════╝
{Colors.E}""")

    if len(sys.argv) < 2:
        print(f"""  Usage:
    python {os.path.basename(__file__)} <file.canim-meta>                 Interactive
    python {os.path.basename(__file__)} <file> --view                     Quick view
    python {os.path.basename(__file__)} <file> --detail                   Detailed
    python {os.path.basename(__file__)} <file> --verify                   Verify
    python {os.path.basename(__file__)} <file> --export [out.json]        Export JSON
    python {os.path.basename(__file__)} <file> --import <in.json>         Import JSON
    python {os.path.basename(__file__)} <file> --scale <entry> <factor>
    python {os.path.basename(__file__)} <file> --time <entry> <start> <end>
    python {os.path.basename(__file__)} <file> --bbox <e> <p> <x1> <y1> <x2> <y2>
    python {os.path.basename(__file__)} --batch <folder>                  Batch analyze
""")
        sys.exit(1)

    if sys.argv[1] == '--batch' and len(sys.argv) >= 3:
        batch_analyze(sys.argv[2])
        sys.exit(0)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"  [ERROR] Not found: {filepath}")
        sys.exit(1)

    meta = CAnimMeta()
    meta.load(filepath)

    if len(sys.argv) == 2:
        print(f"  Auto-verify:")
        verify_roundtrip(meta, filepath)
        interactive_mode(meta)
    elif sys.argv[2] == '--view':
        meta.display()
    elif sys.argv[2] == '--detail':
        detailed_view(meta)
    elif sys.argv[2] == '--verify':
        verify_roundtrip(meta, filepath)
    elif sys.argv[2] == '--export':
        out = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_export(meta, [out] if out else [])
    elif sys.argv[2] == '--import':
        if len(sys.argv) < 4:
            print("  [ERROR] Missing JSON path")
            sys.exit(1)
        cmd_import(meta, [sys.argv[3]])
        meta.save()
    elif sys.argv[2] == '--scale':
        cmd_scale(meta, sys.argv[3:])
        meta.save()
    elif sys.argv[2] == '--time':
        cmd_time(meta, sys.argv[3:])
        meta.save()
    elif sys.argv[2] == '--bbox':
        cmd_bbox(meta, sys.argv[3:])
        meta.save()
    else:
        print(f"  Unknown: {sys.argv[2]}")
        sys.exit(1)