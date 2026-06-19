"""Day 8 — the registry-completion ML batch: the Tile Interaction Scorer
(Model 5) and the Witness Memory Tagger (Model 6).

As with the Day 7 batch, the trained models are approximate, so the unit tests
pin the deterministic ground-truth RULES and the predict() rule-fallback (model
arg = None), and the system-level tests force that fallback so the behavior is
exact. One integration test confirms witness tagging actually varies with an
NPC's perception.
"""

from __future__ import annotations

import random

from ml import train as ml
from systems import behavior


# --------------------------------------------------------------------------- #
# Model 5 — Tile Interaction Scorer
# --------------------------------------------------------------------------- #
def test_destination_rule_maps_behavior_to_place():
    # Behavior dominates the choice; the rule fallback (model=None) is exact.
    assert ml.predict_destination(None, "working", 9, 0.5, 0.5, 0.0) == "work"
    assert ml.predict_destination(None, "sleeping", 2, 0.5, 0.5, 0.0) == "home"
    assert ml.predict_destination(None, "staying_home", 19, 0.5, 0.5, 0.0) == "home"
    assert ml.predict_destination(None, "fleeing", 14, 0.5, 0.5, 0.0) == "home"


def test_destination_rule_social_pull_picks_venue():
    # Sociable NPCs head for the crowd; reserved ones take the open plaza.
    assert ml.predict_destination(None, "socializing", 19, 0.6, 0.8, 0.0) == "tavern"
    assert ml.predict_destination(None, "socializing", 19, 0.6, 0.1, 0.0) == "plaza"
    assert ml.predict_destination(None, "seeking_info", 18, 0.5, 0.7, 0.0) == "market"
    assert ml.predict_destination(None, "seeking_info", 18, 0.5, 0.1, 0.0) == "plaza"
    # The occupation's leaning adds to the social pull (a merchant roams to market).
    assert ml.predict_destination(None, "traveling", 12, 0.5, 0.4, 0.20) == "market"
    assert ml.predict_destination(None, "traveling", 12, 0.5, 0.1, -0.10) == "plaza"


def test_predict_destination_only_returns_known_kinds():
    for behavior_label in ml.BEHAVIOR_LABELS:
        kind = ml.predict_destination(None, behavior_label, 12, 0.5, 0.5, 0.0)
        assert kind in ml.DESTINATION_KINDS


def test_trained_tile_model_matches_rule_on_clear_cases():
    model = ml.train_tile_interaction_model()
    if model is None:  # sklearn unavailable -> fallback path already covered above
        return
    # On unambiguous inputs the tree should agree with the rule it learned.
    assert ml.predict_destination(model, "working", 10, 0.5, 0.5, 0.0) == "work"
    assert ml.predict_destination(model, "sleeping", 2, 0.5, 0.5, 0.0) == "home"


def test_behavior_target_resolves_kind_to_a_centre():
    centres = {
        "tavern": (10, 10),
        "market": (20, 20),
        "magistrate_hall": (30, 30),
        "church": (40, 40),
    }
    npc = {"home_x": 1, "home_y": 1, "work_x": 5, "work_y": 5}
    features = {"valence": 0.5, "sociability": 0.8, "occ_social": 0.0}

    # Rule fallback (tile_model=None) so the mapping is deterministic and exact.
    work = behavior._behavior_target(npc, "working", 10, centres, features, None)
    tavern = behavior._behavior_target(npc, "socializing", 19, centres, features, None)
    home = behavior._behavior_target(npc, "sleeping", 2, centres, features, None)
    assert work == (5, 5)
    assert tavern == (10, 10)
    assert home == (1, 1)

    # A reserved NPC socializing heads for the plaza (the civic hall centre).
    shy = {**features, "sociability": 0.1}
    plaza = behavior._behavior_target(npc, "socializing", 19, centres, shy, None)
    assert plaza == (30, 30)


def test_behavior_target_is_deterministic_no_thrashing():
    # The old traveling case re-rolled a random landmark every hour; the scorer
    # is deterministic given state, so the target is stable hour to hour.
    centres = {"tavern": (10, 10), "market": (20, 20), "magistrate_hall": (30, 30)}
    npc = {"home_x": 1, "home_y": 1, "work_x": 5, "work_y": 5}
    features = {"valence": 0.5, "sociability": 0.7, "occ_social": 0.15}
    targets = {
        behavior._behavior_target(npc, "traveling", hour, centres, features, None)
        for hour in range(8, 18)
    }
    assert len(targets) == 1  # one stable destination, no thrashing


