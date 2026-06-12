"""Day 6 checks: rumor propagation/decay (US4) and the Demon Lord (US5).

No test talks to a real Ollama server: the LLM boundary is monkeypatched, and
spread randomness is forced through fake RNGs, so the suite stays fast and
deterministic. Live decision/dialogue quality is verified manually against the
running backend.
"""

from __future__ import annotations

import random

from systems import conversation, demon_lord, rumors


class AlwaysRng:
    """random() always below any positive gossip chance -> every whisper lands."""

    def random(self) -> float:
        return 0.0


class NeverRng:
    """random() always 1.0 -> nothing ever spreads."""

    def random(self) -> float:
        return 1.0


def _npc(npc_id, name=None, relationships=(), **overrides):
    npc = {
        "id": npc_id,
        "name": name or npc_id,
        "tier": 1,
        "occupation": "merchant",
        "personality_traits": ["curious"],
        "relationships": [
            {"npc_id": rid, "name": rid, "relationship_type": "friend", "sentiment": 50}
            for rid in relationships
        ],
        "rumor_knowledge": [],
        "current_mood": "neutral",
    }
    npc.update(overrides)
    return npc


def _rumor(rumor_id="rumor_d003_test", **overrides):
    rumor = {
        "id": rumor_id,
        "original_event": "something happened",
        "current_text": "something happened",
        "distortion_level": 0,
        "known_by_npc_ids": [],
        "propagation_rate": 0.5,
        "decay_rate": 0.05,
        "drama_score": 80,
        "age_days": 0,
        "active": True,
    }
    rumor.update(overrides)
    return rumor


# --------------------------------------------------------------------------- #
# Rumor propagation (T030/T032)
# --------------------------------------------------------------------------- #
def test_gossip_chance_scales_with_personality_and_drama():
    gossip = _npc("a", occupation="tavern_keeper", personality_traits=["curious"])
    reserved = _npc("b", occupation="guard_captain", personality_traits=["cautious"])
    juicy = _rumor(drama_score=95)
    dull = _rumor(drama_score=10)
    assert rumors.gossip_chance(gossip, juicy) > rumors.gossip_chance(reserved, juicy)
    assert rumors.gossip_chance(gossip, juicy) > rumors.gossip_chance(gossip, dull)
    assert 0.0 <= rumors.gossip_chance(gossip, juicy) <= rumors.MAX_GOSSIP_CHANCE


def test_propagation_spreads_across_relationships():
    teller = _npc("npc_a", relationships=["npc_b"])
    listener = _npc("npc_b")
    rumor = _rumor(known_by_npc_ids=["npc_a"])

    result = rumors.propagate_daily([teller, listener], [rumor], AlwaysRng())

    assert "npc_b" in rumor["known_by_npc_ids"]
    assert listener["rumor_knowledge"] == [rumor["id"]]
    assert result["spread_count"] == 1
    assert listener in result["npc_changes"]


def test_propagation_caps_tells_per_knower_per_day():
    relations = [f"npc_{i}" for i in range(1, 5)]
    teller = _npc("npc_0", relationships=relations)
    listeners = [_npc(rid) for rid in relations]
    rumor = _rumor(known_by_npc_ids=["npc_0"])

    result = rumors.propagate_daily([teller, *listeners], [rumor], AlwaysRng())

    assert result["spread_count"] == rumors.MAX_TELLS_PER_DAY


def test_player_and_demon_lord_stand_outside_the_gossip_network():
    teller = _npc("npc_a", relationships=["npc_player", "npc_demon"])
    player = _npc("npc_player", is_player=True)
    demon = _npc("npc_demon", is_demon_lord=True)
    rumor = _rumor(known_by_npc_ids=["npc_a"])

    result = rumors.propagate_daily([teller, player, demon], [rumor], AlwaysRng())

    assert result["spread_count"] == 0
    assert player["rumor_knowledge"] == []
    assert demon["rumor_knowledge"] == []


def test_rumors_age_decay_and_retire():
    fading = _rumor("rumor_fading", propagation_rate=0.06, decay_rate=0.05)
    stale = _rumor("rumor_stale", age_days=rumors.MAX_RUMOR_AGE_DAYS - 1)
    fresh = _rumor("rumor_fresh", propagation_rate=0.5, age_days=0)

    rumors.propagate_daily([], [fading, stale, fresh], NeverRng())

    assert fading["active"] is False  # rate decayed below the floor
    assert stale["active"] is False  # too old to matter
    assert fresh["active"] is True
    assert fresh["age_days"] == 1
    assert fresh["propagation_rate"] == 0.45


