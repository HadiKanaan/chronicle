"""Day 7 checks: fog of war (T038), the static/mutable save/load split and full
round-trip (T039/T040), and the visual-only continent overlay (added scope).

No test talks to a real server or LLM. Continent generation runs the real
numpy/scipy/scikit-learn pipeline (deterministic via a fixed seed), so these
also exercise the reused biome/civ models and the Country Property Generator.
"""

from __future__ import annotations

import json


def _minimal_region(width: int = 6, height: int = 6) -> dict:
    return {
        "id": "region_test",
        "name": "Testmoor",
        "width": width,
        "height": height,
        "biome": "temperate_forest",
        "tiles": [
            [{"x": x, "y": y, "tile_type": "grass", "passable": True} for x in range(width)]
            for y in range(height)
        ],
        "buildings": [
            {"id": "bld_x", "name": "House", "building_type": "house",
             "x": 1, "y": 1, "width": 2, "height": 2, "owner_npc_id": None}
        ],
        "current_weather": "clear",
        "season": "spring",
    }


# --------------------------------------------------------------------------- #
# Save/load split (T039) - tiles persisted once, mutable state stays hot
# --------------------------------------------------------------------------- #
def test_static_grid_persisted_once_and_merged_back(temp_db):
    region = _minimal_region()
    state = {"game_started": True, "current_day": 1, "current_hour": 6, "region": region}
    temp_db.save_world_state(state)

    # The immutable grid lives in region_static, not the hot world-state blob.
    static = temp_db.get_region_static()
    assert static["tiles"] == region["tiles"]
    assert static["buildings"] == region["buildings"]
    with temp_db._connect() as connection:
        raw = connection.execute("SELECT data FROM world_state WHERE id = 1").fetchone()["data"]
    blob = json.loads(raw)
    assert "tiles" not in blob["region"]
    assert "buildings" not in blob["region"]

    # get_world_state merges the grid back so callers still see full tiles.
    loaded = temp_db.get_world_state()
    assert loaded["region"]["tiles"] == region["tiles"]
    assert loaded["region"]["buildings"] == region["buildings"]


def test_hourly_resave_keeps_tiles_immutable_and_updates_mutable(temp_db):
    region = _minimal_region()
    temp_db.save_world_state(
        {"game_started": True, "current_day": 1, "current_hour": 6, "region": region}
    )
    loaded = temp_db.get_world_state()
    loaded["current_hour"] = 7
    loaded["region"]["current_weather"] = "storm"
    temp_db.save_world_state(loaded)

    again = temp_db.get_world_state()
    assert again["current_hour"] == 7
    assert again["region"]["current_weather"] == "storm"
    assert again["region"]["tiles"] == region["tiles"]  # never rewritten


def test_world_state_roundtrip_preserves_day5_6_7_fields(temp_db):
    region = _minimal_region()
    state = {
        "game_started": True,
        "current_day": 12,
        "current_hour": 18,
        "player_npc_id": "npc_player",
        "demon_lord_npc_id": "npc_demon_lord",
        "demon_lord_decisions": [{"day": 11, "action_type": "spread_fear", "summary": "Day 11: fear"}],
        "explored_tiles": ["1,1", "2,2", "3,3"],
        "region": region,
    }
    temp_db.save_world_state(state)
    loaded = temp_db.get_world_state()
    for field in (
        "current_day", "current_hour", "player_npc_id", "demon_lord_npc_id",
        "demon_lord_decisions", "explored_tiles",
    ):
        assert loaded[field] == state[field]


def test_legacy_world_with_embedded_tiles_heals_into_region_static(temp_db):
    # Pre-Day-7 rows embedded the tile grid in the world-state blob and had no
    # region_static. The first load must still return tiles; the next save then
    # populates region_static and slims the blob.
    region = _minimal_region()
    legacy = {"game_started": True, "current_day": 1, "current_hour": 6, "region": region}
    with temp_db._connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO world_state (id, data) VALUES (1, ?)",
            (json.dumps(legacy),),
        )
    assert temp_db.get_region_static() is None

    loaded = temp_db.get_world_state()  # tiles still present from the blob
    assert loaded["region"]["tiles"] == region["tiles"]

    temp_db.save_world_state(loaded)  # migrate
    assert temp_db.get_region_static()["tiles"] == region["tiles"]


def test_clear_world_drops_static_grid_for_regeneration(temp_db):
    temp_db.save_world_state(
        {"game_started": True, "current_day": 1, "current_hour": 6, "region": _minimal_region()}
    )
    assert temp_db.get_region_static() is not None
    temp_db.clear_world()
    assert temp_db.get_region_static() is None
    assert temp_db.get_world_state() is None


# --------------------------------------------------------------------------- #
# Fog of war (T038)
# --------------------------------------------------------------------------- #
def test_visible_tile_keys_is_a_generous_circle():
    import main

    region = {"width": 40, "height": 40}
    keys = main._visible_tile_keys(region, 20.0, 20.0)
    assert "20,20" in keys                      # the host's own tile
    assert "20,9" in keys                        # ~11 tiles north is still seen
    assert "0,0" not in keys                     # far corner is not
    # No out-of-bounds keys leak in.
    assert all(0 <= int(k.split(",")[0]) < 40 and 0 <= int(k.split(",")[1]) < 40 for k in keys)


