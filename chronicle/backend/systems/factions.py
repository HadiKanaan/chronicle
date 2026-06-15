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

from typing import Any

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


def _faction_members(faction_id: str, npcs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        npc for npc in npcs
        if any(a.get("faction_id") == faction_id for a in npc.get("faction_affiliations", []))
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