def test_propagation_backfills_witness_knowledge():
    # Pre-Day-6 rumors tracked known_by on the rumor only; the NPC side heals.
    witness = _npc("npc_a")
    rumor = _rumor(known_by_npc_ids=["npc_a"])

    result = rumors.propagate_daily([witness], [rumor], NeverRng())

    assert witness["rumor_knowledge"] == [rumor["id"]]
    assert witness in result["npc_changes"]


def test_seed_knowledge_marks_witnesses():
    witness = _npc("npc_a")
    other = _npc("npc_b")
    rumor = _rumor(known_by_npc_ids=["npc_a"])

    changed = rumors.seed_knowledge(rumor, {"npc_a": witness, "npc_b": other})

    assert changed == [witness]
    assert witness["rumor_knowledge"] == [rumor["id"]]
    assert other["rumor_knowledge"] == []


def test_known_rumor_texts_filters_orders_and_caps():
    npc = _npc("npc_a", rumor_knowledge=["rumor_d001_a", "rumor_d002_b", "rumor_d003_c", "rumor_d004_d"])
    active = [
        _rumor("rumor_d003_c", current_text="third"),
        _rumor("rumor_d001_a", current_text="first"),
        _rumor("rumor_d002_b", current_text="second"),
        _rumor("rumor_d004_d", current_text="fourth"),
        _rumor("rumor_d005_e", current_text="unknown to npc"),
    ]
    texts = rumors.known_rumor_texts(npc, active)
    assert texts == ["second", "third", "fourth"]  # newest 3, retired/unknown dropped


# --------------------------------------------------------------------------- #
# Rumor-aware dialogue (T033)
# --------------------------------------------------------------------------- #
def test_conversation_prompt_carries_actual_rumor_texts():
    npc = _npc("npc_a", name="Mara Vane", rumor_knowledge=["rumor_x"])
    block = conversation.build_situation_block(
        npc, "Aldric", rumor_texts=["Cultists struck the market stores."]
    )
    assert "Cultists struck the market stores." in block
    assert "rumor(s) lately" not in block  # the old count placeholder is gone


def test_conversation_prompt_without_rumors_stays_silent_about_them():
    block = conversation.build_situation_block(_npc("npc_a"), "Aldric", rumor_texts=[])
    assert "Rumors you have heard" not in block


# --------------------------------------------------------------------------- #
# Demon Lord card + decision parsing (T034)
# --------------------------------------------------------------------------- #
def _factions():
    return [
        {"id": "faction_watch", "name": "Aldenmoor Watch", "player_reputation": 50,
         "description": "The magistrate's guard."},
        {"id": "faction_guild", "name": "Merchants' Concord", "player_reputation": 50,
         "description": "A loose guild of traders."},
        {"id": "faction_church", "name": "Order of the Ashen Light", "player_reputation": 50,
         "description": "The dominant faith."},
        {"id": "faction_commons", "name": "The Commons", "player_reputation": 50,
         "description": "Folk with no other banner."},
    ]


def _region(width=8, height=8):
    return {
        "id": "region_aldenmoor",
        "width": width,
        "height": height,
        "tiles": [
            [{"x": x, "y": y, "passable": True} for x in range(width)]
            for y in range(height)
        ],
        "current_weather": "clear",
    }


def test_build_demon_lord_card_shape():
    card = demon_lord.build_demon_lord(_region())
    assert card["id"] == demon_lord.DEMON_LORD_ID
    assert card["is_demon_lord"] is True
    assert card["tier"] == 1
    assert card["llm_enriched"] is True  # hand-authored: skip enrichment pass
    assert 0 <= card["x"] < 8 and 0 <= card["y"] < 8


def test_match_faction_id_exact_then_fuzzy():
    factions = _factions()
    assert demon_lord.match_faction_id("faction_watch", factions) == "faction_watch"
    assert demon_lord.match_faction_id("watch", factions) == "faction_watch"
    assert demon_lord.match_faction_id("Aldenmoor Watch", factions) == "faction_watch"
    assert demon_lord.match_faction_id("the Merchants' Concord", factions) == "faction_guild"
    assert demon_lord.match_faction_id("guild", factions) == "faction_guild"
    assert demon_lord.match_faction_id("the dark brotherhood", factions) is None
    assert demon_lord.match_faction_id("", factions) is None
    assert demon_lord.match_faction_id(None, factions) is None


