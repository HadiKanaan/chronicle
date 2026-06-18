"""Static decoration layer (Day 8 / visual flavor).

Generates a deterministic scatter of trees, bushes, and rocks across the
region's open grass, computed ONCE at world generation and persisted alongside
the tile grid in ``region_static`` (see ``database.save_region_decorations``).

This is purely cosmetic data: decorations carry no simulation meaning, never
change after generation, and are surfaced read-only in the render payload. The
generator is seeded so the same world always yields the same scatter - the
frontend can poll twice and never see a decoration flicker or jump.

Decorations only land on passable grass that is not a building, path, water, or
an NPC's home/work tile, so they never obscure structures or sit where a
villager stands at dawn.
"""

from __future__ import annotations

import random
from typing import Any

# Weighted decoration palette. Trees dominate (the town sits in a temperate
# valley), with bushes and rocks for variety.
_DECORATION_WEIGHTS = [
    ("tree", 52),
    ("bush", 30),
    ("rock", 18),
]

# Fraction of eligible grass tiles that receive a decoration. Dense enough to
# frame the town in greenery, sparse enough to leave open ground to walk.
_DECORATION_DENSITY = 0.07

# Fixed seed so a given region always scatters identically (the data is
# persisted anyway; this just makes regeneration reproducible too).
_DECORATION_SEED = 20240608


def _occupied_npc_tiles(npcs: list[dict[str, Any]]) -> set[tuple[int, int]]:
    """Home and work tiles for every NPC - kept clear so decorations never sit
    where a villager spawns or labors."""
    occupied: set[tuple[int, int]] = set()
    for npc in npcs:
        for kx, ky in (("home_x", "home_y"), ("work_x", "work_y")):
            x, y = npc.get(kx), npc.get(ky)
            if x is not None and y is not None:
                occupied.add((int(round(float(x))), int(round(float(y)))))
    return occupied


def generate_decorations(
    region: dict[str, Any],
    npcs: list[dict[str, Any]],
    seed: int = _DECORATION_SEED,
) -> list[dict[str, Any]]:
    """Return a deterministic list of ``{decoration_type, x, y}`` dicts.

    Only passable grass tiles that are not occupied by a building, path, water,
    or an NPC home/work tile are eligible. Output is ordered (row-major) and
    stable for a given (region, npcs, seed), so repeated calls are identical.
    """
    tiles = region.get("tiles") or []
    occupied = _occupied_npc_tiles(npcs)
    rng = random.Random(seed)

    types = [t for t, _ in _DECORATION_WEIGHTS]
    weights = [w for _, w in _DECORATION_WEIGHTS]

    decorations: list[dict[str, Any]] = []
    for row in tiles:
        for tile in row:
            if tile.get("tile_type") != "grass" or not tile.get("passable", False):
                continue
            x, y = int(tile.get("x", 0)), int(tile.get("y", 0))
            if (x, y) in occupied:
                continue
            if rng.random() >= _DECORATION_DENSITY:
                continue
            decoration_type = rng.choices(types, weights=weights)[0]
            decorations.append({"decoration_type": decoration_type, "x": x, "y": y})
    return decorations
