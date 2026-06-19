"""Day 4 checks: ML behavior layer, world clock, memory rolls, rumor persistence.

Covers the acceptance criteria for User Story 2: NPCs visibly change behavior
and position over in-game days, weather changes over time, memory buffers fill
on significant events, and rumor structures persist without propagation.
"""

from __future__ import annotations

import random

import pytest

from ml import train as ml
from systems import behavior, weather


# --------------------------------------------------------------------------- #
# ML models (T019)
# --------------------------------------------------------------------------- #
class TestBehaviorClassifier:
    @pytest.fixture(scope="class")
    def model(self):
        return ml.train_behavior_model()

    def test_sleeps_at_night(self, model):
        label = ml.classify_behavior(model, 2, 0.5, 0.5, 0.0, 0.2, 0.2, 0.3)
        assert label == "sleeping"

    def test_works_during_the_day(self, model):
        label = ml.classify_behavior(model, 10, 0.6, 0.5, 0.0, 0.2, 0.2, 0.3)
        assert label == "working"

    def test_flees_when_terrified(self, model):
        label = ml.classify_behavior(model, 10, 0.2, 0.5, 0.5, 0.95, 0.2, 0.3)
        assert label == "fleeing"

    def test_shelters_from_storms(self, model):
        label = ml.classify_behavior(model, 10, 0.6, 0.5, 1.0, 0.2, 0.2, 0.3)
        assert label == "staying_home"

    def test_socializes_in_the_evening(self, model):
        label = ml.classify_behavior(model, 19, 0.7, 0.9, 0.0, 0.2, 0.2, 0.3)
        assert label == "socializing"

    def test_labels_always_valid(self, model):
        rng = random.Random(99)
        for _ in range(100):
            label = ml.classify_behavior(
                model,
                rng.randint(0, 23),
                rng.random(), rng.random(), rng.random(),
                rng.random(), rng.random(), rng.random(),
            )
            assert label in ml.BEHAVIOR_LABELS


class TestMoodModel:
    @pytest.fixture(scope="class")
    def model(self):
        return ml.train_mood_model()

    def test_good_day_lifts_mood(self, model):
        label = ml.predict_mood(model, 0.8, 0.9, 0.0, 0.8)
        assert label in ("happy", "content")

    def test_bad_day_in_a_storm_darkens_mood(self, model):
        label = ml.predict_mood(model, 0.2, 0.15, 1.0, 0.2)
        assert label in ("anxious", "fearful")

    def test_labels_always_valid(self, model):
        rng = random.Random(7)
        for _ in range(100):
            label = ml.predict_mood(model, rng.random(), rng.random(), rng.random(), rng.random())
            assert label in ml.MOOD_LABELS


class TestWeatherClassifier:
    @pytest.fixture(scope="class")
    def model(self):
        return ml.train_weather_model()

    def test_low_pressure_keeps_clear_weather(self, model):
        assert ml.predict_weather(model, "clear", "spring", 0.01) == "clear"

    def test_weather_varies_across_draws(self, model):
        rng = random.Random(11)
        seen = {ml.predict_weather(model, "clear", "spring", rng.random()) for _ in range(200)}
        assert len(seen) >= 2
        assert seen <= set(ml.WEATHER_LABELS)


# --------------------------------------------------------------------------- #
# Behavior system (T020) + memory rolling
# --------------------------------------------------------------------------- #
def test_memory_buffer_rolls_at_cap():
    npc = {"id": "npc_x", "memory_buffer": []}
    for i in range(behavior.MEMORY_BUFFER_CAP + 5):
        behavior.remember(npc, f"event {i}")
    assert len(npc["memory_buffer"]) == behavior.MEMORY_BUFFER_CAP
    assert npc["memory_buffer"][0] == "event 5"
    assert npc["memory_buffer"][-1] == f"event {behavior.MEMORY_BUFFER_CAP + 4}"


def test_bfs_routes_around_walls():
    # 5x5 grid with a vertical wall at x=2 except a gap at y=4.
    tiles = [
        [{"passable": not (x == 2 and y != 4)} for x in range(5)]
        for y in range(5)
    ]
    path = behavior._compute_path(tiles, (0, 0), (4, 0))
    assert path[-1] == (4, 0)
    assert all(tiles[y][x]["passable"] for x, y in path)
    assert behavior._compute_path(tiles, (0, 0), (0, 0)) == []


