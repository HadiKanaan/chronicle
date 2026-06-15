"""Faction-level daily dynamics (Day 7).

Pure simulation over the plain dict faction/NPC shapes, like rumors.py and
behavior.py - it never touches the database. main.py orchestrates the dawn-tick
call under its simulation lock and persists what changed.

Day 7 (faction decoupling): a faction's `morale` is its cohesion/wellbeing,
distinct from `player_reputation` (which now tracks only the player). Each dawn
morale drifts gently from its members' moods toward a baseline - this is the
RESTORING FORCE that keeps the Demon Lord's pressure from ratcheting morale to 0
over a long game. The player-reputation and inter-faction restoring forces
arrive with the Day 7 ML batch (Command 3); this module starts with morale.
"""

from __future__ import annotations

from typing import Any, Optional

from ml import train as ml
from systems import behavior


# Morale gravitates here when members are of average spirits; content members
# pull it above, frightened/grieving members below.
MORALE_BASELINE = 55
# Fraction of the gap to the daily target that morale closes each dawn - small,
# so morale eases rather than snaps (and Demon-Lord hits visibly linger).
MORALE_DRIFT_STEP = 0.2
# How far member mood can swing the daily target above/below the baseline.
_MEMBER_MOOD_SWING = 40.0
_DEFAULT_MORALE = 60


def _is_member_npc(npc: dict[str, Any]) -> bool:
    """The player's host and the Demon Lord don't count as faction members."""
    return not npc.get("is_player") and not npc.get("is_demon_lord")


def _faction_members(faction_id: str, npcs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        npc for npc in npcs
        if _is_member_npc(npc)
        and any(a.get("faction_id") == faction_id for a in npc.get("faction_affiliations", []))
    ]


def _morale_target(members: list[dict[str, Any]]) -> float:
    """The morale a faction is pulled toward today, from its members' moods."""
    if not members:
        return float(MORALE_BASELINE)
    valences = [behavior.MOOD_VALENCE.get(npc.get("current_mood", "neutral"), 0.5) for npc in members]
    mean_valence = sum(valences) / len(valences)
    return MORALE_BASELINE + (mean_valence - 0.5) * _MEMBER_MOOD_SWING


