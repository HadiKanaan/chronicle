"""Reproducible Day 8 asset setup (run via `uv run --with pillow python tools/setup_assets.py`).

The PNGs under frontend/public/assets/ are gitignored, so the *selection* of
which raw pack sprite becomes which game asset would otherwise live only in
shell history. This script encodes that selection in committed code: it copies
the chosen sprites out of the (gitignored) asset packs at the CHRONICLE root,
crops/trims them, and lays them down with the exact filenames the renderer's
atlases expect. Run it once after cloning, or any time the local assets are
lost - a freshly generated world then looks identical out of the box.

It is idempotent: every run re-copies from the pristine pack sources and
re-trims, so the result is deterministic regardless of prior state.

NOTE: the Day 3 terrain + character assets (assets/tiles/*, assets/characters/*)
predate this script and are assumed already present. Only the Day 8 additions
- building sprites, decoration props, the door, and the kenney RTS spritesheet
used for road tiles - are (re)built here.
"""

from __future__ import annotations

import os
import shutil

from PIL import Image

# .../CHRONICLE/chronicle/backend/tools/setup_assets.py -> CHRONICLE (pack root)
HERE = os.path.dirname(os.path.abspath(__file__))
PACK_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
ASSETS = os.path.abspath(os.path.join(HERE, "..", "..", "frontend", "public", "assets"))

KENNEY = os.path.join(PACK_ROOT, "kenney_medieval-rts", "PNG", "Default size")
KENNEY_STRUCT = os.path.join(KENNEY, "Structure")
KENNEY_ENV = os.path.join(KENNEY, "Environment")
KENNEY_SHEET = os.path.join(PACK_ROOT, "kenney_medieval-rts", "Spritesheet", "medievalRTS_spritesheet.png")
FANTASY_DOOR = os.path.join(
    PACK_ROOT, "The Fan-tasy Tileset (Free) 1.5.7", "The Fan-tasy Tileset (Free)",
    "Art", "Buildings", "Animations", "Door_Normal_Wood.png",
)

# building_type -> source structure sprite (chosen by eye for role-readability:
# barrel/sign tavern, forge-chimney smithy, striped market stall, cross chapel,
# crenellated gatehouse hall, simple green-roof cottage).
BUILDINGS = {
    "tavern": "medievalStructure_23.png",
    "blacksmith": "medievalStructure_20.png",
    "market": "medievalStructure_22.png",
    "church": "medievalStructure_04.png",
    "magistrate_hall": "medievalStructure_02.png",
    "house": "medievalStructure_16.png",
}

# decoration_type -> source environment sprite.
DECORATIONS = {
    "tree": "medievalEnvironment_04.png",
    "bush": "medievalEnvironment_01.png",
    "rock": "medievalEnvironment_09.png",
}


def _trim(img: Image.Image) -> Image.Image:
    """Crop transparent padding so the draw scales the art, not the empty frame."""
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def _copy_trimmed(src: str, dst: str) -> None:
    img = _trim(Image.open(src).convert("RGBA"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    img.save(dst)
    print(f"  {os.path.basename(dst):22s} <- {os.path.basename(src):26s} {img.size}")


def main() -> None:
    print(f"pack root : {PACK_ROOT}")
    print(f"assets    : {ASSETS}")

    print("buildings:")
    for name, src in BUILDINGS.items():
        _copy_trimmed(os.path.join(KENNEY_STRUCT, src), os.path.join(ASSETS, "buildings", f"{name}.png"))

    print("decorations:")
    for name, src in DECORATIONS.items():
        _copy_trimmed(os.path.join(KENNEY_ENV, src), os.path.join(ASSETS, "decorations", f"{name}.png"))

    print("door:")
    # First frame (closed door) of the Fan-tasy door animation strip, trimmed.
    door = _trim(Image.open(FANTASY_DOOR).convert("RGBA").crop((0, 0, 16, 26)))
    door_dst = os.path.join(ASSETS, "buildings", "door.png")
    door.save(door_dst)
    print(f"  {'door.png':22s} <- Door_Normal_Wood.png[0]   {door.size}")

    print("spritesheet (road tiles):")
    sheet_dst = os.path.join(ASSETS, "tiles", "kenney_rts.png")
    os.makedirs(os.path.dirname(sheet_dst), exist_ok=True)
    shutil.copyfile(KENNEY_SHEET, sheet_dst)
    print(f"  {'kenney_rts.png':22s} <- medievalRTS_spritesheet.png")

    print("done.")


if __name__ == "__main__":
    main()
