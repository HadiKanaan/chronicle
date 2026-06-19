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

NOTE: the Day 3 terrain tiles (assets/tiles/ground|road|walls|floors|water.png)
predate this script and are assumed already present. The Day 8 additions
- building sprites, decoration props, the door, the kenney RTS spritesheet used
for road tiles, and the animated 6-frame character walk/run sheets - are
(re)built here.
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
PC = os.path.join(PACK_ROOT, "Pixel Crawler - Free Pack", "Entities")

# sprite_id -> source 6-frame, 64px walk/run sheet. Uniform layout (384x64) so
# every character type animates identically. Copied RAW (never trimmed - that
# would wreck frame alignment).
CHARACTERS = {
    "human_base.png": os.path.join(PC, "Characters", "Body_A", "Animations", "Walk_Base", "Walk_Down-Sheet.png"),
    "knight.png": os.path.join(PC, "Npc's", "Knight", "Run", "Run-Sheet.png"),
    "rogue.png": os.path.join(PC, "Npc's", "Rogue", "Run", "Run-Sheet.png"),
    "wizard.png": os.path.join(PC, "Npc's", "Wizzard", "Run", "Run-Sheet.png"),
}
FANTASY_ART = os.path.join(
    PACK_ROOT, "The Fan-tasy Tileset (Free) 1.5.7", "The Fan-tasy Tileset (Free)", "Art",
)
FANTASY_DOOR = os.path.join(FANTASY_ART, "Buildings", "Animations", "Door_Normal_Wood.png")

# Detailed Fan-tasy buildings (dest filename -> source). Two house variants for
# residential variety, the 2-storey inn as the tavern, the forge as the smithy.
FANTASY_BUILDINGS = {
    "house_1.png": "House_Hay_1.png",
    "house_2.png": "House_Hay_2.png",
    "tavern.png": "House_Hay_4_Purple.png",
    "blacksmith.png": "House_Hay_3.png",
}

# Kept as kenney structures for their distinct civic silhouettes (striped market
# stall, cross-topped chapel, crenellated gatehouse) the Fan-tasy set lacks.
KENNEY_BUILDINGS = {
    "market.png": "medievalStructure_22.png",
    "church.png": "medievalStructure_04.png",
    "magistrate_hall.png": "medievalStructure_02.png",
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

    print("buildings (Fan-tasy, detailed):")
    fantasy_buildings = os.path.join(FANTASY_ART, "Buildings")
    for name, src in FANTASY_BUILDINGS.items():
        _copy_trimmed(os.path.join(fantasy_buildings, src), os.path.join(ASSETS, "buildings", name))
    print("buildings (kenney, civic):")
    for name, src in KENNEY_BUILDINGS.items():
        _copy_trimmed(os.path.join(KENNEY_STRUCT, src), os.path.join(ASSETS, "buildings", name))

    print("decorations:")
    for name, src in DECORATIONS.items():
        _copy_trimmed(os.path.join(KENNEY_ENV, src), os.path.join(ASSETS, "decorations", f"{name}.png"))

    print("door:")
    # First frame (closed door) of the Fan-tasy door animation strip, trimmed.
    door = _trim(Image.open(FANTASY_DOOR).convert("RGBA").crop((0, 0, 16, 26)))
    door_dst = os.path.join(ASSETS, "buildings", "door.png")
    door.save(door_dst)
    print(f"  {'door.png':22s} <- Door_Normal_Wood.png[0]   {door.size}")

    print("spritesheet (kenney, fallback dirt tile):")
    sheet_dst = os.path.join(ASSETS, "tiles", "kenney_rts.png")
    os.makedirs(os.path.dirname(sheet_dst), exist_ok=True)
    shutil.copyfile(KENNEY_SHEET, sheet_dst)
    print(f"  {'kenney_rts.png':22s} <- medievalRTS_spritesheet.png")

    print("road autotile (Fan-tasy, 16-tile):")
    road_dst = os.path.join(ASSETS, "tiles", "road_tiles.png")
    shutil.copyfile(os.path.join(FANTASY_ART, "Ground Tileset", "Tileset_Road.png"), road_dst)
    print(f"  {'road_tiles.png':22s} <- Tileset_Road.png")

    print("characters (6-frame walk/run sheets, copied raw):")
    for name, src in CHARACTERS.items():
        dst = os.path.join(ASSETS, "characters", name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        print(f"  {name:22s} <- {os.path.basename(src)}")

    print("done.")


if __name__ == "__main__":
    main()
