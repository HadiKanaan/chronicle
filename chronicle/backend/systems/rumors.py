"""Rumor propagation system (Day 6 / User Story 4).

Each dawn tick, every active rumor tries to hop across the NPC relationship
graph: each NPC who knows it may whisper it to a few of their relations, gated
by a gossip chance built from the rumor's propagation_rate and drama_score and
the teller's personality and occupation. Rumors then age: propagation slows by
decay_rate each day, and a rumor retires (active=False) once it can no longer
spread or has grown too old to matter.

Like behavior.py, this module is pure simulation over the plain dict shapes
stored in SQLite - it never touches the database. main.py orchestrates the
dawn-tick call under its simulation lock and persists what changed. Knowledge
is tracked on both sides: the rumor's known_by_npc_ids and each knower's
rumor_knowledge list (the latter feeds rumor-aware dialogue prompts).
"""

from __future__ import annotations

import random
from typing import Any, Optional

from ml import train as ml

# A rumor retires when it can no longer spread or has gone stale.
MIN_PROPAGATION_RATE = 0.02
MAX_RUMOR_AGE_DAYS = 10

# Each knower whispers to at most this many relations per day, so even a
# dramatic rumor takes several days to saturate the Tier 1 social graph.
MAX_TELLS_PER_DAY = 2

# Per-hop spread probability is clamped so nothing is ever a guaranteed jump.
MAX_GOSSIP_CHANCE = 0.90

# How many known rumor texts a conversation prompt receives.
DIALOGUE_RUMOR_CAP = 3

# How likely a personality is to pass a story along (added to the base 0.5).
BASE_GOSSIP_PROPENSITY = 0.5
_TRAIT_GOSSIP = {
    "curious": 0.20, "cheerful": 0.10, "reckless": 0.10, "suspicious": 0.10,
    "cautious": -0.15, "melancholic": -0.10, "loyal": -0.05,
}
_OCC_GOSSIP = {
    "tavern_keeper": 0.30, "merchant": 0.15, "trader": 0.15,
    "beggar": 0.20, "courier": 0.20, "priest": -0.10, "guard_captain": -0.10,
}


def _is_social(npc: dict[str, Any]) -> bool:
    """Player and Demon Lord stand outside the gossip network entirely."""
    return not npc.get("is_player") and not npc.get("is_demon_lord")


def _gossip_propensity(npc: dict[str, Any]) -> float:
    propensity = BASE_GOSSIP_PROPENSITY + _OCC_GOSSIP.get(npc.get("occupation", ""), 0.0)
    propensity += sum(_TRAIT_GOSSIP.get(t, 0.0) for t in npc.get("personality_traits", []))
    return max(0.0, min(1.0, propensity))


def gossip_chance(teller: dict[str, Any], rumor: dict[str, Any]) -> float:
    """Probability the teller passes this rumor along one relationship today.

    This is the Day-6 hand-rolled formula; since Day 7 it is the rule fallback
    behind the trained propagation model (spread_probability).
    """
    drama = max(0, min(100, int(rumor.get("drama_score", 50)))) / 100.0
    rate = float(rumor.get("propagation_rate", 0.3))
    chance = rate * _gossip_propensity(teller) * (0.5 + drama)
    return max(0.0, min(MAX_GOSSIP_CHANCE, chance))


# Day 7 (Model 1): a trained classifier predicts the per-hop spread probability,
# adding the teller<->listener relationship the bare formula ignored - a juicy
# rumor travels faster between close friends. gossip_chance stays the fallback.
_prop_model: Optional[Any] = None
_prop_model_trained = False

# Distortion: each successful hop has a small chance to garble the tale a little,
# nudging current_text away from original_event and bumping distortion_level
# (which sat at 0 before Day 7). Deterministic text-blur, no LLM in the tick.
DISTORTION_CHANCE = 0.15
MAX_DISTORTION_LEVEL = 3
_HEDGES = [
    "- or so they say.",
    "- though the details differ in each telling.",
    "...if the tale is even true anymore.",
]


def _get_prop_model() -> Optional[Any]:
    global _prop_model, _prop_model_trained
    if not _prop_model_trained:
        _prop_model = ml.train_rumor_propagation_model()
        _prop_model_trained = True
    return _prop_model


def spread_probability(
    teller: dict[str, Any],
    rumor: dict[str, Any],
    relationship: Optional[dict[str, Any]] = None,
) -> float:
    """Model-driven per-hop spread probability, relationship-aware (Model 1)."""
    drama = max(0, min(100, int(rumor.get("drama_score", 50)))) / 100.0
    rate = float(rumor.get("propagation_rate", 0.3))
    propensity = _gossip_propensity(teller)
    rel_sentiment = int(relationship.get("sentiment", 0)) if relationship else 0
    rel_norm = (max(-100, min(100, rel_sentiment)) + 100) / 200.0
    return ml.predict_spread_probability(_get_prop_model(), rate, drama, propensity, rel_norm)


