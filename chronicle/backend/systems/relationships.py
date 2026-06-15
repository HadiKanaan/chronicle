"""NPC relationship drift (Day 7, Model 2).

Pure simulation over the plain dict shapes stored in SQLite - like rumors.py and
behavior.py, it never touches the database. main.py runs the dawn-tick call
under its simulation lock and persists the NPCs that changed.

The Tier-1 relationship graph has been static since world generation. Each dawn
this drifts every directed relationship's sentiment from the two NPCs' moods,
whether they share a faction, and what rumors they both know - with a decay term
that eases bonds back toward neutral when nothing reinforces them. The fresh
sentiments feed the rumor-propagation model (Model 1), which is why this runs
first in the dawn branch.
"""

from __future__ import annotations

import random
from typing import Any, Optional

from ml import train as ml
from systems import behavior


# A per-day change at least this large (or a sign flip) is worth a notification.
NOTABLE_SHIFT = 4
_SHARED_RUMOR_CAP = 3.0

_model: Optional[Any] = None
_model_trained = False


def _get_model() -> Optional[Any]:
    global _model, _model_trained
    if not _model_trained:
        _model = ml.train_relationship_drift_model()
        _model_trained = True
    return _model


def _is_social(npc: dict[str, Any]) -> bool:
    """Player and Demon Lord stand outside the social graph."""
    return not npc.get("is_player") and not npc.get("is_demon_lord")


def _valence(npc: dict[str, Any]) -> float:
    return behavior.MOOD_VALENCE.get(npc.get("current_mood", "neutral"), 0.5)


def _factions_of(npc: dict[str, Any]) -> set[str]:
    return {a.get("faction_id") for a in npc.get("faction_affiliations", [])}


def drift_relationships_daily(
    npcs: list[dict[str, Any]],
    rng: random.Random,  # reserved for future stochastic drift; kept for a uniform signature
) -> dict[str, Any]:
    """Drift every Tier-1 directed relationship one day. Mutates NPC dicts in
    place; returns {"changed": [npc, ...], "notes": [str, ...]}."""
    model = _get_model()
    by_id = {npc["id"]: npc for npc in npcs}
    changed: list[dict[str, Any]] = []
    changed_ids: set[str] = set()
    notes: list[str] = []

    for npc in npcs:
        if not _is_social(npc):
            continue
        relationships = npc.get("relationships") or []
        if not relationships:
            continue
        valence_a = _valence(npc)
        my_factions = _factions_of(npc)
        my_rumors = set(npc.get("rumor_knowledge", []))
        npc_changed = False

        for rel in relationships:
            partner = by_id.get(rel.get("npc_id"))
            if partner is None or not _is_social(partner):
                continue
            shared = len(my_rumors & set(partner.get("rumor_knowledge", [])))
            delta = ml.predict_sentiment_delta(
                model,
                int(rel.get("sentiment", 0)),
                valence_a,
                _valence(partner),
                bool(my_factions & _factions_of(partner)),
                min(1.0, shared / _SHARED_RUMOR_CAP),
            )
            old = int(rel.get("sentiment", 0))
            new = max(-100, min(100, int(round(old + delta))))
            if new == old:
                continue
            rel["sentiment"] = new
            npc_changed = True
            if abs(new - old) >= NOTABLE_SHIFT or (old < 0) != (new < 0):
                verb = "grown closer to" if new > old else "cooled toward"
                notes.append(
                    f"{npc.get('name', npc['id'])} has {verb} "
                    f"{rel.get('name', rel.get('npc_id'))}."
                )

        if npc_changed and npc["id"] not in changed_ids:
            changed_ids.add(npc["id"])
            changed.append(npc)

    return {"changed": changed, "notes": notes}