def test_build_fog_map_tiers_and_persists_exploration(temp_db, monkeypatch):
    import main

    monkeypatch.setattr(main, "_reveal_all", False)
    region = _minimal_region(width=40, height=40)
    state = {
        "game_started": True, "current_day": 1, "current_hour": 6,
        "player_npc_id": "npc_p", "region": region,
        "explored_tiles": ["39,0"],  # a far tile seen on a previous life
    }
    temp_db.save_world_state(state)

    host = {"id": "npc_p", "x": 5.0, "y": 5.0}
    fog = main._build_fog_map(temp_db.get_world_state(), region, host)
    tiers = {(cell["x"], cell["y"]): cell["fog_tier"] for cell in fog}

    assert (5, 5) not in tiers              # within the radius: visible (omitted)
    assert tiers[(39, 39)] == "unexplored"  # never seen
    assert tiers[(39, 0)] == "explored"     # seen before, not in view now

    # The newly-seen tiles are folded into the persisted exploration set.
    saved = temp_db.get_world_state()
    assert "5,5" in saved["explored_tiles"]
    assert "39,0" in saved["explored_tiles"]  # prior exploration preserved


def test_reveal_all_clears_the_fog(temp_db, monkeypatch):
    import main

    monkeypatch.setattr(main, "_reveal_all", True)
    region = _minimal_region(width=20, height=20)
    state = {
        "game_started": True, "current_day": 1, "current_hour": 6,
        "player_npc_id": "npc_p", "region": region, "explored_tiles": [],
    }
    temp_db.save_world_state(state)
    fog = main._build_fog_map(temp_db.get_world_state(), region, {"id": "npc_p", "x": 1.0, "y": 1.0})
    assert fog == []  # whole map reads as visible


def test_toggle_reveal_input_flips_the_flag():
    import main

    main._reveal_all = False
    response = main.post_input(main.PlayerInput(type="toggle_reveal"))
    assert json.loads(response.body)["reveal_all"] is True
    main.post_input(main.PlayerInput(type="toggle_reveal"))
    assert main._reveal_all is False


# --------------------------------------------------------------------------- #
# Continent overlay (added scope, visual only)
# --------------------------------------------------------------------------- #
def test_continent_persistence_roundtrip(temp_db):
    assert temp_db.get_continent() is None
    data = {"width": 3, "height": 2, "cells": [], "countries": []}
    temp_db.save_continent(data)
    assert temp_db.get_continent()["width"] == 3


def test_generate_continent_shape_and_features():
    from systems import continent

    payload = continent.generate_continent()
    assert len(payload["cells"]) == payload["width"] * payload["height"]
    assert any(cell["land"] for cell in payload["cells"])
    assert any(not cell["land"] for cell in payload["cells"])  # ringed by sea
    assert len(payload["countries"]) >= 1
    assert payload["aldenmoor"]["label"].startswith("Aldenmoor")
    for country in payload["countries"]:
        assert {"naval_power", "timber", "agriculture", "mineral_wealth",
                "military", "population"}.issubset(country["properties"])
        assert "name" in country and "capital" in country


def test_continent_biomes_are_2d_not_latitude_bands():
    """Biomes must form regions, not pure horizontal latitude stripes.

    The old climate model made temperature a function of y only, so every row was
    a single biome (~1.0 distinct biomes/row). Temperature is now driven by a 2D
    warmth field (plus a lowland-wetland overlay), so rows mix biomes.
    """
    from collections import defaultdict

    from systems import continent

    payload = continent.generate_continent()
    assert payload.get("version") == continent.CONTINENT_VERSION
    land = [c for c in payload["cells"] if c["land"]]
    biomes = {c["biome"] for c in land}
    # More than a two-band map: at least three distinct biomes appear.
    assert len(biomes) >= 3

    rows = defaultdict(set)
    for c in land:
        rows[c["y"]].add(c["biome"])
    avg_per_row = sum(len(s) for s in rows.values()) / max(1, len(rows))
    # Pure bands score 1.0; regions score well above it.
    assert avg_per_row > 1.3


def test_country_property_constraints_are_enforced():
    from ml import train as ml

    model = ml.train_country_property_model()
    landlocked = ml.generate_country_properties(
        model, coastal=False, aridity=0.2, elevation=0.5, size=0.3, forest=0.8
    )
    assert landlocked["naval_power"] == 0  # a landlocked nation has no navy

    arid = ml.generate_country_properties(
        model, coastal=True, aridity=0.9, elevation=0.4, size=0.3, forest=0.2
    )
    assert arid["timber"] <= 5  # an arid nation has no forests

    # The deterministic fallback (no model) honors the same constraints.
    fallback = ml.generate_country_properties(
        None, coastal=False, aridity=0.9, elevation=0.5, size=0.3, forest=0.5
    )
    assert fallback["naval_power"] == 0 and fallback["timber"] <= 5