def test_movement_pops_cached_path_steps():
    walker = {"id": "a", "x": 0.0, "y": 0.0, "tier": 2,
              "current_behavior": "working", "path": [[1, 0], [2, 0], [3, 0]]}
    fleer = {"id": "b", "x": 0.0, "y": 0.0, "tier": 2,
             "current_behavior": "fleeing", "path": [[1, 0], [2, 0], [3, 0]]}
    player = {"id": "c", "x": 0.0, "y": 0.0, "tier": 1, "is_player": True,
              "current_behavior": "working", "path": [[1, 0]]}
    arrived = {"id": "d", "x": 5.0, "y": 5.0, "tier": 3,
               "current_behavior": "sleeping", "path": []}

    moved = behavior.update_movement([walker, fleer, player, arrived])

    assert [npc["id"] for npc in moved] == ["a", "b"]
    assert (walker["x"], walker["y"]) == (1.0, 0.0) and walker["path"] == [[2, 0], [3, 0]]
    assert (fleer["x"], fleer["y"]) == (2.0, 0.0) and fleer["path"] == [[3, 0]]
    assert (player["x"], player["y"]) == (0.0, 0.0), "simulation must not move the player"


# --------------------------------------------------------------------------- #
# Daily tick: moods, memories, rumor structures (no propagation)
# --------------------------------------------------------------------------- #
def _make_world(seed=42):
    from systems import world_gen

    return world_gen.build_world(seed)


def test_initial_moods_are_mostly_settled():
    """Day 1 should not look like a town in panic: settled moods dominate."""
    world = _make_world(seed=42)
    moods = [npc.current_mood.value for npc in world["npcs"]]
    settled = sum(1 for mood in moods if mood in ("neutral", "content", "happy"))
    assert settled / len(moods) > 0.6


def test_storm_writes_memories_and_a_rumor():
    world = _make_world()
    state = world["world_state"].model_dump()
    npcs = [npc.model_dump() for npc in world["npcs"]]
    state["region"]["current_weather"] = "storm"
    state["current_day"] = 3

    result = behavior.update_daily(state, npcs, weather_changed=True, rng=random.Random(1))

    storm_rumors = [r for r in result["rumors"] if r["id"] == "rumor_d003_storm"]
    assert len(storm_rumors) == 1
    assert storm_rumors[0]["known_by_npc_ids"]
    # Day 8 (Model 6): storm memories are now selective - only the NPCs whose
    # perception and proximity cross the witness threshold remember it, but the
    # floor guarantees at least one does (and not every townsperson sleeps through it).
    eligible = [
        npc for npc in npcs
        if int(npc["tier"]) <= 2 and not npc.get("is_player") and not npc.get("is_demon_lord")
    ]
    remembered = [
        npc for npc in eligible
        if any("storm broke over Aldenmoor" in entry for entry in npc.get("memory_buffer", []))
    ]
    assert remembered, "the witness floor must keep at least one rememberer"
    assert len(remembered) < len(eligible), "storm witnessing should be selective, not blanket"


def test_rumors_persist_without_propagation(temp_db):
    rumor = {
        "id": "rumor_test",
        "original_event": "test event",
        "current_text": "test event",
        "distortion_level": 0,
        "known_by_npc_ids": ["npc_00001"],
        "propagation_rate": 0.3,
        "decay_rate": 0.05,
        "drama_score": 50,
        "age_days": 0,
        "active": True,
    }
    temp_db.save_rumor(rumor)
    stored = temp_db.get_active_rumors()
    assert [r["id"] for r in stored] == ["rumor_test"]

    temp_db.add_rumor_knowledge("rumor_test", ["npc_00002", "npc_00001"])
    assert temp_db.get_rumor("rumor_test")["known_by_npc_ids"] == ["npc_00001", "npc_00002"]


# --------------------------------------------------------------------------- #
# World clock integration (T022): several in-game days end to end
# --------------------------------------------------------------------------- #
def test_world_clock_simulates_living_days(temp_db, monkeypatch):
    import main
    from systems import world_gen

    world_gen.generate_world(seed=42)
    monkeypatch.setattr(main, "_tick_rng", random.Random(5))

    homes = {
        npc["id"]: (npc["home_x"], npc["home_y"])
        for npc in temp_db.get_all_npcs()
    }

    behaviors_seen: set[str] = set()
    weather_seen: set[str] = set()
    away_from_home_seen = False
    for _ in range(72):  # three in-game days at full sub-tick cadence
        main._advance_one_hour()
        for _ in range(main.MOVE_STEPS_PER_HOUR - 1):
            main._advance_one_move_step()
        state = temp_db.get_world_state()
        weather_seen.add(state["region"]["current_weather"])
        for npc in temp_db.get_all_npcs():
            if npc.get("is_player"):
                continue
            behaviors_seen.add(npc["current_behavior"])
            if (npc["x"], npc["y"]) != homes[npc["id"]]:
                away_from_home_seen = True

    state = temp_db.get_world_state()
    assert state["current_day"] >= 3
    assert len(behaviors_seen) >= 3, f"world looks static: {behaviors_seen}"
    assert away_from_home_seen, "no NPC ever left home"
    assert weather_seen <= set(weather.WEATHER_STATES)

    # The player's host NPC is never driven by the simulation.
    player_id = state["player_npc_id"]
    player = temp_db.get_npc(player_id)
    assert (player["x"], player["y"]) == homes[player_id]
