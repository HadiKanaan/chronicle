"""Demo/debug controls: /api/debug (set_time, set_faction, advance_hour,
trigger_dawn). Drives main.post_debug directly with a temp DB."""

from __future__ import annotations

import json

import pytest


def _region(width=8, height=8):
    return {
        "id": "region_aldenmoor", "name": "Aldenmoor", "width": width, "height": height,
        "biome": "temperate_forest",
        "tiles": [[{"x": x, "y": y, "tile_type": "grass", "passable": True}
                   for x in range(width)] for y in range(height)],
        "buildings": [], "current_weather": "clear", "season": "spring",
    }


def _seed_state(database, day=3, hour=10):
    database.save_world_state({
        "game_started": True, "current_day": day, "current_hour": hour,
        "player_npc_id": "npc_player", "region": _region(),
    })


def test_set_time_updates_and_clamps(temp_db):
    import main
    _seed_state(temp_db)
    main.post_debug(main.DebugInput(action="set_time", payload={"day": 9, "hour": 14}))
    state = temp_db.get_world_state()
    assert state["current_day"] == 9 and state["current_hour"] == 14
    # Hour clamps into 0..23, day floors at 1.
    main.post_debug(main.DebugInput(action="set_time", payload={"day": -5, "hour": 99}))
    state = temp_db.get_world_state()
    assert state["current_day"] == 1 and state["current_hour"] == 23


def test_set_faction_sets_and_clamps_reputation_and_morale(temp_db):
    import main
    _seed_state(temp_db)
    temp_db.save_faction({"id": "faction_watch", "name": "Aldenmoor Watch",
                          "faction_type": "civic", "description": "", "color": "#fff",
                          "player_reputation": 50, "morale": 60})
    # By display name, with clamping.
    main.post_debug(main.DebugInput(action="set_faction",
                                    payload={"faction": "Aldenmoor Watch", "reputation": 200, "morale": -10}))
    watch = temp_db.get_faction("faction_watch")
    assert watch["player_reputation"] == 100 and watch["morale"] == 0
    # By id too.
    main.post_debug(main.DebugInput(action="set_faction",
                                    payload={"faction": "faction_watch", "reputation": 42}))
    assert temp_db.get_faction("faction_watch")["player_reputation"] == 42


def test_set_faction_unknown_is_404(temp_db):
    import main
    from fastapi import HTTPException
    _seed_state(temp_db)
    with pytest.raises(HTTPException) as exc:
        main.post_debug(main.DebugInput(action="set_faction", payload={"faction": "void"}))
    assert exc.value.status_code == 404


def test_unknown_action_is_400(temp_db):
    import main
    from fastapi import HTTPException
    _seed_state(temp_db)
    with pytest.raises(HTTPException) as exc:
        main.post_debug(main.DebugInput(action="nonsense"))
    assert exc.value.status_code == 400


def test_clear_history_wipes_transcripts(temp_db):
    import main
    _seed_state(temp_db)
    temp_db.save_npc({"id": "npc_a", "tier": 1, "name": "A",
                      "conversation_history": [{"player_text": "hi", "npc_response": "ho"}]})
    temp_db.save_npc({"id": "npc_b", "tier": 1, "name": "B",
                      "conversation_history": [{"player_text": "x", "npc_response": "y"}]})
    # One NPC by id.
    out = main.post_debug(main.DebugInput(action="clear_history", payload={"npc_id": "npc_a"}))
    assert json.loads(out.body)["cleared"] == 1
    assert temp_db.get_npc("npc_a")["conversation_history"] == []
    assert temp_db.get_npc("npc_b")["conversation_history"] != []
    # All NPCs when no id is given.
    main.post_debug(main.DebugInput(action="clear_history"))
    assert temp_db.get_npc("npc_b")["conversation_history"] == []


def test_trigger_dawn_advances_to_dawn_and_runs_batch(temp_db, monkeypatch):
    import main
    from systems import world_gen
    world_gen.generate_world(seed=42)
    monkeypatch.setattr(main, "_tick_rng", __import__("random").Random(5))

    response = main.post_debug(main.DebugInput(action="trigger_dawn"))
    assert json.loads(response.body)["status"] == "ok"

    state = temp_db.get_world_state()
    assert state["current_hour"] == 6  # advanced 5 -> 6 (dawn)
    # The dawn ML batch ran: faction relationships captured their Day-2 seed.
    rels = temp_db.get_faction_relationships()
    assert rels and all("seed_score" in r for r in rels)
