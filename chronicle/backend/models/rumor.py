from __future__ import annotations

from pydantic import BaseModel, Field


class Rumor(BaseModel):
    id: str
    original_event: str
    current_text: str
    distortion_level: int = 0
    known_by_npc_ids: list[str] = Field(default_factory=list)
    propagation_rate: float = 0.3
    decay_rate: float = 0.05
    drama_score: int = 50
    age_days: int = 0
    active: bool = True
