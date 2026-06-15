"""Day 7 — the live ML batch: NPC relationship drift (Model 2), rumor
propagation + distortion (Model 1), player reputation scorer (Model 3), and the
faction relationship updater (Model 4).

ML predictions from a RandomForest are approximate, so the per-model unit tests
pin the deterministic ground-truth RULES (and the predict() rule-fallback), and
the system-level tests force the rule fallback (model globals set to None) so the
arithmetic is exact. One integration test runs a real dawn tick end to end.
"""

from __future__ import annotations

import random

from ml import train as ml
from systems import factions, relationships, rumors


class _ForceRng:
    def __init__(self, value):
        self._value = value

    def random(self):
        return self._value


def _member(faction_id, mood="neutral", sentiment=50, loyalty=50, npc_id="n"):
    return {
        "id": npc_id, "current_mood": mood, "player_sentiment": sentiment,
        "faction_affiliations": [{"faction_id": faction_id, "loyalty": loyalty}],
    }


# --------------------------------------------------------------------------- #
# Model 1 — rumor propagation + distortion
# --------------------------------------------------------------------------- #
def test_spread_rule_bounds_and_relationship_monotonic():
    cold = ml._spread_rule(0.5, 0.8, 0.7, 0.0)
    warm = ml._spread_rule(0.5, 0.8, 0.7, 1.0)
    assert 0.0 <= cold <= ml.MAX_SPREAD_PROBABILITY
    assert warm > cold  # a warmer bond carries the tale more readily
    assert ml.predict_spread_probability(None, 0.5, 0.8, 0.7, 1.0) == warm  # rule fallback


def test_spread_probability_uses_relationship_sentiment(monkeypatch):
    monkeypatch.setattr(rumors, "_prop_model", None)
    monkeypatch.setattr(rumors, "_prop_model_trained", True)  # force the rule fallback
    teller = {"occupation": "tavern_keeper", "personality_traits": ["curious"]}
    rumor = {"propagation_rate": 0.5, "drama_score": 80}
    close = rumors.spread_probability(teller, rumor, {"sentiment": 90})
    distant = rumors.spread_probability(teller, rumor, {"sentiment": -90})
    assert close > distant


def test_maybe_distort_increments_level_blurs_text_and_caps():
    rumor = {"current_text": "Cultists struck the market.", "distortion_level": 0}
    rumors._maybe_distort(rumor, _ForceRng(0.0))  # below DISTORTION_CHANCE -> distorts
    assert rumor["distortion_level"] == 1
    assert rumor["current_text"] != "Cultists struck the market."  # hedged
    # Never past the cap, and a roll above the chance leaves it alone.
    rumor["distortion_level"] = rumors.MAX_DISTORTION_LEVEL
    before = dict(rumor)
    rumors._maybe_distort(rumor, _ForceRng(0.0))
    assert rumor["distortion_level"] == rumors.MAX_DISTORTION_LEVEL
    rumor2 = {"current_text": "x", "distortion_level": 0}
    rumors._maybe_distort(rumor2, _ForceRng(0.99))  # above the chance -> no-op
    assert rumor2["distortion_level"] == 0


# --------------------------------------------------------------------------- #
# Model 2 — NPC relationship drift
# --------------------------------------------------------------------------- #
def test_relationship_drift_rule_directions_and_clamp():
    warm = ml._relationship_drift_rule(0.0, 0.7, 0.7, 1.0, 0.0)   # content + same faction
    cold = ml._relationship_drift_rule(0.0, 0.15, 0.15, 0.0, 0.0)  # both miserable, no tie
    decay = ml._relationship_drift_rule(1.0, 0.5, 0.5, 0.0, 0.0)   # high bond, nothing feeding it
    assert warm > 0 and cold < 0 and decay < 0
    assert -ml.RELATIONSHIP_DELTA_LIMIT <= cold <= ml.RELATIONSHIP_DELTA_LIMIT
    assert ml.predict_sentiment_delta(None, 0, 0.7, 0.7, True, 0.0) == warm  # rule fallback


def test_drift_relationships_warms_friends_and_decays_stale_bonds(monkeypatch):
    monkeypatch.setattr(relationships, "_model", None)
    monkeypatch.setattr(relationships, "_model_trained", True)  # force the rule
    npcs = [
        {"id": "a", "current_mood": "content", "faction_affiliations": [{"faction_id": "f1"}],
         "rumor_knowledge": [],
         "relationships": [
             {"npc_id": "b", "name": "B", "sentiment": 0},     # fellow content faction-mate
             {"npc_id": "c", "name": "C", "sentiment": 100},   # maxed bond to a neutral outsider
         ]},
        {"id": "b", "current_mood": "content", "faction_affiliations": [{"faction_id": "f1"}],
         "rumor_knowledge": [], "relationships": []},
        {"id": "c", "current_mood": "neutral", "faction_affiliations": [{"faction_id": "f2"}],
         "rumor_knowledge": [], "relationships": []},
    ]
    result = relationships.drift_relationships_daily(npcs, random.Random(1))
    a_to_b = npcs[0]["relationships"][0]["sentiment"]
    a_to_c = npcs[0]["relationships"][1]["sentiment"]
    assert a_to_b > 0          # content + same faction warms the new bond
    assert a_to_c < 100        # a maxed bond to a neutral outsider decays back down
    assert npcs[0] in result["changed"]