def test_parse_decision_valid_payload():
    raw = (
        '{"action_type": "raid_supplies", "target_faction": "faction_guild",'
        '"announcement": "Cultists struck the market.",'
        '"faction_reputation_effects": {"faction_guild": -6}}'
    )
    decision = demon_lord.parse_decision(raw, _factions())
    assert decision["action_type"] == "raid_supplies"
    assert decision["target_faction"] == "faction_guild"
    assert decision["faction_reputation_effects"] == {"faction_guild": -6}
    assert decision["used_llm"] is True


def test_parse_decision_rejects_unknown_action():
    raw = '{"action_type": "summon_dragon", "announcement": "Rawr."}'
    assert demon_lord.parse_decision(raw, _factions()) is None


def test_parse_decision_validates_effect_keys_exact_then_fuzzy_and_clamps():
    raw = (
        '{"action_type": "corrupt_official",'
        '"announcement": "Someone has turned.",'
        '"faction_reputation_effects": {'
        '"faction_watch": -20, "Merchants\' Concord": -3, "shadow_cabal": -5, "church": "bad"}}'
    )
    decision = demon_lord.parse_decision(raw, _factions())
    effects = decision["faction_reputation_effects"]
    assert effects["faction_watch"] == -demon_lord.REPUTATION_EFFECT_LIMIT  # clamped
    assert effects["faction_guild"] == -3  # display name fuzzily resolved
    assert "shadow_cabal" not in effects  # unknown key dropped
    assert len(effects) == 2  # non-integer value dropped too


def test_parse_decision_fills_default_effects_and_announcement():
    raw = '{"action_type": "dark_omen", "target_faction": "", "announcement": ""}'
    decision = demon_lord.parse_decision(raw, _factions())
    assert decision["announcement"]  # stub announcement substituted
    assert decision["faction_reputation_effects"] == demon_lord.ACTION_DEFAULT_EFFECTS["dark_omen"]


def test_generate_decision_rerolls_once_on_invalid_output(monkeypatch):
    responses = iter(
        [
            '{"action_type": "summon_dragon"}',  # invalid -> one re-roll
            '{"action_type": "spread_fear", "announcement": "Fear walks.",'
            '"faction_reputation_effects": {"faction_commons": -4}}',
        ]
    )
    calls = []
    monkeypatch.setattr(
        conversation, "_call_llm",
        lambda **kwargs: calls.append(1) or next(responses),
    )
    decision = demon_lord.generate_decision({}, {"region": {}}, _factions(), [])
    assert len(calls) == 2
    assert decision["action_type"] == "spread_fear"
    assert decision["used_llm"] is True


def test_generate_decision_falls_back_to_stub_after_two_bad_rolls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        conversation, "_call_llm",
        lambda **kwargs: calls.append(1) or '{"action_type": "nonsense"}',
    )
    decision = demon_lord.generate_decision({}, {"region": {}}, _factions(), [])
    assert len(calls) == 2  # exactly one re-roll, never more
    assert decision["used_llm"] is False
    assert decision["action_type"] in demon_lord.ACTION_TYPES


def test_generate_decision_stub_when_llm_down(monkeypatch):
    monkeypatch.setattr(conversation, "_call_llm", lambda **kwargs: None)
    decision = demon_lord.generate_decision({}, {"region": {}}, _factions(), [])
    assert decision["used_llm"] is False
    assert decision["action_type"] in demon_lord.ACTION_TYPES
    assert decision["announcement"]
    assert decision["faction_reputation_effects"]


def test_decision_prompt_uses_faction_ids_and_recent_moves():
    state = {
        "current_day": 9,
        "region": {"current_weather": "fog"},
        "demon_lord_decisions": [{"day": 8, "summary": "Day 8: omens bled the sky."}],
    }
    prompt = demon_lord.build_decision_prompt(
        {"name": demon_lord.DEMON_LORD_NAME}, state, _factions(),
        [_rumor(current_text="The smith wept at dawn.")],
    )
    assert "faction_watch" in prompt and "faction_commons" in prompt
    assert "The smith wept at dawn." in prompt
    assert "Day 8: omens bled the sky." in prompt
    for action in demon_lord.ACTION_TYPES:
        assert action in prompt