def update_morale_daily(
    factions: list[dict[str, Any]],
    npcs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drift every faction's morale one daily step toward its member-mood target.

    Mutates faction dicts in place; returns the factions whose morale changed so
    the caller can persist just those. Clamped to 0..100.
    """
    changed: list[dict[str, Any]] = []
    for faction in factions:
        members = _faction_members(str(faction.get("id", "")), npcs)
        target = _morale_target(members)
        current = float(faction.get("morale", _DEFAULT_MORALE))
        new_morale = int(round(max(0.0, min(100.0, current + (target - current) * MORALE_DRIFT_STEP))))
        if new_morale != int(current):
            faction["morale"] = new_morale
            changed.append(faction)
    return changed


# --------------------------------------------------------------------------- #
# Model 3: player reputation scorer (Day 7) — makes player_reputation move on
# its own again, now that the Demon Lord no longer writes it. Each dawn it eases
# toward the faction members' loyalty-weighted sentiment toward the player, so a
# neutral player drifts back to ~50 instead of the old slide to 0.
# --------------------------------------------------------------------------- #
_PLAYER_REP_STEP = 0.25
_rep_model: Optional[Any] = None
_rep_model_trained = False


def _get_rep_model() -> Optional[Any]:
    global _rep_model, _rep_model_trained
    if not _rep_model_trained:
        _rep_model = ml.train_player_reputation_model()
        _rep_model_trained = True
    return _rep_model


def update_player_reputation_daily(
    factions: list[dict[str, Any]],
    npcs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drift each faction's player_reputation toward its members' loyalty-weighted
    sentiment. Mutates faction dicts; returns the ones that changed."""
    model = _get_rep_model()
    changed: list[dict[str, Any]] = []
    for faction in factions:
        fid = str(faction.get("id", ""))
        members = _faction_members(fid, npcs)
        if not members:
            continue
        total_weight = 0.0
        accum = 0.0
        for member in members:
            loyalty = next(
                (a.get("loyalty", 50) for a in member.get("faction_affiliations", [])
                 if a.get("faction_id") == fid),
                50,
            )
            weight = max(1.0, float(loyalty))
            accum += weight * float(member.get("player_sentiment", 50))
            total_weight += weight
        weighted_mean = accum / total_weight if total_weight else 50.0
        target = ml.predict_reputation_target(model, weighted_mean, min(1.0, len(members) / 8.0))
        current = float(faction.get("player_reputation", 50))
        new_rep = int(round(max(0.0, min(100.0, current + (target - current) * _PLAYER_REP_STEP))))
        if new_rep != int(current):
            faction["player_reputation"] = new_rep
            changed.append(faction)
    return changed


# --------------------------------------------------------------------------- #
# Model 4: faction relationship updater (Day 7) — unfreezes the inter-faction
# scores (static since Day 2). Similar collective moods warm a pair, divergent
# ones cool it; shared stress (low morale) cools relations; a restore term pulls
# back toward the original Day-2 seed. The GDD's cut "Political Stability" model,
# brought down to town scale.
# --------------------------------------------------------------------------- #
_FACTION_REL_STEP = 0.5
_FACTION_REL_NOTABLE = 1
_rel_model: Optional[Any] = None
_rel_model_trained = False


def _get_rel_model() -> Optional[Any]:
    global _rel_model, _rel_model_trained
    if not _rel_model_trained:
        _rel_model = ml.train_faction_relationship_model()
        _rel_model_trained = True
    return _rel_model


def _faction_mood_valence(faction_id: str, npcs: list[dict[str, Any]]) -> float:
    members = _faction_members(faction_id, npcs)
    if not members:
        return 0.5
    return sum(
        behavior.MOOD_VALENCE.get(npc.get("current_mood", "neutral"), 0.5) for npc in members
    ) / len(members)


def _faction_pressure(faction: dict[str, Any]) -> float:
    """How far a faction's morale sits below baseline, 0..1 (Demon-Lord stress)."""
    morale = float(faction.get("morale", _DEFAULT_MORALE))
    return max(0.0, min(1.0, (MORALE_BASELINE - morale) / MORALE_BASELINE))


def update_faction_relationships_daily(
    faction_rels: list[dict[str, Any]],
    factions_by_id: dict[str, dict[str, Any]],
    npcs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Drift inter-faction scores one day. Mutates the relationship rows in place
    (capturing the Day-2 seed on first touch); returns {"changed": [row, ...],
    "notes": [{text, mag, a, b}, ...]} sorted by magnitude, for the caller to
    persist and log."""
    model = _get_rel_model()
    valences = {fid: _faction_mood_valence(fid, npcs) for fid in factions_by_id}
    pressures = {fid: _faction_pressure(fac) for fid, fac in factions_by_id.items()}

    changed: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for row in faction_rels:
        a, b = row.get("faction_a_id"), row.get("faction_b_id")
        current = int(row.get("relationship_score", 50))
        # Capture the Day-2 seed once - and persist it even if the score itself
        # doesn't move this dawn, so the restoring force has a stable anchor.
        seed_new = "seed_score" not in row
        if seed_new:
            row["seed_score"] = current
        seed = int(row["seed_score"])
        alignment = 1.0 - abs(valences.get(a, 0.5) - valences.get(b, 0.5))
        pressure = (pressures.get(a, 0.0) + pressures.get(b, 0.0)) / 2.0
        delta = ml.predict_relationship_delta(model, current, seed, alignment, pressure)
        new_score = max(0, min(100, int(round(current + delta * _FACTION_REL_STEP))))
        if new_score == current:
            if seed_new:
                changed.append(row)  # persist the freshly-captured seed
            continue
        row["relationship_score"] = new_score
        changed.append(row)
        if abs(new_score - current) >= _FACTION_REL_NOTABLE:
            name_a = factions_by_id.get(a, {}).get("name", a)
            name_b = factions_by_id.get(b, {}).get("name", b)
            verb = "grow warmer toward" if new_score > current else "grow colder toward"
            notes.append(
                {"text": f"The {name_a} and the {name_b} {verb} one another.",
                 "mag": abs(new_score - current), "a": a, "b": b}
            )
    notes.sort(key=lambda n: n["mag"], reverse=True)
    return {"changed": changed, "notes": notes}
