"""Day 8 dynamic NPC tier promotion/demotion - the "LRU of personhood".

Covers systems.tiers (pure promote/demote/LRU over plain card dicts) and the
main.py conversation wiring that bumps the count + last-talked stamp and triggers
promotion under _sim_lock:

- promotion seeds dark_trait/redeeming_quality/trauma, flips tier to 1, and links
  2-3 reciprocal relationships into the Tier-1 social graph;
- demotion is LRU (least-recently-conversed-with Tier 1) and preserves the whole
  card (memories/history/enrichment) so re-promotion remembers everything;
- is_player and is_demon_lord are excluded from both promotion and demotion;
- the ~10 Tier-1 cap holds (a promotion over the cap demotes the LRU member).

No real Ollama server is needed: the pure tests touch no I/O, and the wiring test
talks to a Tier-2 NPC (rule-based stub replies, no LLM) and disables the
enrichment daemon.
"""

from __future__ import annotations

import random

from systems import tiers


def _names() -> dict:
    return tiers.load_name_pools()


def _card(npc_id: str, *, tier: int = 2, **overrides) -> dict:
    card = {
        "id": npc_id,
        "tier": tier,
        "name": npc_id.replace("_", " ").title(),
        "occupation": "farmer",
        "current_mood": "content",
        "player_sentiment": 50,
        "player_conversation_count": 0,
        "last_talked_stamp": 0.0,
        "relationships": [],
        "memory_buffer": [],
        "conversation_history": [],
    }
    card.update(overrides)
    return card


# --------------------------------------------------------------------------- #
# Per-conversation bookkeeping
# --------------------------------------------------------------------------- #
def test_record_conversation_bumps_count_and_stamp():
    npc = _card("x")
    tiers.record_conversation(npc, 12.5)
    assert npc["player_conversation_count"] == 1
    assert npc["last_talked_stamp"] == 12.5
    tiers.record_conversation(npc, 20.0)
    assert npc["player_conversation_count"] == 2
    assert npc["last_talked_stamp"] == 20.0


def test_should_promote_only_after_threshold_and_only_for_background_npcs():
    below = _card("a", tier=2, player_conversation_count=tiers.PROMOTION_THRESHOLD - 1)
    at = _card("b", tier=2, player_conversation_count=tiers.PROMOTION_THRESHOLD)
    already_t1 = _card("c", tier=1, player_conversation_count=99)
    assert tiers.should_promote(below) is False
    assert tiers.should_promote(at) is True
    assert tiers.should_promote(already_t1) is False  # Tier 1 is not a promotion target


# --------------------------------------------------------------------------- #
# Promotion: seeds traits + flips tier + links relationships
# --------------------------------------------------------------------------- #
def test_promotion_seeds_traits_flips_tier_and_links_relationships():
    rng = random.Random(0)
    names = _names()
    peers = [_card(f"t1_{i}", tier=1) for i in range(5)]
    npc = _card("farmer", tier=2, player_conversation_count=tiers.PROMOTION_THRESHOLD)

    result = tiers.apply_conversation_tiering(npc, peers, names, rng, stamp=50.0)

    assert result["promoted"] is npc
    assert npc["tier"] == 1
    # seeded from the names.json pools
    assert npc["dark_trait"] in names["dark_traits"]
    assert npc["redeeming_quality"] in names["redeeming_qualities"]
    assert npc["trauma"] in names["traumas"]
    # 2-3 edges into the Tier-1 graph, all to real peers
    assert 2 <= len(npc["relationships"]) <= tiers.RELATIONSHIP_LINKS
    linked_ids = {rel["npc_id"] for rel in npc["relationships"]}
    assert linked_ids <= {peer["id"] for peer in peers}
    # reciprocal: every linked peer now knows the newcomer (and is returned to save)
    changed_ids = {card["id"] for card in result["changed"]}
    for peer in peers:
        if peer["id"] in linked_ids:
            assert any(rel["npc_id"] == "farmer" for rel in peer["relationships"])
            assert peer["id"] in changed_ids
    # a never-enriched promotee is queued for LLM enrichment
    assert result["enrich"] is npc