# --------------------------------------------------------------------------- #
# Decision effects + injection (T035/T036)
# --------------------------------------------------------------------------- #
def _seed_world(database):
    for faction in _factions():
        database.save_faction(faction)
    npcs = [
        _npc("npc_00001", name="Watcher One", tier=2,
             faction_affiliations=[{"faction_id": "faction_watch", "faction_name": "Aldenmoor Watch",
                                    "loyalty": 70, "role": "member"}]),
        _npc("npc_00002", name="Watcher Two", tier=2,
             faction_affiliations=[{"faction_id": "faction_watch", "faction_name": "Aldenmoor Watch",
                                    "loyalty": 60, "role": "member"}]),
        _npc("npc_00003", name="Trader", tier=1,
             faction_affiliations=[{"faction_id": "faction_guild", "faction_name": "Merchants' Concord",
                                    "loyalty": 50, "role": "member"}]),
        _npc("npc_player", name="Host", is_player=True),
    ]
    for npc in npcs:
        database.save_npc(npc)
    database.save_world_state(
        {
            "game_started": True,
            "current_day": 9,
            "current_hour": 6,
            "player_npc_id": "npc_player",
            "demon_lord_npc_id": None,
            "demon_lord_decisions": [],
            "region": _region(),
        }
    )


def test_apply_decision_writes_all_effects(temp_db):
    _seed_world(temp_db)
    decision = {
        "action_type": "corrupt_official",
        "target_faction": "faction_watch",
        "announcement": "Someone in the Watch now answers to the Veiled Flame.",
        "faction_reputation_effects": {"faction_watch": -6},
        "used_llm": False,
    }

    result = demon_lord.apply_decision(decision, day=9)

    # Faction standing shifted and clamped within bounds.
    assert temp_db.get_faction("faction_watch")["player_reputation"] == 44
    # The reserved suspicious mood entered through the story event.
    suspicious = [n for n in temp_db.get_all_npcs() if n["current_mood"] == "suspicious"]
    assert {"Watcher One", "Watcher Two"} == {n["name"] for n in suspicious}
    assert all(
        any("Veiled Flame" in m for m in n["memory_buffer"]) for n in suspicious
    )
    # The announcement was born as a high-drama rumor seeded on witnesses.
    rumor = temp_db.get_rumor("rumor_d009_demonlord")
    assert rumor["active"] is True and rumor["drama_score"] == 85
    for npc_id in rumor["known_by_npc_ids"]:
        assert "rumor_d009_demonlord" in temp_db.get_npc(npc_id)["rumor_knowledge"]
    # The decision is recorded display-ready and logged.
    state = temp_db.get_world_state()
    assert state["demon_lord_decisions"][-1]["day"] == 9
    assert "Veiled Flame" in state["demon_lord_decisions"][-1]["summary"]
    assert any(e["event_type"] == "demon_lord" for e in temp_db.get_recent_log())
    assert result["mood"] == "suspicious"


def test_reputation_adjustment_clamps_and_rejects_unknown(temp_db):
    _seed_world(temp_db)
    assert temp_db.adjust_faction_reputation("faction_watch", -200) == 0
    assert temp_db.adjust_faction_reputation("faction_watch", +500) == 100
    assert temp_db.adjust_faction_reputation("faction_void", -5) is None


def test_ensure_demon_lord_injects_into_existing_world_once(temp_db):
    import main

    _seed_world(temp_db)
    before = {npc["id"] for npc in temp_db.get_all_npcs()}

    main._ensure_demon_lord()
    state = temp_db.get_world_state()
    assert state["demon_lord_npc_id"] == demon_lord.DEMON_LORD_ID
    demon = temp_db.get_npc(demon_lord.DEMON_LORD_ID)
    assert demon["is_demon_lord"] is True
    # Injection adds exactly one NPC and touches nothing else - the existing
    # world (and its accumulated memories) is never regenerated.
    assert {npc["id"] for npc in temp_db.get_all_npcs()} == before | {demon_lord.DEMON_LORD_ID}

    main._ensure_demon_lord()  # idempotent across restarts
    assert len([n for n in temp_db.get_all_npcs() if n.get("is_demon_lord")]) == 1


def test_demon_lord_defers_while_player_is_conversing(monkeypatch):
    import time

    import main

    monkeypatch.setattr(main, "CONVERSATION_IDLE_GRACE", 0.2)
    monkeypatch.setattr(main, "_LULL_POLL_SECONDS", 0.02)
    monkeypatch.setattr(main, "_last_conversation_at", time.monotonic())
    start = time.monotonic()
    main._wait_for_conversation_lull()
    assert time.monotonic() - start >= 0.15  # held off until the grace expired


