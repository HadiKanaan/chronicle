"""Day 8 checks: the visual-flavor payload additions.

These cover the only backend surface Day 8 touches - surfacing `buildings` and
the static decoration scatter in the render payload, and persisting decorations
once into region_static. The frontend draw layers (sprites, NPC lerp, weather)
are render-only and carry no backend behavior to test.

No test talks to a real server or LLM; decoration generation is pure/seeded.
"""

from __future__ import annotations

import json

from systems import decorations, paths


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
        "building_type": "house", "x": 2, "y": 2, "width": 4, "height": 4,
        # entrance tile = bottom-centre, matching world_gen._carve_building.
        "door_x": 4, "door_y": 5,
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


# --------------------------------------------------------------------------- #
# NPC sprite variety - display-only mapping, no stored data mutated
# --------------------------------------------------------------------------- #
def test_display_sprite_maps_by_occupation():
    import main
    assert main._display_sprite({"occupation": "guard"}) == "npc_knight"
    assert main._display_sprite({"occupation": "magistrate"}) == "npc_knight"
    assert main._display_sprite({"occupation": "priest"}) == "npc_wizard"
    assert main._display_sprite({"occupation": "merchant"}) == "npc_rogue"
    # Unmapped roles fall back to the base villager.
    assert main._display_sprite({"occupation": "farmer"}) == "human_base"
    # A deliberately-assigned sprite (e.g. the Demon Lord) is preserved.
    assert main._display_sprite({"occupation": "warlord", "sprite_id": "npc_wizard"}) == "npc_wizard"


# --------------------------------------------------------------------------- #
# Path network - connects building doors over walkable ground only
# --------------------------------------------------------------------------- #
def _two_building_region(size: int = 16) -> dict:
    """Open grass with two carved buildings (walls + a stone door each), so the
    road router has two reachable entrances to connect."""
    tiles = [
        [{"x": x, "y": y, "tile_type": "grass", "passable": True} for x in range(size)]
        for y in range(size)
    ]
    buildings = []
    for bx, by, w, h, bid in [(2, 2, 3, 3, "bld_a"), (10, 10, 3, 3, "bld_b")]:
        for yy in range(by, by + h):
            for xx in range(bx, bx + w):
                border = xx in (bx, bx + w - 1) or yy in (by, by + h - 1)
                tiles[yy][xx]["tile_type"] = "building_wall" if border else "building_floor"
                tiles[yy][xx]["passable"] = not border
        dx, dy = bx + w // 2, by + h - 1
        tiles[dy][dx]["tile_type"] = "stone_path"
        tiles[dy][dx]["passable"] = True
        buildings.append({"id": bid, "name": bid, "building_type": "house",
                          "x": bx, "y": by, "width": w, "height": h, "owner_npc_id": None})
    return {
        "id": "region_test", "name": "Testmoor", "width": size, "height": size,
        "biome": "temperate_forest", "tiles": tiles, "buildings": buildings,
        "current_weather": "clear", "season": "spring",
    }


def test_paths_connect_doors_over_walkable_ground():
    region = _two_building_region()
    network = paths.generate_paths(region)
    assert network, "expected a road network between two reachable buildings"

    coords = {(p["x"], p["y"]) for p in network}
    assert (3, 4) in coords and (11, 12) in coords  # both door tiles on the road

    tile_at = {(t["x"], t["y"]): t for row in region["tiles"] for t in row}
    for x, y in coords:
        tile = tile_at[(x, y)]
        assert tile["tile_type"] in {"grass", "dirt", "stone_path"}, "road off walkable ground"
        assert tile["passable"], "road on an impassable tile"


def test_paths_stable_across_calls():
    region = _two_building_region()
    assert paths.generate_paths(region) == paths.generate_paths(region)


def test_paths_persist_and_surface_in_payload(temp_db):
    region = _two_building_region()
    temp_db.save_world_state(
        {"game_started": True, "current_day": 1, "current_hour": 6,
         "player_npc_id": None, "region": region}
    )
    network = paths.generate_paths(region)
    temp_db.save_region_paths(network)

    assert temp_db.get_region_paths() == network
    # The decoration write path and the path write must not clobber each other.
    temp_db.save_region_decorations([{"decoration_type": "tree", "x": 0, "y": 0}])
    assert temp_db.get_region_paths() == network

    import main
    assert main._build_render_payload().paths == network