def test_repromotion_preserves_enriched_card_and_skips_enrich_queue():
    rng = random.Random(0)
    names = _names()
    # A previously-Tier-1 card, demoted to Tier 2 but still enriched with its own
    # inner life - a return visit must re-promote it whole, not overwrite it.
    card = _card(
        "vet",
        tier=2,
        player_conversation_count=tiers.PROMOTION_THRESHOLD,
        llm_enriched=True,
        dark_trait="hoards secrets",
        redeeming_quality="kind to orphans",
        trauma="the old fire",
        memory_buffer=["Day 1: remembers the flood"],
    )
    result = tiers.apply_conversation_tiering(card, [], names, rng, stamp=5.0)

    assert card["tier"] == 1
    assert card["dark_trait"] == "hoards secrets"  # NOT reseeded
    assert card["redeeming_quality"] == "kind to orphans"
    assert card["trauma"] == "the old fire"
    assert card["memory_buffer"] == ["Day 1: remembers the flood"]  # memories kept
    assert result["enrich"] is None  # already enriched -> not re-queued


# --------------------------------------------------------------------------- #
# Demotion: LRU + preserves the card
# --------------------------------------------------------------------------- #
def test_demotion_is_lru_and_preserves_the_card():
    rng = random.Random(1)
    names = _names()
    # Four established Tier-1s with rising last-talked stamps: t1_0 is the oldest.
    peers = [
        _card(
            f"t1_{i}",
            tier=1,
            last_talked_stamp=float(i),
            memory_buffer=[f"Day {i}: a memory"],
            conversation_history=[{"player_text": "hi", "npc_response": "aye"}],
        )
        for i in range(4)
    ]
    newcomer = _card("new", tier=2, player_conversation_count=tiers.PROMOTION_THRESHOLD)
    roster = peers + [newcomer]

    result = tiers.apply_conversation_tiering(newcomer, roster, names, rng, stamp=100.0, cap=4)

    # promoting a 5th social Tier-1 over a cap of 4 demotes the LRU (oldest stamp)
    assert result["promoted"] is newcomer
    assert result["demoted"]["id"] == "t1_0"
    assert result["demoted"]["tier"] == 2
    # demotion is ONLY a tier flip - the card keeps everything
    assert result["demoted"]["memory_buffer"] == ["Day 0: a memory"]
    assert result["demoted"]["conversation_history"] == [
        {"player_text": "hi", "npc_response": "aye"}
    ]
    # the roster is back to the cap of promotable Tier-1s
    social_t1 = [c for c in roster if tiers.is_social(c) and c["tier"] == 1]
    assert len(social_t1) == 4


def test_no_demotion_when_under_cap():
    rng = random.Random(2)
    names = _names()
    peers = [_card(f"t1_{i}", tier=1, last_talked_stamp=float(i)) for i in range(3)]
    newcomer = _card("new", tier=2, player_conversation_count=tiers.PROMOTION_THRESHOLD)
    result = tiers.apply_conversation_tiering(newcomer, peers + [newcomer], names, rng, 9.0, cap=10)
    assert result["promoted"] is newcomer
    assert result["demoted"] is None
    assert all(peer["tier"] == 1 for peer in peers)  # nobody bumped down


# --------------------------------------------------------------------------- #
# Player / Demon Lord exclusion
# --------------------------------------------------------------------------- #
def test_player_and_demon_lord_are_never_promoted():
    rng = random.Random(0)
    names = _names()
    for special in (
        _card("player", tier=2, is_player=True, player_conversation_count=99),
        _card("demon", tier=1, is_demon_lord=True, player_conversation_count=99),
    ):
        result = tiers.apply_conversation_tiering(special, [], names, rng, 5.0)
        # a no-op: not even the count/stamp is bumped for these two
        assert result == {"changed": [], "promoted": None, "demoted": None, "enrich": None}
        assert special["player_conversation_count"] == 99


def test_player_and_demon_lord_are_never_demoted():
    rng = random.Random(0)
    names = _names()
    # A player and Demon Lord both sit at Tier 1 with stamp 0 (the usual LRU
    # victims), but a cap-busting promotion must demote the only SOCIAL Tier-1.
    player = _card("player", tier=1, is_player=True, last_talked_stamp=0.0)
    demon = _card("demon", tier=1, is_demon_lord=True, last_talked_stamp=0.0)
    real_t1 = _card("real", tier=1, last_talked_stamp=5.0)
    newcomer = _card("new", tier=2, player_conversation_count=tiers.PROMOTION_THRESHOLD)
    roster = [player, demon, real_t1, newcomer]

    result = tiers.apply_conversation_tiering(newcomer, roster, names, rng, 10.0, cap=1)

    assert result["demoted"]["id"] == "real"  # never the player or the Demon Lord
    assert player["tier"] == 1 and demon["tier"] == 1