def test_demon_lord_deferral_is_capped_so_the_day_never_starves(monkeypatch):
    import time

    import main

    monkeypatch.setattr(main, "CONVERSATION_IDLE_GRACE", 9999.0)
    monkeypatch.setattr(main, "DECISION_MAX_DEFER", 0.1)
    monkeypatch.setattr(main, "_LULL_POLL_SECONDS", 0.02)
    monkeypatch.setattr(main, "_last_conversation_at", time.monotonic())
    start = time.monotonic()
    main._wait_for_conversation_lull()
    assert time.monotonic() - start < 1.0  # gave up at the cap


def test_world_freezes_for_dialogue_and_daily_decision(monkeypatch):
    import main

    monkeypatch.setattr(main, "_active_conversations", 0)
    monkeypatch.setattr(main, "_dialogue_freeze_until", 0.0)
    main._demon_lord_deciding.clear()
    assert main._world_frozen() is False  # nothing active: the clock runs

    monkeypatch.setattr(main, "_active_conversations", 1)
    assert main._world_frozen() is True  # conversation turn in flight
    monkeypatch.setattr(main, "_active_conversations", 0)

    main._demon_lord_deciding.set()
    try:
        assert main._world_frozen() is True  # daily LLM call in flight
    finally:
        main._demon_lord_deciding.clear()
    assert main._world_frozen() is False


def test_dialogue_window_signals_freeze_and_resume(monkeypatch):
    import main

    monkeypatch.setattr(main, "_active_conversations", 0)
    monkeypatch.setattr(main, "_dialogue_freeze_until", 0.0)
    main._demon_lord_deciding.clear()

    main.post_input(main.PlayerInput(type="dialogue_open"))
    assert main._world_frozen() is True  # rolling freeze window armed
    main.post_input(main.PlayerInput(type="dialogue_close"))
    assert main._world_frozen() is False  # closing the window resumes time


def test_conversation_turn_freezes_world_and_books_out_cleanly(temp_db, monkeypatch):
    import main

    monkeypatch.setattr(main, "_active_conversations", 0)
    monkeypatch.setattr(main, "_dialogue_freeze_until", 0.0)
    _seed_world(temp_db)
    seen = {}

    original = main._run_conversation_inner

    def spying_inner(npc_id, player_text):
        seen["frozen_mid_turn"] = main._world_frozen()
        return original(npc_id, player_text)

    monkeypatch.setattr(main, "_run_conversation_inner", spying_inner)
    main._run_conversation("npc_00001", "Quiet night.")  # tier 2 -> stub reply, no LLM

    assert seen["frozen_mid_turn"] is True  # world held still during the turn
    assert main._active_conversations == 0  # in-flight counter restored
    assert main._world_frozen() is True  # rolling window still covers the dialogue
    main._clear_dialogue_freeze()


def test_run_demon_lord_day_decides_once_per_day(temp_db, monkeypatch):
    import main

    # Earlier endpoint tests stamp conversation activity; without resetting it
    # the decision would politely sleep out its full deferral here.
    monkeypatch.setattr(main, "_last_conversation_at", 0.0)
    _seed_world(temp_db)
    main._ensure_demon_lord()
    decision = {
        "action_type": "spread_fear",
        "target_faction": None,
        "announcement": "Fear walks the lanes tonight.",
        "faction_reputation_effects": {"faction_commons": -4},
        "used_llm": False,
    }
    calls = []
    monkeypatch.setattr(
        demon_lord, "generate_decision",
        lambda *args, **kwargs: calls.append(1) or decision,
    )

    main._run_demon_lord_day(9)
    main._run_demon_lord_day(9)  # same day: skipped, no second decision

    assert len(calls) == 1
    state = temp_db.get_world_state()
    assert [d["day"] for d in state["demon_lord_decisions"]] == [9]
    assert temp_db.get_faction("faction_commons")["player_reputation"] == 46


def test_dawn_tick_triggers_demon_lord_only_when_present(temp_db, monkeypatch):
    import main
    from systems import world_gen

    world_gen.generate_world(seed=42)
    monkeypatch.setattr(main, "_tick_rng", random.Random(5))

    state = temp_db.get_world_state()
    state["current_hour"] = 5  # next advance lands on dawn
    temp_db.save_world_state(state)
    assert main._advance_one_hour_locked() is None  # no Demon Lord yet

    main._ensure_demon_lord()
    state = temp_db.get_world_state()
    state["current_hour"] = 5
    temp_db.save_world_state(state)
    day = main._advance_one_hour_locked()
    assert day == state["current_day"]
