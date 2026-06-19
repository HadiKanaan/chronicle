"""Static town-prop layer (Day 8 / visual flavor).

Scatters a few props (barrels, crates, haystacks, lamp posts, signs, the odd
well) on the open grass immediately around each building, so the town reads as
lived-in rather than a set of bare houses. Generated once at world generation
and persisted in ``region_static`` next to the decoration and path layers (see
``database.save_region_props``); purely cosmetic and surfaced read-only.

Props avoid anything already placed - building tiles, paths, decorations, and
NPC home/work tiles - so nothing overlaps. Seeded, so a given world always
dresses itself identically.
"""

from __future__ import annotations

import random
from typing import Any

# Weighted prop palette - everyday clutter common, wells rare.
_PROP_WEIGHTS = [
    ("barrel", 24),
    ("crate", 20),
    ("haystack", 20),
    ("lamp", 16),
    ("sign", 12),
    ("well", 8),
]

# Tiles outward from a building footprint to consider, and props per building.
_MARGIN = 2
_MIN_PER_BUILDING = 1
_MAX_PER_BUILDING = 3
_PROP_SEED = 71523


def _occupied_tiles(
    npcs: list[dict[str, Any]],
    decorations: list[dict[str, Any]],
    paths: list[dict[str, Any]],
) -> set[tuple[int, int]]:
    occupied: set[tuple[int, int]] = set()
    for item in (*decorations, *paths):
        occupied.add((int(item["x"]), int(item["y"])))
    for npc in npcs:
        for kx, ky in (("home_x", "home_y"), ("work_x", "work_y")):
            x, y = npc.get(kx), npc.get(ky)
            if x is not None and y is not None:
                occupied.add((int(round(float(x))), int(round(float(y)))))
    return occupied


def generate_props(
    region: dict[str, Any],
    npcs: list[dict[str, Any]],
    decorations: list[dict[str, Any]],
    paths: list[dict[str, Any]],
    seed: int = _PROP_SEED,
) -> list[dict[str, Any]]:
    """Return a deterministic list of ``{prop_type, x, y}`` dicts placed on open
    grass around buildings, avoiding all occupied tiles. Row-major sorted and
    stable for a given (region, npcs, decorations, paths, seed)."""
    tiles = region.get("tiles") or []
    height = len(tiles)
    width = len(tiles[0]) if height else 0
    occupied = _occupied_tiles(npcs, decorations, paths)
    rng = random.Random(seed)

    types = [t for t, _ in _PROP_WEIGHTS]
    weights = [w for _, w in _PROP_WEIGHTS]

    props: list[dict[str, Any]] = []
    # Deterministic building order so the seeded placement is reproducible.
    for b in sorted(region.get("buildings", []) or [], key=lambda b: (int(b["y"]), int(b["x"]))):
        bx, by, bw, bh = int(b["x"]), int(b["y"]), int(b["width"]), int(b["height"])
        candidates: list[tuple[int, int]] = []
        for y in range(max(0, by - _MARGIN), min(height, by + bh + _MARGIN)):
            for x in range(max(0, bx - _MARGIN), min(width, bx + bw + _MARGIN)):
                tile = tiles[y][x]
                if tile.get("tile_type") == "grass" and tile.get("passable", False) and (x, y) not in occupied:
                    candidates.append((x, y))
        if not candidates:
            continue
        count = min(len(candidates), rng.randint(_MIN_PER_BUILDING, _MAX_PER_BUILDING))
        for (x, y) in rng.sample(candidates, count):
            prop_type = rng.choices(types, weights=weights)[0]
            props.append({"prop_type": prop_type, "x": x, "y": y})
            occupied.add((x, y))  # never stack two props on one tile

    props.sort(key=lambda p: (p["y"], p["x"]))
    return props