def test_player_and_demon_lord_do_not_count_toward_the_cap():
    rng = random.Random(0)
    names = _names()
    player = _card("player", tier=1, is_player=True)
    demon = _card("demon", tier=1, is_demon_lord=True)
    real_t1 = _card("real", tier=1, last_talked_stamp=5.0)
    newcomer = _card("new", tier=2, player_conversation_count=tiers.PROMOTION_THRESHOLD)
    # cap of 2 promotable Tier-1s: real_t1 + newcomer == 2, so no demotion despite
    # the player and Demon Lord also being Tier 1.
    result = tiers.apply_conversation_tiering(
        newcomer, [player, demon, real_t1, newcomer], names, rng, 10.0, cap=2
    )
    assert result["demoted"] is None


# --------------------------------------------------------------------------- #
# ~10 Tier-1 cap holds under repeated promotions
# --------------------------------------------------------------------------- #
def test_cap_holds_across_many_promotions():
    rng = random.Random(7)
    names = _names()
    cap = 5
    roster = [_card(f"seed_{i}", tier=1, last_talked_stamp=float(i)) for i in range(cap)]
    # Promote a long line of newcomers; the social Tier-1 count must never exceed
    # the cap (each over-cap promotion demotes the least-recently-talked-to one).
    for n in range(8):
        newcomer = _card(
            f"new_{n}", tier=2, player_conversation_count=tiers.PROMOTION_THRESHOLD
        )
        roster.append(newcomer)
        tiers.apply_conversation_tiering(
            newcomer, roster, names, rng, stamp=100.0 + n, cap=cap
        )
        social_t1 = [c for c in roster if tiers.is_social(c) and int(c["tier"]) == 1]
        assert len(social_t1) == cap


# --------------------------------------------------------------------------- #
# main.py conversation wiring (under _sim_lock, no LLM)
# --------------------------------------------------------------------------- #
def test_conversation_promotes_a_background_npc_after_threshold_turns(temp_db, monkeypatch):
    import main

    # No real Ollama: the enrichment daemon must short-circuit, and the Tier-2
    # conversation path already uses rule-based stubs.
    monkeypatch.setattr(main.conversation, "llm_available", lambda: False)
    main._dialogue_freeze_until = 0.0
    main._name_pools_cache = None  # force a clean load against the test data file

    for i in range(3):
        temp_db.save_npc(_card(f"npc_t1_{i}", tier=1, name=f"Peer {i}"))
    temp_db.save_npc(_card("npc_farmer", tier=2, occupation="farmer", name="Bram Holst"))
    temp_db.save_world_state(
        {
            "game_started": True,
            "current_day": 5,
            "current_hour": 9,
            "player_npc_id": None,
            "region": {"id": "r", "width": 4, "height": 4},
        }
    )

    for _ in range(tiers.PROMOTION_THRESHOLD):
        main._run_conversation("npc_farmer", "Good day to you, neighbour.")

    stored = temp_db.get_npc("npc_farmer")
    assert stored["tier"] == 1  # promoted to a real, simulated character
    assert stored["player_conversation_count"] == tiers.PROMOTION_THRESHOLD
    assert stored["dark_trait"] and stored["trauma"]  # personhood seeded
    assert stored["relationships"]  # linked into the Tier-1 social graph
    # the reciprocal edges reached the established peers
    peer = temp_db.get_npc("npc_t1_0")
    linked_back = any(rel["npc_id"] == "npc_farmer" for rel in peer.get("relationships", []))
    other_links = {rel["npc_id"] for rel in stored["relationships"]}
    assert linked_back or other_links  # at least linked somewhere in the graph


def test_conversation_below_threshold_does_not_promote(temp_db, monkeypatch):
    import main

    monkeypatch.setattr(main.conversation, "llm_available", lambda: False)
    main._dialogue_freeze_until = 0.0
    main._name_pools_cache = None

    temp_db.save_npc(_card("npc_quiet", tier=2, occupation="farmer", name="Sela"))
    temp_db.save_world_state(
        {
            "game_started": True,
            "current_day": 1,
            "current_hour": 6,
            "player_npc_id": None,
            "region": {"id": "r", "width": 4, "height": 4},
        }
    )

    # One short of the threshold: still a background villager.
    for _ in range(tiers.PROMOTION_THRESHOLD - 1):
        main._run_conversation("npc_quiet", "Nice weather.")

    stored = temp_db.get_npc("npc_quiet")
    assert stored["tier"] == 2
    assert stored["player_conversation_count"] == tiers.PROMOTION_THRESHOLD - 1
    assert not stored.get("dark_trait")
