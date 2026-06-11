from __future__ import annotations

from pydantic import BaseModel, Field


class Faction(BaseModel):
    id: str
    name: str
    faction_type: str
    description: str
    color: str
    member_npc_ids: list[str] = Field(default_factory=list)
    player_reputation: int = 50


class FactionRelationship(BaseModel):
    faction_a_id: str
    faction_b_id: str
    relationship_score: int