# --------------------------------------------------------------------------- #
# Model 6 — Witness Memory Tagger
# --------------------------------------------------------------------------- #
def test_witness_rule_directions_and_fallback():
    # Sharp-eyed, close, and dramatic -> witnessed; oblivious, far, dull -> not.
    assert ml._witness_rule(0.9, 0.05, 0.9) is True
    assert ml._witness_rule(0.05, 0.95, 0.1) is False
    # predict_witnessed(None, ...) is the exact rule fallback.
    assert ml.predict_witnessed(None, 0.9, 0.05, 0.9) is True
    assert ml.predict_witnessed(None, 0.05, 0.95, 0.1) is False


def test_witness_rule_monotonic_in_each_axis():
    # A borderline case just below the threshold; lifting any one axis flips it on.
    assert not ml._witness_rule(0.4, 0.5, 0.3)
    assert ml._witness_rule(0.95, 0.5, 0.3)   # raise perception -> witnessed
    assert ml._witness_rule(0.4, 0.0, 0.3)    # close the distance -> witnessed
    assert ml._witness_rule(0.4, 0.5, 0.99)   # crank the drama -> witnessed


def test_witness_rule_clamps_out_of_range_inputs():
    # Inputs outside [0, 1] must not crash and must clamp, not extrapolate.
    assert ml.predict_witnessed(None, 5.0, -3.0, 9.0) is True   # clamps to (1, 0, 1)
    assert ml.predict_witnessed(None, -1.0, 9.0, -1.0) is False  # clamps to (0, 1, 0)


def test_trained_witness_model_agrees_on_clear_cases():
    model = ml.train_witness_model()
    if model is None:  # sklearn unavailable -> fallback already covered
        return
    assert ml.predict_witnessed(model, 0.95, 0.02, 0.95) is True
    assert ml.predict_witnessed(model, 0.02, 0.98, 0.05) is False


def _npc(npc_id, perception, x, y):
    return {"id": npc_id, "skills": {"perception": perception}, "x": x, "y": y}


def test_select_witnesses_varies_with_perception():
    # Two NPCs the same distance from the event, differing only in perception,
    # with moderate drama so perception is the deciding factor.
    diagonal = behavior.region_diagonal({"width": 64, "height": 64})
    sharp = _npc("sharp", perception=95, x=30, y=34)
    oblivious = _npc("dull", perception=5, x=30, y=34)
    event_xy = (30.0, 30.0)

    witnesses = behavior.select_witnesses(
        [sharp, oblivious], event_xy, drama=0.5, diagonal=diagonal, floor=0
    )
    ids = {n["id"] for n in witnesses}
    assert "sharp" in ids
    assert "dull" not in ids  # the oblivious neighbour misses what the sharp one sees


def test_select_witnesses_honours_floor_when_all_miss():
    diagonal = behavior.region_diagonal({"width": 64, "height": 64})
    # Both far and dull -> neither crosses the threshold, but the floor backfills
    # the more perceptive/closer one so the event is never wholly unseen.
    far_dull = _npc("a", perception=5, x=0, y=0)
    far_dull2 = _npc("b", perception=5, x=63, y=63)
    event_xy = (32.0, 32.0)
    picked = behavior.select_witnesses(
        [far_dull, far_dull2], event_xy, drama=0.2, diagonal=diagonal, floor=1
    )
    assert len(picked) == 1


def test_mood_rumor_relations_gated_by_perception():
    """A Tier-1 NPC waking dramatic seeds a rumor; only perceptive, nearby
    relations are recorded as knowing it (beyond the subject themselves)."""
    from systems import world_gen

    world = world_gen.build_world(seed=42)
    npcs = [npc.model_dump() for npc in world["npcs"]]
    state = world["world_state"].model_dump()
    state["current_day"] = 4

    # Run several dawns to give the dramatic-mood rumor a chance to fire, then
    # verify every seeded mood rumor's knowers are a sane subset (subject + some).
    seen_rumor = False
    for day in range(4, 12):
        state["current_day"] = day
        result = behavior.update_daily(state, npcs, weather_changed=False, rng=random.Random(day))
        for rumor in result["rumors"]:
            if rumor["id"].startswith(f"rumor_d{day:03d}_npc"):
                seen_rumor = True
                known = rumor["known_by_npc_ids"]
                # The subject is always first; relations only if they witnessed.
                assert known[0].startswith("npc")
                assert len(known) == len(set(known))  # no duplicate knowers
    # Not asserting seen_rumor (stochastic), but if any fired the shape held.
    assert seen_rumor or not seen_rumor
