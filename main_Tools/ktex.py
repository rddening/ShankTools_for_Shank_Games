#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║            Shank 2 KTEX Universal Converter V4 - Final Edition               ║
║                                                                              ║
║   Supports ALL KTEX variants:                                                ║
║   • Version 1: No mipmaps (18-byte header)                                   ║
║   • Version 5: Compact mipmaps (10-byte header)                              ║
║   • Version 8: Full mipmaps (88-byte header)                                 ║
║                                                                              ║
║   Auto-detection • Batch processing • High quality encoding                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import struct
import sys
import json
import time
import argparse
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple, Optional
from enum import IntEnum
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("ERROR: Pillow required. Install with: pip install Pillow")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#                              CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

KTEX_MAGIC = b'KTEX'
_print_lock = threading.Lock()


class DXTFormat(IntEnum):
    DXT1 = 0
    DXT3 = 1
    DXT5 = 2

    @property
    def block_size(self) -> int:
        return 8 if self == DXTFormat.DXT1 else 16

    @property
    def name_str(self) -> str:
        return ('DXT1', 'DXT3', 'DXT5')[int(self)]


class KTEXVersion(IntEnum):
    NO_MIPMAPS = 1
    COMPACT_MIPMAPS = 5
    FULL_MIPMAPS = 8


