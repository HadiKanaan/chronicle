from __future__ import annotations

from pydantic import BaseModel, Field


class Faction(BaseModel):
    id: str
    name: str
    faction_type: str
    description: str
    color: str
    member_npc_ids: list[str] = Field(default_factory=list)
    # How the faction regards the PLAYER (0-100). Day 7: this is now purely
    # player-driven (the Player Reputation Scorer, Command 3); the Demon Lord no
    # longer touches it.
    player_reputation: int = 50
    # Faction cohesion / wellbeing (0-100). Day 7: the Demon Lord's pressure
    # lands HERE, and it drifts back toward a baseline from member moods so it
    # never ratchets to 0.
    morale: int = 60
    # Rolling narrative log ({day, text}), capped - mirrors the NPC memory buffer
    # so each faction reads as a stateful entity with a history.
    history: list[dict] = Field(default_factory=list)


class FactionRelationship(BaseModel):
    faction_a_id: str
    faction_b_id: str
    relationship_score: int
