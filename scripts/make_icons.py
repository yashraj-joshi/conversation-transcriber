#!/usr/bin/env python3
"""Generate the PWA / apple-touch PNG icons with the standard library only (no Pillow).

Draws a white microphone-style capsule with a red record dot on a dark-blue background.
Usage: python3 scripts/make_icons.py   (writes frontend/icons/*.png)
"""

import os
import struct
import zlib

BG = (31, 58, 95)
FG = (255, 255, 255)
DOT = (230, 72, 61)
OUT = os.path.join(os.path.dirname(__file__), "..", "frontend", "icons")


def png(width, height, pixel):
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(pixel(x, y))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


def icon(size, safe=1.0):
    s = size * safe
    cx, top, bottom, r = size / 2, size / 2 - s * 0.25, size / 2 + s * 0.05, s * 0.12
    dot_c, dot_r = (size / 2 + s * 0.3, size / 2 - s * 0.28), s * 0.08
    stand_w = s * 0.03

    def pixel(x, y):
        px, py = x + 0.5, y + 0.5
        if (px - dot_c[0]) ** 2 + (py - dot_c[1]) ** 2 <= dot_r ** 2:
            return DOT
        # capsule
        cy = min(max(py, top), bottom)
        if (px - cx) ** 2 + (py - cy) ** 2 <= r ** 2:
            return FG
        # arc under the capsule
        d = ((px - cx) ** 2 + (py - bottom) ** 2) ** 0.5
        if py >= bottom and abs(d - r * 1.6) <= stand_w and d > 0:
            return FG
        # stand
        foot = bottom + r * 1.6 + s * 0.08
        if abs(px - cx) <= stand_w and bottom + r * 1.6 <= py <= foot:
            return FG
        if abs(py - foot) <= stand_w and abs(px - cx) <= s * 0.1:
            return FG
        return BG

    return png(size, size, pixel)


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, size, safe in [("apple-touch-icon.png", 180, 1.0), ("icon-192.png", 192, 1.0),
                             ("icon-512.png", 512, 1.0), ("icon-maskable-512.png", 512, 0.8)]:
        with open(os.path.join(OUT, name), "wb") as fh:
            fh.write(icon(size, safe))
        print("wrote", name)


if __name__ == "__main__":
    main()