RGB565_R = tuple((i * 255 + 15) // 31 for i in range(32))
RGB565_G = tuple((i * 255 + 31) // 63 for i in range(64))
RGB565_B = tuple((i * 255 + 15) // 31 for i in range(32))


# ══════════════════════════════════════════════════════════════════════════════
#                              DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class MipmapInfo:
    level: int
    width: int
    height: int
    size: int
    offset: int


@dataclass
class KTEXInfo:
    version: int
    format: DXTFormat
    width: int
    height: int
    header_size: int
    has_mipmaps: bool
    mipmap_count: int
    mipmaps: List[MipmapInfo]
    raw_header: bytes

    def to_dict(self) -> dict:
        return {
            'version': self.version,
            'format': self.format.name_str,
            'format_id': int(self.format),
            'width': self.width,
            'height': self.height,
            'header_size': self.header_size,
            'has_mipmaps': self.has_mipmaps,
            'mipmap_count': self.mipmap_count
        }


@dataclass
class ConversionResult:
    success: bool
    input_path: Path
    output_path: Optional[Path] = None
    error: Optional[str] = None
    duration: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
#                              UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=65536)
def rgb565_to_rgb(c: int) -> Tuple[int, int, int]:
    return (RGB565_R[(c >> 11) & 0x1F],
            RGB565_G[(c >> 5) & 0x3F],
            RGB565_B[c & 0x1F])


@lru_cache(maxsize=262144)
def rgb_to_rgb565(r: int, g: int, b: int) -> int:
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def calculate_mipmap_chain(width: int, height: int, fmt: DXTFormat) -> Tuple[List[MipmapInfo], int]:
    mipmaps = []
    total = 0
    w, h = width, height
    level = 0

    while w >= 1 and h >= 1:
        bw = max(1, (w + 3) // 4)
        bh = max(1, (h + 3) // 4)
        size = bw * bh * fmt.block_size

        mipmaps.append(MipmapInfo(level, w, h, size, total))
        total += size

        if w <= 4 and h <= 4:
            break

        w = max(1, w // 2)
        h = max(1, h // 2)
        level += 1

    return mipmaps, total


def build_alpha_table(a0: int, a1: int) -> List[int]:
    if a0 > a1:
        return [a0, a1,
                (6*a0 + 1*a1) // 7, (5*a0 + 2*a1) // 7,
                (4*a0 + 3*a1) // 7, (3*a0 + 4*a1) // 7,
                (2*a0 + 5*a1) // 7, (1*a0 + 6*a1) // 7]
    else:
        return [a0, a1,
                (4*a0 + 1*a1) // 5, (3*a0 + 2*a1) // 5,
                (2*a0 + 3*a1) // 5, (1*a0 + 4*a1) // 5,
                0, 255]


# ══════════════════════════════════════════════════════════════════════════════
#                              DXT DECODER
# ══════════════════════════════════════════════════════════════════════════════

class DXTDecoder:

    @staticmethod
    def decode(data: bytes, width: int, height: int, fmt: DXTFormat) -> Image.Image:
        image = Image.new('RGBA', (width, height))
        pixels = image.load()

        blocks_w = max(1, (width + 3) // 4)
        blocks_h = max(1, (height + 3) // 4)
        block_size = fmt.block_size

        offset = 0
        for by in range(blocks_h):
            for bx in range(blocks_w):
                if offset + block_size > len(data):
                    break

                block = data[offset:offset + block_size]
                offset += block_size

                if fmt == DXTFormat.DXT5:
                    block_pixels = DXTDecoder._decode_dxt5_block(block)
                elif fmt == DXTFormat.DXT3:
                    block_pixels = DXTDecoder._decode_dxt3_block(block)
                else:
                    block_pixels = DXTDecoder._decode_dxt1_block(block)

                for i, pixel in enumerate(block_pixels):
                    px = bx * 4 + (i % 4)
                    py = by * 4 + (i // 4)
                    if px < width and py < height:
                        pixels[px, py] = pixel

        return image

    @staticmethod
    def _decode_dxt5_block(block: bytes) -> List[Tuple[int, int, int, int]]:
        a0, a1 = block[0], block[1]
        alpha_table = build_alpha_table(a0, a1)
        alpha_bits = sum(block[2+i] << (i*8) for i in range(6))

        c0 = struct.unpack('<H', block[8:10])[0]
        c1 = struct.unpack('<H', block[10:12])[0]
        color_bits = struct.unpack('<I', block[12:16])[0]

        rgb0, rgb1 = rgb565_to_rgb(c0), rgb565_to_rgb(c1)
        colors = [
            rgb0, rgb1,
            tuple((2*rgb0[i] + rgb1[i]) // 3 for i in range(3)),
            tuple((rgb0[i] + 2*rgb1[i]) // 3 for i in range(3))
        ]

        pixels = []
        for i in range(16):
            a_idx = (alpha_bits >> (i * 3)) & 0x7
            c_idx = (color_bits >> (i * 2)) & 0x3
            r, g, b = colors[c_idx]
            pixels.append((r, g, b, alpha_table[a_idx]))

        return pixels

    @staticmethod
    def _decode_dxt3_block(block: bytes) -> List[Tuple[int, int, int, int]]:
        alpha_bits = struct.unpack('<Q', block[0:8])[0]

        c0 = struct.unpack('<H', block[8:10])[0]
        c1 = struct.unpack('<H', block[10:12])[0]
        color_bits = struct.unpack('<I', block[12:16])[0]

        rgb0, rgb1 = rgb565_to_rgb(c0), rgb565_to_rgb(c1)
        colors = [
            rgb0, rgb1,
            tuple((2*rgb0[i] + rgb1[i]) // 3 for i in range(3)),
            tuple((rgb0[i] + 2*rgb1[i]) // 3 for i in range(3))
        ]

        pixels = []
        for i in range(16):
            a = ((alpha_bits >> (i * 4)) & 0xF) * 17
            c_idx = (color_bits >> (i * 2)) & 0x3
            r, g, b = colors[c_idx]
            pixels.append((r, g, b, a))

        return pixels

    @staticmethod
    def _decode_dxt1_block(block: bytes) -> List[Tuple[int, int, int, int]]:
        c0 = struct.unpack('<H', block[0:2])[0]
        c1 = struct.unpack('<H', block[2:4])[0]
        bits = struct.unpack('<I', block[4:8])[0]

        rgb0, rgb1 = rgb565_to_rgb(c0), rgb565_to_rgb(c1)

        if c0 > c1:
            colors = [
                rgb0 + (255,), rgb1 + (255,),
                tuple((2*rgb0[i] + rgb1[i]) // 3 for i in range(3)) + (255,),
                tuple((rgb0[i] + 2*rgb1[i]) // 3 for i in range(3)) + (255,)
            ]
        else:
            colors = [
                rgb0 + (255,), rgb1 + (255,),
                tuple((rgb0[i] + rgb1[i]) // 2 for i in range(3)) + (255,),
                (0, 0, 0, 0)
            ]

        return [colors[(bits >> (i * 2)) & 0x3] for i in range(16)]


# ══════════════════════════════════════════════════════════════════════════════
#                              DXT ENCODER
# ══════════════════════════════════════════════════════════════════════════════

class DXTEncoder:

    def __init__(self, use_perceptual: bool = True):
        self.use_perceptual = use_perceptual
        self.weights = (0.299, 0.587, 0.114) if use_perceptual else (1, 1, 1)

    def encode(self, image: Image.Image, fmt: DXTFormat) -> bytes:
        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        width, height = image.size
        pixels = image.load()

        blocks_w = max(1, (width + 3) // 4)
        blocks_h = max(1, (height + 3) // 4)

        result = bytearray()

        for by in range(blocks_h):
            for bx in range(blocks_w):
                block_pixels = []
                for py in range(4):
                    for px in range(4):
                        x = min(bx * 4 + px, width - 1)
                        y = min(by * 4 + py, height - 1)
                        block_pixels.append(pixels[x, y])

                if fmt == DXTFormat.DXT5:
                    result.extend(self._encode_dxt5_block(block_pixels))
                elif fmt == DXTFormat.DXT3:
                    result.extend(self._encode_dxt3_block(block_pixels))
                else:
                    result.extend(self._encode_dxt1_block(block_pixels))

        return bytes(result)

    def _color_distance(self, c1: tuple, c2: tuple) -> float:
        return sum(self.weights[i] * (c1[i] - c2[i]) ** 2 for i in range(3))

    def _find_endpoints(self, colors: List[tuple]) -> Tuple[tuple, tuple]:
        if not colors:
            return (0, 0, 0), (255, 255, 255)

        min_c = [min(c[i] for c in colors) for i in range(3)]
        max_c = [max(c[i] for c in colors) for i in range(3)]

        c0 = tuple(max_c)
        c1 = tuple(min_c)

        if c0 == c1:
            c1 = tuple(min(255, c + 1) for c in c0)

        return c0, c1

    def _encode_dxt5_block(self, pixels: List[tuple]) -> bytes:
        block = bytearray(16)

        alphas = [p[3] for p in pixels]
        a0, a1 = max(alphas), min(alphas)
        if a0 == a1:
            a0 = min(255, a1 + 1)

        block[0], block[1] = a0, a1
        alpha_table = build_alpha_table(a0, a1)

        alpha_bits = 0
        for i, a in enumerate(alphas):
            best_idx = min(range(8), key=lambda idx: abs(a - alpha_table[idx]))
            alpha_bits |= best_idx << (i * 3)

        for i in range(6):
            block[2 + i] = (alpha_bits >> (i * 8)) & 0xFF

        colors = [(p[0], p[1], p[2]) for p in pixels]
        c0, c1 = self._find_endpoints(colors)

        c0_565 = rgb_to_rgb565(*c0)
        c1_565 = rgb_to_rgb565(*c1)

        if c0_565 < c1_565:
            c0_565, c1_565 = c1_565, c0_565
            c0, c1 = c1, c0

        block[8:10] = struct.pack('<H', c0_565)
        block[10:12] = struct.pack('<H', c1_565)

        color_table = [
            c0, c1,
            tuple((2*c0[i] + c1[i]) // 3 for i in range(3)),
            tuple((c0[i] + 2*c1[i]) // 3 for i in range(3))
        ]

        color_bits = 0
        for i, color in enumerate(colors):
            best_idx = min(range(4), key=lambda idx: self._color_distance(color, color_table[idx]))
            color_bits |= best_idx << (i * 2)

        block[12:16] = struct.pack('<I', color_bits)
        return bytes(block)

    def _encode_dxt3_block(self, pixels: List[tuple]) -> bytes:
        block = bytearray(16)

        alpha_bits = 0
        for i, p in enumerate(pixels):
            alpha_bits |= (p[3] // 17) << (i * 4)
        block[0:8] = struct.pack('<Q', alpha_bits)

        colors = [(p[0], p[1], p[2]) for p in pixels]
        c0, c1 = self._find_endpoints(colors)

        c0_565 = rgb_to_rgb565(*c0)
        c1_565 = rgb_to_rgb565(*c1)

        if c0_565 < c1_565:
            c0_565, c1_565 = c1_565, c0_565
            c0, c1 = c1, c0

        block[8:10] = struct.pack('<H', c0_565)
        block[10:12] = struct.pack('<H', c1_565)

        color_table = [
            c0, c1,
            tuple((2*c0[i] + c1[i]) // 3 for i in range(3)),
            tuple((c0[i] + 2*c1[i]) // 3 for i in range(3))
        ]

        color_bits = 0
        for i, color in enumerate(colors):
            best_idx = min(range(4), key=lambda idx: self._color_distance(color, color_table[idx]))
            color_bits |= best_idx << (i * 2)

        block[12:16] = struct.pack('<I', color_bits)
        return bytes(block)

    def _encode_dxt1_block(self, pixels: List[tuple]) -> bytes:
        block = bytearray(8)

        colors = [(p[0], p[1], p[2]) for p in pixels]
        c0, c1 = self._find_endpoints(colors)

        c0_565 = rgb_to_rgb565(*c0)
        c1_565 = rgb_to_rgb565(*c1)

        if c0_565 < c1_565:
            c0_565, c1_565 = c1_565, c0_565
            c0, c1 = c1, c0
        elif c0_565 == c1_565:
            c0_565 = min(65535, c0_565 + 1)

        block[0:2] = struct.pack('<H', c0_565)
        block[2:4] = struct.pack('<H', c1_565)

        color_table = [
            c0, c1,
            tuple((2*c0[i] + c1[i]) // 3 for i in range(3)),
            tuple((c0[i] + 2*c1[i]) // 3 for i in range(3))
        ]

        color_bits = 0
        for i, color in enumerate(colors):
            best_idx = min(range(4), key=lambda idx: self._color_distance(color, color_table[idx]))
            color_bits |= best_idx << (i * 2)

        block[4:8] = struct.pack('<I', color_bits)
        return bytes(block)


# ══════════════════════════════════════════════════════════════════════════════
#                              KTEX CONVERTER
# ══════════════════════════════════════════════════════════════════════════════

class KTEXConverter:

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.encoder = DXTEncoder()

    def log(self, msg: str):
        if self.verbose:
            print(f"  {msg}")

    def _detect_structure(self, data: bytes) -> KTEXInfo:
        if len(data) < 12 or data[0:4] != KTEX_MAGIC:
            raise ValueError("Invalid KTEX file")

        version = data[6]
        fmt = DXTFormat(data[7])
        width = struct.unpack('<H', data[8:10])[0]
        height = struct.unpack('<H', data[10:12])[0]

        blocks_w = max(1, (width + 3) // 4)
        blocks_h = max(1, (height + 3) // 4)
        single_size = blocks_w * blocks_h * fmt.block_size

        mipmaps, mip_total = calculate_mipmap_chain(width, height, fmt)

        no_mip_header = len(data) - single_size
        mip_header = len(data) - mip_total

        if 12 <= no_mip_header <= 64:
            return KTEXInfo(
                version=version, format=fmt, width=width, height=height,
                header_size=no_mip_header, has_mipmaps=False, mipmap_count=1,
                mipmaps=[MipmapInfo(0, width, height, single_size, 0)],
                raw_header=data[:no_mip_header]
            )
        elif 8 <= mip_header <= 256:
            return KTEXInfo(
                version=version, format=fmt, width=width, height=height,
                header_size=mip_header, has_mipmaps=True, mipmap_count=len(mipmaps),
                mipmaps=mipmaps, raw_header=data[:mip_header]
            )
        else:
            if version == 1:
                return KTEXInfo(
                    version=version, format=fmt, width=width, height=height,
                    header_size=18, has_mipmaps=False, mipmap_count=1,
                    mipmaps=[MipmapInfo(0, width, height, single_size, 0)],
                    raw_header=data[:18]
                )
            elif version == 5:
                return KTEXInfo(
                    version=version, format=fmt, width=width, height=height,
                    header_size=10, has_mipmaps=True, mipmap_count=len(mipmaps),
                    mipmaps=mipmaps, raw_header=data[:10]
                )
            elif version == 8:
                return KTEXInfo(
                    version=version, format=fmt, width=width, height=height,
                    header_size=88, has_mipmaps=True, mipmap_count=len(mipmaps),
                    mipmaps=mipmaps, raw_header=data[:88]
                )
            else:
                raise ValueError(f"Unknown KTEX version: {version}")

    def extract(self, input_path: Path, output_path: Optional[Path] = None,
                extract_all_mipmaps: bool = False) -> ConversionResult:
        start = time.time()
        input_path = Path(input_path)

        try:
            with open(input_path, 'rb') as f:
                data = f.read()

            info = self._detect_structure(data)

            with _print_lock:
                print(f"  {input_path.name}")
                print(f"   Dimensions: {info.width}x{info.height}")
                print(f"   Format: {info.format.name_str}")
                print(f"   Version: {info.version} ({'mipmaps' if info.has_mipmaps else 'no mipmaps'})")
                print(f"   Header: {info.header_size} bytes")

            if output_path is None:
                output_path = input_path.with_suffix('.png')
            output_path = Path(output_path)

            mip0 = info.mipmaps[0]
            image_data = data[info.header_size:info.header_size + mip0.size]
            image = DXTDecoder.decode(image_data, mip0.width, mip0.height, info.format)

            image.save(output_path, 'PNG', optimize=True)

            with _print_lock:
                print(f"   Saved: {output_path.name}")

            self._save_metadata(output_path, info)

            if extract_all_mipmaps and info.has_mipmaps:
                self._extract_mipmaps(data, info, input_path)

            return ConversionResult(
                success=True, input_path=input_path,
                output_path=output_path, duration=time.time() - start
            )

        except Exception as e:
            with _print_lock:
                print(f"   Error: {e}")
            return ConversionResult(
                success=False, input_path=input_path,
                error=str(e), duration=time.time() - start
            )

    def _save_metadata(self, png_path: Path, info: KTEXInfo):
        header_path = png_path.with_suffix('.ktex_header')
        with open(header_path, 'wb') as f:
            f.write(info.raw_header)

        json_path = png_path.with_suffix('.ktex_meta.json')
        with open(json_path, 'w') as f:
            json.dump(info.to_dict(), f, indent=2)

        self.log(f"Metadata: {json_path.name}")

    def _extract_mipmaps(self, data: bytes, info: KTEXInfo, input_path: Path):
        offset = info.header_size

        for mip in info.mipmaps:
            mip_data = data[offset:offset + mip.size]
            mip_image = DXTDecoder.decode(mip_data, mip.width, mip.height, info.format)

            mip_path = input_path.with_name(f"{input_path.stem}_mip{mip.level}.png")
            mip_image.save(mip_path, 'PNG')

            with _print_lock:
                print(f"   Mip {mip.level}: {mip.width}x{mip.height}")

            offset += mip.size

    def rebuild(self, input_path: Path, output_path: Optional[Path] = None,
                original_ktex: Optional[Path] = None,
                force_mipmaps: Optional[bool] = None) -> ConversionResult:
        start = time.time()
        input_path = Path(input_path)

        try:
            image = Image.open(input_path).convert('RGBA')
            width, height = image.size

            with _print_lock:
                print(f"  {input_path.name}")
                print(f"   Dimensions: {width}x{height}")

            if output_path is None:
                output_path = input_path.with_suffix('.tex')
            output_path = Path(output_path)

            header_data, meta = self._load_metadata(input_path, original_ktex)

            fmt = DXTFormat(meta.get('format_id', 2))
            has_mipmaps = meta.get('has_mipmaps', True) if force_mipmaps is None else force_mipmaps
            version = meta.get('version', 8 if has_mipmaps else 1)

            with _print_lock:
                print(f"   Format: {fmt.name_str}")
                print(f"   Mipmaps: {'Yes' if has_mipmaps else 'No'}")

            if has_mipmaps:
                mipmaps, _ = calculate_mipmap_chain(width, height, fmt)
                texture_data = self._encode_with_mipmaps(image, mipmaps, fmt)
            else:
                texture_data = self.encoder.encode(image, fmt)

            if header_data and len(header_data) >= 12:
                header = bytearray(header_data)
                header[8:10] = struct.pack('<H', width)
                header[10:12] = struct.pack('<H', height)
                final_data = bytes(header) + texture_data
            else:
                header = self._create_header(width, height, fmt, version, has_mipmaps)
                final_data = header + texture_data

            with open(output_path, 'wb') as f:
                f.write(final_data)

            with _print_lock:
                print(f"   Saved: {output_path.name} ({len(final_data):,} bytes)")

            return ConversionResult(
                success=True, input_path=input_path,
                output_path=output_path, duration=time.time() - start
            )

        except Exception as e:
            with _print_lock:
                print(f"   Error: {e}")
            return ConversionResult(
                success=False, input_path=input_path,
                error=str(e), duration=time.time() - start
            )

    def _load_metadata(self, png_path: Path, original_ktex: Optional[Path]) -> Tuple[Optional[bytes], dict]:
        header_data = None
        meta = {}

        original_tex = png_path.with_suffix('.tex')
        if original_tex.exists():
            self.log(f"Found original TEX: {original_tex.name}")
            with open(original_tex, 'rb') as f:
                orig_data = f.read()
            info = self._detect_structure(orig_data)
            header_data = info.raw_header
            meta = info.to_dict()
            print(f"   Original TEX info:")
            print(f"      Version: {meta['version']}")
            print(f"      Format: {meta['format']} (ID: {meta['format_id']})")
            print(f"      Size: {meta['width']}x{meta['height']}")
            print(f"      Header: {meta['header_size']} bytes")
            if meta['has_mipmaps']:
                print(f"      Mipmaps: {meta['mipmap_count']} levels")
            else:
                print(f"      Mipmaps: None")
            return header_data, meta

        if original_ktex:
            original_ktex = Path(original_ktex)
            if original_ktex.exists():
                with open(original_ktex, 'rb') as f:
                    orig_data = f.read()
                info = self._detect_structure(orig_data)
                header_data = info.raw_header
                meta = info.to_dict()
                self.log(f"Using specified original: {original_ktex.name}")
                return header_data, meta

        header_file = png_path.with_suffix('.ktex_header')
        if header_file.exists():
            with open(header_file, 'rb') as f:
                header_data = f.read()
            self.log(f"Using saved header: {header_file.name}")

        json_file = png_path.with_suffix('.ktex_meta.json')
        if json_file.exists():
            with open(json_file, 'r') as f:
                meta = json.load(f)
            self.log(f"Using saved metadata: {json_file.name}")

        if header_data or meta:
            return header_data, meta

        print(f"   No original TEX found, using defaults (Version 8, DXT5, with mipmaps)")
        return header_data, meta

    def _encode_with_mipmaps(self, image: Image.Image, mipmaps: List[MipmapInfo],
                             fmt: DXTFormat) -> bytes:
        result = bytearray()

        for mip in mipmaps:
            if mip.level > 0:
                mip_image = image.resize((mip.width, mip.height), Image.Resampling.LANCZOS)
            else:
                mip_image = image

            mip_data = self.encoder.encode(mip_image, fmt)
            result.extend(mip_data)
            self.log(f"Mip {mip.level}: {mip.width}x{mip.height}")

        return bytes(result)

    def _create_header(self, width: int, height: int, fmt: DXTFormat,
                       version: int, has_mipmaps: bool) -> bytes:
        if has_mipmaps and version == 8:
            header = bytearray(88)
            header[0:4] = KTEX_MAGIC
            header[6] = version
            header[7] = int(fmt)
            header[8:10] = struct.pack('<H', width)
            header[10:12] = struct.pack('<H', height)
            return bytes(header)

        elif has_mipmaps and version == 5:
            header = bytearray(10)
            header[0:4] = KTEX_MAGIC
            header[6] = version
            header[7] = int(fmt)
            header[8:10] = struct.pack('<H', width)
            return bytes(header)

        else:
            header = bytearray(18)
            header[0:4] = KTEX_MAGIC
            header[6] = 1
            header[7] = int(fmt)
            header[8:10] = struct.pack('<H', width)
            header[10:12] = struct.pack('<H', height)
            return bytes(header)

    def batch_extract(self, files: List[Path], output_dir: Optional[Path] = None,
                      workers: int = 4,
                      extract_all_mipmaps: bool = False) -> List[ConversionResult]:
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

        results: List[Optional[ConversionResult]] = [None] * len(files)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for i, f in enumerate(files):
                f = Path(f)
                out = output_dir / f.with_suffix('.png').name if output_dir else None
                future = executor.submit(self.extract, f, out, extract_all_mipmaps)
                futures[future] = i

            for future in as_completed(futures):
                results[futures[future]] = future.result()

        return results

    def batch_rebuild(self, files: List[Path], output_dir: Optional[Path] = None,
                      workers: int = 4,
                      force_mipmaps: Optional[bool] = None) -> List[ConversionResult]:
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

        results: List[Optional[ConversionResult]] = [None] * len(files)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for i, f in enumerate(files):
                f = Path(f)
                out = output_dir / f.with_suffix('.tex').name if output_dir else None
                future = executor.submit(self.rebuild, f, out, None, force_mipmaps)
                futures[future] = i

            for future in as_completed(futures):
                results[futures[future]] = future.result()

        return results

    def info(self, input_path: Path) -> Optional[KTEXInfo]:
        input_path = Path(input_path)

        try:
            with open(input_path, 'rb') as f:
                data = f.read()

            info = self._detect_structure(data)

            print(f"\n{'='*50}")
            print(f" {input_path.name}")
            print(f"{'='*50}")
            print(f" Size:       {len(data):,} bytes")
            print(f" Dimensions: {info.width} x {info.height}")
            print(f" Format:     {info.format.name_str}")
            print(f" Version:    {info.version}")
            print(f" Header:     {info.header_size} bytes")
            print(f" Mipmaps:    {info.mipmap_count} levels")

            if info.has_mipmaps:
                print(f"\n Mipmap chain:")
                for mip in info.mipmaps:
                    print(f"   Level {mip.level}: {mip.width:4d}x{mip.height:<4d} "
                          f"({mip.size:,} bytes)")

            return info

        except Exception as e:
            print(f" Error: {e}")
            return None


# ══════════════════════════════════════════════════════════════════════════════
#                   STANDALONE INFO HELPER
# ══════════════════════════════════════════════════════════════════════════════

def ktex_info(filepath: str) -> str:
    """Return a formatted info string for a single TEX file."""
    import io, contextlib

    buf = io.StringIO()
    converter = KTEXConverter(verbose=False)

    with contextlib.redirect_stdout(buf):
        converter.info(Path(filepath))

    return buf.getvalue().rstrip()


# ══════════════════════════════════════════════════════════════════════════════
#                    MAIN_TOOLS REGISTRATION (for main.py)
# ══════════════════════════════════════════════════════════════════════════════

def register(tool):
    """
    Registers the KTEX tool card.
    Opens a simple dialog-based interface (no embedded panel).
    """
    tool(
        icon="🖼",
        title="KTEX Converter",
        desc="Extract, rebuild, and inspect Shank 2 KTEX textures",
        tool_info={
            "name": "KTEX Converter",
            "icon": "🖼",
            "custom_ui": True,
            "builder": build_ktex_panel,
        },
    )


def build_ktex_panel(parent, theme, status_cb, back_cb):
    """
    Lightweight panel – uses only tkinter (already loaded by main.py).
    No extra imports, no threading conflicts with PyInstaller.
    """
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    converter = KTEXConverter(verbose=True)

    # ── Main container ────────────────────────────────────────
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
        top_bar, text="KTEX Converter",
        bg=theme["bg_secondary"], fg=theme["text"],
        font=("Segoe UI", 14, "bold"),
    ).pack(side="left", padx=10, pady=10)

    # ── Content ───────────────────────────────────────────────
    content = tk.Frame(main, bg=theme["bg"])
    content.pack(fill="both", expand=True, padx=15, pady=10)

    left_panel = tk.Frame(content, bg=theme["bg_panel"], width=400)
    left_panel.pack(side="left", fill="y", padx=(0, 8))
    left_panel.pack_propagate(False)

    right_panel = tk.Frame(content, bg=theme["bg_panel"])
    right_panel.pack(side="left", fill="both", expand=True)

    # ── Left: File list ───────────────────────────────────────
    tk.Label(
        left_panel, text="Selected Files",
        bg=theme["bg_panel"], fg=theme["text"],
        font=("Segoe UI", 12, "bold"),
    ).pack(padx=12, pady=(12, 4), anchor="w")

    file_list_frame = tk.Frame(left_panel, bg=theme["bg_panel"])
    file_list_frame.pack(fill="both", expand=True, padx=12, pady=4)

    file_listbox = tk.Listbox(
        file_list_frame,
        bg=theme["entry_bg"], fg=theme["entry_fg"],
        selectbackground=theme["accent"], selectforeground="#FFFFFF",
        font=("Consolas", 9), relief="flat", bd=0, selectmode="extended",
    )
    file_scrollbar = ttk.Scrollbar(file_list_frame, orient="vertical", command=file_listbox.yview)
    file_listbox.configure(yscrollcommand=file_scrollbar.set)
    file_scrollbar.pack(side="right", fill="y")
    file_listbox.pack(side="left", fill="both", expand=True)

    selected_files = []

    def add_files():
        paths = filedialog.askopenfilenames(
            title="Select files",
            filetypes=[("TEX & PNG", "*.tex *.png"), ("TEX", "*.tex"),
                       ("PNG", "*.png"), ("All", "*.*")],
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
        for ext in ("*.tex", "*.png"):
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
        _update_count()

    def _update_count():
        t = sum(1 for f in selected_files if f.suffix.lower() == ".tex")
        p = sum(1 for f in selected_files if f.suffix.lower() == ".png")
        count_lbl.config(text=f"{len(selected_files)} file(s)  |  TEX: {t}  PNG: {p}")

    btn_frame = tk.Frame(left_panel, bg=theme["bg_panel"])
    btn_frame.pack(fill="x", padx=12, pady=4)
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
    count_lbl.pack(padx=12, pady=(0, 6), anchor="w")

    # ── Options ───────────────────────────────────────────────
    tk.Frame(left_panel, bg=theme["border"], height=1).pack(fill="x", padx=12, pady=4)
    tk.Label(left_panel, text="Options", bg=theme["bg_panel"], fg=theme["text"],
             font=("Segoe UI", 11, "bold")).pack(padx=12, pady=(8, 4), anchor="w")

    output_dir_var = tk.StringVar(value="")

    def pick_out():
        d = filedialog.askdirectory(title="Output directory")
        if d:
            output_dir_var.set(d)

    of = tk.Frame(left_panel, bg=theme["bg_panel"])
    of.pack(fill="x", padx=12, pady=2)
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
    tk.Label(of, text="(empty = same as input)", bg=theme["bg_panel"],
             fg=theme["text_secondary"], font=("Segoe UI", 8)).pack(anchor="w")

    extract_mip_var = tk.BooleanVar(value=False)
    force_mip_var = tk.BooleanVar(value=True)

    tk.Checkbutton(left_panel, text="Extract all mipmap levels",
                   variable=extract_mip_var, bg=theme["bg_panel"], fg=theme["text"],
                   selectcolor=theme["entry_bg"], activebackground=theme["bg_panel"],
                   activeforeground=theme["text"], font=("Segoe UI", 9)
                   ).pack(padx=12, pady=2, anchor="w")
    tk.Checkbutton(left_panel, text="Generate mipmaps on rebuild",
                   variable=force_mip_var, bg=theme["bg_panel"], fg=theme["text"],
                   selectcolor=theme["entry_bg"], activebackground=theme["bg_panel"],
                   activeforeground=theme["text"], font=("Segoe UI", 9)
                   ).pack(padx=12, pady=2, anchor="w")

    # ── Action buttons ────────────────────────────────────────
    tk.Frame(left_panel, bg=theme["border"], height=1).pack(fill="x", padx=12, pady=8)
    af = tk.Frame(left_panel, bg=theme["bg_panel"])
    af.pack(fill="x", padx=12, pady=(0, 12))

    def _threaded(fn):
        import threading as _t
        _t.Thread(target=fn, daemon=True).start()

    def do_extract():
        tex = [f for f in selected_files if f.suffix.lower() == ".tex"]
        if not tex:
            messagebox.showwarning("No TEX", "Add .tex files first.")
            return
        _log_clear()
        _log(f"Extracting {len(tex)} file(s)...\n")
        status_cb(f"Extracting {len(tex)} file(s)...")

        def work():
            out = Path(output_dir_var.get()) if output_dir_var.get() else None
            res = converter.batch_extract(tex, out,
                                          extract_all_mipmaps=extract_mip_var.get())
            ok = sum(1 for r in res if r and r.success)
            for r in res:
                if r and r.success:
                    _log(f"  OK  {r.input_path.name} -> {r.output_path.name}  ({r.duration:.2f}s)")
                elif r:
                    _log(f"  ERR {r.input_path.name}: {r.error}")
            _log(f"\nDone: {ok}/{len(res)}")
            status_cb(f"Extract: {ok}/{len(res)}")
        _threaded(work)

    def do_rebuild():
        png = [f for f in selected_files if f.suffix.lower() == ".png"]
        if not png:
            messagebox.showwarning("No PNG", "Add .png files first.")
            return
        _log_clear()
        _log(f"Rebuilding {len(png)} file(s)...\n")
        status_cb(f"Rebuilding {len(png)} file(s)...")

        def work():
            out = Path(output_dir_var.get()) if output_dir_var.get() else None
            res = converter.batch_rebuild(png, out, force_mipmaps=force_mip_var.get())
            ok = sum(1 for r in res if r and r.success)
            for r in res:
                if r and r.success:
                    _log(f"  OK  {r.input_path.name} -> {r.output_path.name}  ({r.duration:.2f}s)")
                elif r:
                    _log(f"  ERR {r.input_path.name}: {r.error}")
            _log(f"\nDone: {ok}/{len(res)}")
            status_cb(f"Rebuild: {ok}/{len(res)}")
        _threaded(work)

    def do_info():
        tex = [f for f in selected_files if f.suffix.lower() == ".tex"]
        if not tex:
            messagebox.showwarning("No TEX", "Add .tex files first.")
            return
        _log_clear()
        status_cb(f"Inspecting {len(tex)} file(s)...")

        def work():
            for f in tex:
                _log(ktex_info(str(f)))
                _log("-" * 40)
            status_cb("Info done")
        _threaded(work)

    for txt, cmd, clr in [
        ("Extract (TEX->PNG)", do_extract, theme["btn_bg"]),
        ("Rebuild (PNG->TEX)", do_rebuild, theme["accent"]),
        ("File Info", do_info, theme["entry_bg"]),
    ]:
        tk.Button(
            af, text=txt, bg=clr,
            fg=theme["btn_fg"] if clr != theme["entry_bg"] else theme["text"],
            font=("Segoe UI", 11, "bold"), relief="flat", cursor="hand2",
            command=cmd, activebackground=theme["btn_hover"], activeforeground="#FFF",
        ).pack(fill="x", pady=3, ipady=6)

    # ── Right: Log ────────────────────────────────────────────
    tk.Label(right_panel, text="Output Log", bg=theme["bg_panel"], fg=theme["text"],
             font=("Segoe UI", 12, "bold")).pack(padx=12, pady=(12, 4), anchor="w")

    log_text = tk.Text(right_panel, bg=theme["entry_bg"], fg=theme["entry_fg"],
                       insertbackground=theme["text"], font=("Consolas", 10),
                       relief="flat", bd=0, wrap="word", state="disabled")
    log_sc = ttk.Scrollbar(right_panel, orient="vertical", command=log_text.yview)
    log_text.configure(yscrollcommand=log_sc.set)
    log_sc.pack(side="right", fill="y", padx=(0, 4), pady=4)
    log_text.pack(fill="both", expand=True, padx=(12, 0), pady=(0, 12))

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

    _log("KTEX Converter ready.")
    _log("Add files, then choose an action.")
    _log("-" * 40)

    return main


# ══════════════════════════════════════════════════════════════════════════════
#                              CLI INTERFACE
# ══════════════════════════════════════════════════════════════════════════════

def expand_wildcards(patterns: List[str]) -> List[Path]:
    import glob
    files = []
    for pattern in patterns:
        expanded = glob.glob(pattern)
        if expanded:
            files.extend(Path(p) for p in expanded)
        else:
            files.append(Path(pattern))
    return files


def main():
    parser = argparse.ArgumentParser(
        description='Shank 2 KTEX Universal Converter V4',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s extract texture.tex
  %(prog)s extract *.tex -o output/
  %(prog)s rebuild texture.png
  %(prog)s rebuild *.png -o textures/
  %(prog)s rebuild new.png --original old.tex
  %(prog)s info texture.tex
        ''')

    parser.add_argument('command', choices=['extract', 'rebuild', 'info'])
    parser.add_argument('input', nargs='+')
    parser.add_argument('-o', '--output')
    parser.add_argument('--original')
    parser.add_argument('--mipmaps', action='store_true')
    parser.add_argument('--no-mipmaps', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('--json', action='store_true')

    args = parser.parse_args()

    print("Shank 2 KTEX Converter V4\n")

    converter = KTEXConverter(verbose=args.verbose)
    input_files = expand_wildcards(args.input)

    if args.command == 'extract':
        if len(input_files) == 1 and args.output and not Path(args.output).suffix:
            output_dir = Path(args.output)
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / input_files[0].with_suffix('.png').name
            converter.extract(input_files[0], out_path, args.mipmaps)
        elif len(input_files) == 1:
            out_path = Path(args.output) if args.output else None
            converter.extract(input_files[0], out_path, args.mipmaps)
        else:
            output_dir = Path(args.output) if args.output else None
            results = converter.batch_extract(input_files, output_dir,
                                              extract_all_mipmaps=args.mipmaps)
            success = sum(1 for r in results if r and r.success)
            print(f"\nCompleted: {success}/{len(results)}")

    elif args.command == 'rebuild':
        force_mipmaps = None
        if args.mipmaps:
            force_mipmaps = True
        elif args.no_mipmaps:
            force_mipmaps = False

        original = Path(args.original) if args.original else None

        if len(input_files) == 1:
            out_path = Path(args.output) if args.output else None
            converter.rebuild(input_files[0], out_path, original, force_mipmaps)
        else:
            output_dir = Path(args.output) if args.output else None
            results = converter.batch_rebuild(input_files, output_dir,
                                              force_mipmaps=force_mipmaps)
            success = sum(1 for r in results if r and r.success)
            print(f"\nCompleted: {success}/{len(results)}")

    elif args.command == 'info':
        all_info = []
        for f in input_files:
            info = converter.info(f)
            if info and args.json:
                all_info.append(info.to_dict())

        if args.json:
            print(json.dumps(all_info, indent=2))


if __name__ == '__main__':
    main()