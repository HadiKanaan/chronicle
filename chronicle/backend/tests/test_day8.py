"""Day 8 checks: the visual-flavor payload additions.

These cover the only backend surface Day 8 touches - surfacing `buildings` and
the static decoration scatter in the render payload, and persisting decorations
once into region_static. The frontend draw layers (sprites, NPC lerp, weather)
are render-only and carry no backend behavior to test.

No test talks to a real server or LLM; decoration generation is pure/seeded.
"""

from __future__ import annotations

import json

from systems import decorations


def _mixed_region(width: int = 20, height: int = 20) -> dict:
    """A grass field with a building block, a path strip, and a water column -
    so eligibility (grass + passable, none of the others) is actually exercised."""
    tiles = [
        [{"x": x, "y": y, "tile_type": "grass", "passable": True} for x in range(width)]
        for y in range(height)
    ]
    # Building footprint (walls non-passable, floor passable but not grass).
    for yy in range(2, 6):
        for xx in range(2, 6):
            border = xx in (2, 5) or yy in (2, 5)
            tiles[yy][xx]["tile_type"] = "building_wall" if border else "building_floor"
            tiles[yy][xx]["passable"] = not border
    # A stone path strip (only where it fits).
    if height > 10:
        for xx in range(8, min(14, width)):
            tiles[10][xx]["tile_type"] = "stone_path"
    # A water column (impassable), only where it fits.
    if width > 16:
        for yy in range(height):
            tiles[yy][16]["tile_type"] = "water"
            tiles[yy][16]["passable"] = False
    return {
        "id": "region_test",
        "name": "Testmoor",
        "width": width,
        "height": height,
        "biome": "temperate_forest",
        "tiles": tiles,
        "buildings": [
            {"id": "bld_x", "name": "House", "building_type": "house",
             "x": 2, "y": 2, "width": 4, "height": 4, "owner_npc_id": None}
        ],
        "current_weather": "clear",
        "season": "spring",
    }


# --------------------------------------------------------------------------- #
# Decoration generation - eligibility + determinism
# --------------------------------------------------------------------------- #
def test_decorations_only_on_open_grass_avoiding_occupied():
    region = _mixed_region()
    # NPC sitting on an otherwise-eligible grass tile - must be left clear.
    npcs = [{"id": "npc_0", "home_x": 9.0, "home_y": 3.0, "work_x": 12.0, "work_y": 18.0}]
    decs = decorations.generate_decorations(region, npcs)

    assert decs, "expected at least some decorations on a 20x20 grass field"
    grass = {
        (t["x"], t["y"])
        for row in region["tiles"] for t in row
        if t["tile_type"] == "grass" and t["passable"]
    }
    occupied = {(9, 3), (12, 18)}
    for dec in decs:
        assert dec["decoration_type"] in {"tree", "bush", "rock"}
        pos = (dec["x"], dec["y"])
        assert pos in grass, f"decoration on non-grass/occupied tile {pos}"
        assert pos not in occupied, f"decoration on NPC home/work tile {pos}"


def test_decorations_stable_across_calls():
    region = _mixed_region()
    npcs = [{"id": "npc_0", "home_x": 9.0, "home_y": 3.0, "work_x": 12.0, "work_y": 18.0}]
    first = decorations.generate_decorations(region, npcs)
    second = decorations.generate_decorations(region, npcs)
    assert first == second, "seeded scatter must be identical across calls"


# --------------------------------------------------------------------------- #
# Persistence - folded into region_static without clobbering tiles/buildings
# --------------------------------------------------------------------------- #
def test_save_decorations_preserves_static_grid(temp_db):
    region = _mixed_region(6, 6)
    state = {"game_started": True, "current_day": 1, "current_hour": 6, "region": region}
    temp_db.save_world_state(state)  # persists tiles + buildings into region_static

    scatter = [{"decoration_type": "tree", "x": 0, "y": 0}]
    temp_db.save_region_decorations(scatter)

    assert temp_db.get_region_decorations() == scatter
    # The earlier static grid must survive the decoration write.
    static = temp_db.get_region_static()
    assert static["tiles"] == region["tiles"]
    assert static["buildings"] == region["buildings"]
    assert static["decorations"] == scatter


def test_get_decorations_empty_before_generation(temp_db):
    assert temp_db.get_region_decorations() == []


# --------------------------------------------------------------------------- #
# Render payload surfaces buildings + decorations (display-ready only)
# --------------------------------------------------------------------------- #
def test_render_payload_includes_buildings_and_decorations(temp_db):
    region = _mixed_region(8, 8)
    state = {
        "game_started": True, "current_day": 2, "current_hour": 8,
        "player_npc_id": None, "region": region,
    }
    temp_db.save_world_state(state)
    scatter = [
        {"decoration_type": "tree", "x": 1, "y": 1},
        {"decoration_type": "rock", "x": 7, "y": 7},
    ]
    temp_db.save_region_decorations(scatter)

    import main
    payload = main._build_render_payload()

    assert payload.decorations == scatter
    assert payload.buildings, "payload should surface building footprints"
    building = payload.buildings[0]
    assert building == {
        "building_type": "house", "x": 2, "y": 2, "width": 4, "height": 4
    }
    # Simulation-only fields must NOT leak into the display dict.
    assert "id" not in building and "owner_npc_id" not in building


# --------------------------------------------------------------------------- #
# Manual pause - sticky hold on the world clock, surfaced for the UI
# --------------------------------------------------------------------------- #
def test_manual_pause_freezes_clock_and_surfaces_in_payload(temp_db):
    region = _mixed_region(6, 6)
    temp_db.save_world_state(
        {"game_started": True, "current_day": 1, "current_hour": 6,
         "player_npc_id": None, "region": region}
    )

    import main
    # A clean world with no dialogue/decision in flight is not frozen.
    main._manual_pause = False
    main._dialogue_freeze_until = 0.0
    try:
        assert main._world_frozen() is False
        assert main._build_render_payload().manually_paused is False

        # Engaging the manual pause both freezes the tick loop and shows up in
        # the payload so the UI can render a paused state + Resume control.
        main._manual_pause = True
        assert main._world_frozen() is True
        payload = main._build_render_payload()
        assert payload.manually_paused is True
        assert payload.world_paused is True
    finally:
        main._manual_pause = False
