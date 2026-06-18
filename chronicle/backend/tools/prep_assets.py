"""One-off asset prep for the Day 8 visual pass (run via `uv run --with pillow`).

The kenney structure/environment PNGs are 64x64 with heavy transparent padding,
so drawing the frame at ~1 tile made trees tiny and buildings sit oddly in their
footprints. This trims each sprite to its opaque bounding box so the on-screen
draw scales the actual art, not the empty frame.

It also scans the Fan-tasy water tileset for the most solid, sand-free interior
cell (max blue coverage, fully opaque) and prints its pixel offset, so the river
uses open water instead of a shoreline cell.

Idempotent enough for a demo: re-trimming an already-trimmed sprite is a no-op
(its bbox already fills the frame). Assets are gitignored; this only rewrites the
local working copies.
"""

from __future__ import annotations

import glob
import os

from PIL import Image

ASSETS = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "public", "assets")


def trim(path: str) -> None:
    img = Image.open(path).convert("RGBA")
    bbox = img.getbbox()  # tight box around non-zero alpha
    if bbox and bbox != (0, 0, img.width, img.height):
        img.crop(bbox).save(path)
        print(f"trimmed {os.path.basename(path):20s} {img.size} -> {(bbox[2]-bbox[0], bbox[3]-bbox[1])}")
    else:
        print(f"kept    {os.path.basename(path):20s} {img.size} (already tight)")


def best_water_cell(path: str, cell: int = 16) -> None:
    img = Image.open(path).convert("RGBA")
    px = img.load()
    best = None  # (score, sx, sy)
    for cy in range(0, img.height - cell + 1, cell):
        for cx in range(0, img.width - cell + 1, cell):
            blue = 0
            opaque = 0
            for y in range(cy, cy + cell):
                for x in range(cx, cx + cell):
                    r, g, b, a = px[x, y]
                    if a < 250:
                        continue
                    opaque += 1
                    # "open water": blue dominant, not sandy (sand is r>=b).
                    if b > r + 20 and b > 110:
                        blue += 1
            if opaque < cell * cell:  # require a fully opaque cell
                continue
            score = blue
            if best is None or score > best[0]:
                best = (score, cx, cy)
    if best:
        print(f"BEST_WATER_CELL sx={best[1]} sy={best[2]} blue_px={best[0]}/{cell*cell}")


def main() -> None:
    for sub in ("buildings", "decorations"):
        for p in sorted(glob.glob(os.path.join(ASSETS, sub, "*.png"))):
            trim(p)
    best_water_cell(os.path.join(ASSETS, "tiles", "water.png"))


if __name__ == "__main__":
    main()
