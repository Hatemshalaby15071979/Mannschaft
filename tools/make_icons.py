"""Generate the PWA icons with the standard library only.

A dark rounded square with five accent bars of varying height — a waveform.
Supersampled 2x and box-filtered so the edges are not jagged. No PIL, no
ffmpeg: the PNG encoder is about twenty lines of zlib + struct.

Usage:  python3 tools/make_icons.py   (writes src/v5/client/icons/)
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1] / "src" / "v5" / "client"

# palette
BG = (13, 17, 23, 255)
ACCENT = (88, 166, 255, 255)

# five bars, fraction of width: (center_x, width, height)
BARS = [
    (0.20, 0.09, 0.30),
    (0.35, 0.09, 0.52),
    (0.50, 0.09, 0.72),
    (0.65, 0.09, 0.46),
    (0.80, 0.09, 0.26),
]
RADIUS = 0.22


def in_rounded_rect(x, y, x0, y0, x1, y1, radius):
    # inside the body?
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    # corner circles
    corners = [
        (x0 + radius, y0 + radius),
        (x1 - radius, y0 + radius),
        (x0 + radius, y1 - radius),
        (x1 - radius, y1 - radius),
    ]
    near_corner = None
    for cx, cy in corners:
        if (x < cx and y < cy) or (x > cx and y < cy) or (x < cx and y > cy) or (x > cx and y > cy):
            near_corner = (cx, cy)
    if near_corner is None:
        return True
    cx, cy = near_corner
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2


def in_bar(x, y, cx, width, height, size):
    # capsule: rounded rect with radius = half the width
    r = width * size / 2
    left = cx * size - r
    right = cx * size + r
    top = (0.5 - height / 2) * size
    bottom = (0.5 + height / 2) * size
    return in_rounded_rect(x, y, left, top, right, bottom, r)


def build(size: int, sample: int = 2) -> bytes:
    w = size * sample
    # per-pixel colour in supersampled space
    buffer = bytearray()
    for row in range(w):
        buffer.append(0)  # PNG filter byte
        for col in range(w):
            x = col / w
            y = row / w
            inside_bg = in_rounded_rect(x * size, y * size, 0, 0, size, size, RADIUS * size)
            if not inside_bg:
                buffer.extend((0, 0, 0, 0))
                continue
            color = BG
            for cx, width, height in BARS:
                if in_bar(x * size, y * size, cx, width, height, size):
                    color = ACCENT
                    break
            buffer.extend(color)

    # box-downsample to target size
    pixels = bytearray()
    s = sample
    for oy in range(size):
        pixels.append(0)
        for ox in range(size):
            reds = greens = blues = alphas = 0
            for sy in range(s):
                for sx in range(s):
                    idx = ((oy * s + sy) * w + (ox * s + sx)) * 4 + 1
                    reds += buffer[idx]
                    greens += buffer[idx + 1]
                    blues += buffer[idx + 2]
                    alphas += buffer[idx + 3]
            n = s * s
            pixels.extend(
                (
                    reds // n,
                    greens // n,
                    blues // n,
                    alphas // n,
                )
            )

    def chunk(kind: bytes, payload: bytes) -> bytes:
        block = struct.pack(">I", len(payload)) + kind + payload
        block += struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        return block

    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(pixels), 9)
    return header + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def main() -> None:
    icons = CLIENT / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512)):
        path = icons / name
        path.write_bytes(build(size))
        print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