def _maybe_distort(rumor: dict[str, Any], rng: random.Random) -> None:
    """On a hop, sometimes garble the rumor: bump distortion_level and hedge the
    text so it visibly drifts from the original event as it travels."""
    if rng.random() >= DISTORTION_CHANCE:
        return
    level = int(rumor.get("distortion_level", 0))
    if level >= MAX_DISTORTION_LEVEL:
        return
    rumor["distortion_level"] = level + 1
    text = str(rumor.get("current_text", "")).rstrip()
    hedge = _HEDGES[min(level, len(_HEDGES) - 1)]
    if text and hedge not in text:
        rumor["current_text"] = f"{text} {hedge}"


def _learn(npc: dict[str, Any], rumor_id: str) -> bool:
    """Record the rumor on the NPC's card. True when it was actually new."""
    knowledge = npc.setdefault("rumor_knowledge", [])
    if rumor_id in knowledge:
        return False
    knowledge.append(rumor_id)
    return True


def seed_knowledge(rumor: dict[str, Any], npcs_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Write a fresh rumor's id onto its witnesses' rumor_knowledge lists.

    Returns the NPCs that changed so the caller can persist them. Used when a
    rumor is born (dawn drama, Demon Lord actions) so dialogue can surface it
    before the first propagation pass.
    """
    changed: list[dict[str, Any]] = []
    for npc_id in rumor.get("known_by_npc_ids", []):
        npc = npcs_by_id.get(npc_id)
        if npc is not None and _learn(npc, rumor["id"]):
            changed.append(npc)
    return changed


def propagate_daily(
    npcs: list[dict[str, Any]],
    rumors: list[dict[str, Any]],
    rng: random.Random,
) -> dict[str, Any]:
    """One dawn pass: spread active rumors along relationships, then age them.

    Mutates NPC and rumor dicts in place. Returns {"npc_changes": [...],
    "rumor_changes": [...], "spread_count": int, "retired": int}; every rumor
    appears in rumor_changes because aging always advances.
    """
    npcs_by_id = {npc["id"]: npc for npc in npcs}
    npc_changes: list[dict[str, Any]] = []
    changed_ids: set[str] = set()
    spread_count = 0
    retired = 0

    def _mark(npc: dict[str, Any]) -> None:
        if npc["id"] not in changed_ids:
            changed_ids.add(npc["id"])
            npc_changes.append(npc)

    for rumor in rumors:
        if not rumor.get("active", True):
            continue
        known: list[str] = rumor.setdefault("known_by_npc_ids", [])

        # Heal pre-propagation rumors: witnesses recorded on the rumor before
        # Day 6 never had the id mirrored onto their cards.
        for npc_id in known:
            npc = npcs_by_id.get(npc_id)
            if npc is not None and _is_social(npc) and _learn(npc, rumor["id"]):
                _mark(npc)

        for teller_id in list(known):
            teller = npcs_by_id.get(teller_id)
            if teller is None or not _is_social(teller):
                continue
            tells = 0
            for relation in teller.get("relationships", []):
                if tells >= MAX_TELLS_PER_DAY:
                    break
                listener = npcs_by_id.get(relation.get("npc_id"))
                if listener is None or not _is_social(listener):
                    continue
                if listener["id"] in known:
                    continue
                if rng.random() >= spread_probability(teller, rumor, relation):
                    continue
                known.append(listener["id"])
                _learn(listener, rumor["id"])
                _mark(listener)
                _maybe_distort(rumor, rng)
                spread_count += 1
                tells += 1

        rumor["age_days"] = int(rumor.get("age_days", 0)) + 1
        rumor["propagation_rate"] = max(
            0.0, float(rumor.get("propagation_rate", 0.3)) - float(rumor.get("decay_rate", 0.05))
        )
        if (
            rumor["propagation_rate"] <= MIN_PROPAGATION_RATE
            or rumor["age_days"] >= MAX_RUMOR_AGE_DAYS
        ):
            rumor["active"] = False
            retired += 1

    return {
        "npc_changes": npc_changes,
        "rumor_changes": list(rumors),
        "spread_count": spread_count,
        "retired": retired,
    }


def known_rumor_texts(npc: dict[str, Any], active_rumors: list[dict[str, Any]]) -> list[str]:
    """The newest few rumor texts this NPC knows, for the conversation prompt.

    Rumor ids embed their birth day (rumor_dNNN_...), so id order is age order.
    Retired rumors drop out naturally: NPCs stop repeating stale news.
    """
    known = set(npc.get("rumor_knowledge", []))
    texts = [
        rumor.get("current_text", "")
        for rumor in sorted(active_rumors, key=lambda r: str(r.get("id", "")))
        if rumor.get("id") in known and rumor.get("current_text")
    ]
    return texts[-DIALOGUE_RUMOR_CAP:]
