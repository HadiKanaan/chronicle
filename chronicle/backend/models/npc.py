from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class NPCTier(int, Enum):
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3


class MoodType(str, Enum):
    HAPPY = "happy"
    CONTENT = "content"
    ANXIOUS = "anxious"
    ANGRY = "angry"
    FEARFUL = "fearful"
    GRIEVING = "grieving"
    SUSPICIOUS = "suspicious"
    NEUTRAL = "neutral"


class BehaviorState(str, Enum):
    WORKING = "working"
    SOCIALIZING = "socializing"
    STAYING_HOME = "staying_home"
    TRAVELING = "traveling"
    SLEEPING = "sleeping"
    FLEEING = "fleeing"
    SEEKING_INFO = "seeking_info"


class NPCRelationship(BaseModel):
    npc_id: str
    name: str
    relationship_type: str
    sentiment: int
    notes: str = ""


class FactionAffiliation(BaseModel):
    faction_id: str
    faction_name: str
    loyalty: int
    role: str


class NPCSkills(BaseModel):
    combat: int = 10
    negotiation: int = 10
    perception: int = 10
    smithing: int = 0
    farming: int = 0
    magic: int = 0
    stealth: int = 0
    leadership: int = 0


class CharacterCard(BaseModel):
    id: str
    tier: NPCTier
    name: str
    age: int
    species: str = "human"
    occupation: str
    region_id: str
    x: float
    y: float
    appearance: str = ""
    personality_traits: list[str] = Field(default_factory=list)
    dark_trait: str = ""
    redeeming_quality: str = ""
    trauma: str = ""
    skills: NPCSkills = Field(default_factory=NPCSkills)
    current_mood: MoodType = MoodType.NEUTRAL
    mood_reason: str = ""
    faction_affiliations: list[FactionAffiliation] = Field(default_factory=list)
    relationships: list[NPCRelationship] = Field(default_factory=list)
    memory_buffer: list[str] = Field(default_factory=list)
    player_sentiment: int = 50
    rumor_knowledge: list[str] = Field(default_factory=list)
    current_behavior: BehaviorState = BehaviorState.WORKING
    home_x: float = 0
    home_y: float = 0
    work_x: float = 0
    work_y: float = 0
    is_demon_lord: bool = False
    is_player: bool = False
    sprite_id: str = "human_base"