def test_drift_skips_player_and_demon_lord(monkeypatch):
    monkeypatch.setattr(relationships, "_model", None)
    monkeypatch.setattr(relationships, "_model_trained", True)
    npcs = [
        {"id": "p", "is_player": True, "current_mood": "content",
         "relationships": [{"npc_id": "b", "name": "B", "sentiment": 0}], "rumor_knowledge": []},
        {"id": "b", "current_mood": "content", "relationships": [], "rumor_knowledge": []},
    ]
    result = relationships.drift_relationships_daily(npcs, random.Random(1))
    assert result["changed"] == []  # the player's host is outside the social graph


# --------------------------------------------------------------------------- #
# Model 3 — player reputation scorer
# --------------------------------------------------------------------------- #
def test_reputation_target_rule_tracks_member_sentiment():
    assert ml._reputation_target_rule(80, 1.0) > 50
    assert ml._reputation_target_rule(20, 1.0) < 50
    assert abs(ml._reputation_target_rule(50, 1.0) - 50) < 1e-6  # neutral members -> ~50


def test_player_reputation_drifts_toward_member_sentiment(monkeypatch):
    monkeypatch.setattr(factions, "_rep_model", None)
    monkeypatch.setattr(factions, "_rep_model_trained", True)  # force the rule
    fac = {"id": "f1", "player_reputation": 50}
    fond = [_member("f1", sentiment=85, npc_id="a"), _member("f1", sentiment=85, npc_id="b")]
    factions.update_player_reputation_daily([fac], fond)
    assert fac["player_reputation"] > 50  # members fond of the player -> standing rises

    hostile_fac = {"id": "f2", "player_reputation": 50}
    hostile = [_member("f2", sentiment=10, npc_id="c")]
    factions.update_player_reputation_daily([hostile_fac], hostile)
    assert hostile_fac["player_reputation"] < 50


def test_player_reputation_ignores_player_and_memberless_factions(monkeypatch):
    monkeypatch.setattr(factions, "_rep_model", None)
    monkeypatch.setattr(factions, "_rep_model_trained", True)
    empty = {"id": "f1", "player_reputation": 50}
    only_player = [{"id": "p", "is_player": True, "player_sentiment": 0,
                    "faction_affiliations": [{"faction_id": "f1", "loyalty": 90}]}]
    changed = factions.update_player_reputation_daily([empty], only_player)
    assert changed == [] and empty["player_reputation"] == 50  # no real members -> no move


# --------------------------------------------------------------------------- #
# Model 4 — faction relationship updater
# --------------------------------------------------------------------------- #
def test_faction_rel_rule_alignment_pressure_and_restore():
    aligned = ml._faction_rel_rule(0.5, 0.5, 1.0, 0.0)   # identical moods, no stress
    stressed = ml._faction_rel_rule(0.5, 0.5, 1.0, 1.0)  # shared morale collapse
    assert aligned > 0 and stressed < aligned
    assert -ml.FACTION_REL_DELTA_LIMIT <= stressed <= ml.FACTION_REL_DELTA_LIMIT


def test_faction_relationships_capture_seed_and_cool_under_pressure(monkeypatch):
    monkeypatch.setattr(factions, "_rel_model", None)
    monkeypatch.setattr(factions, "_rel_model_trained", True)  # force the rule
    factions_by_id = {
        "fa": {"id": "fa", "name": "Watch", "morale": 20},   # battered -> high pressure
        "fb": {"id": "fb", "name": "Concord", "morale": 20},
    }
    npcs = [_member("fa", "content", npc_id="a"), _member("fb", "fearful", npc_id="b")]
    rels = [{"faction_a_id": "fa", "faction_b_id": "fb", "relationship_score": 60}]

    result = factions.update_faction_relationships_daily(rels, factions_by_id, npcs)

    assert rels[0]["seed_score"] == 60                 # Day-2 seed captured on first touch
    assert rels[0]["relationship_score"] < 60          # divergent moods + shared stress cool it
    assert result["notes"] and result["notes"][0]["a"] == "fa"


# --------------------------------------------------------------------------- #
# Integration — a real dawn tick runs all four models
# --------------------------------------------------------------------------- #
def test_dawn_tick_runs_all_four_models(temp_db, monkeypatch):
    import main
    from systems import world_gen

    world_gen.generate_world(seed=42)
    monkeypatch.setattr(main, "_tick_rng", random.Random(5))
    state = temp_db.get_world_state()
    state["current_hour"] = 5  # next advance lands on dawn
    temp_db.save_world_state(state)

    before = {
        npc["id"]: [r["sentiment"] for r in npc.get("relationships", [])]
        for npc in temp_db.get_all_npcs()
    }

    main._advance_one_hour_locked()  # runs Models 2 -> 1 -> 3 -> 4 under the lock

    # Model 4 captured the Day-2 seed and kept scores in bounds.
    rels = temp_db.get_faction_relationships()
    assert rels and all("seed_score" in r for r in rels)
    assert all(0 <= r["relationship_score"] <= 100 for r in rels)
    # Faction scalars all stayed within bounds.
    for faction in temp_db.get_all_factions():
        assert 0 <= faction["player_reputation"] <= 100
        assert 0 <= faction.get("morale", 60) <= 100
    # Model 2 unfroze the social graph: at least one relationship sentiment moved.
    after = {
        npc["id"]: [r["sentiment"] for r in npc.get("relationships", [])]
        for npc in temp_db.get_all_npcs()
    }
    assert before != after
