from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TileType(str, Enum):
    GRASS = "grass"
    DIRT = "dirt"
    STONE_PATH = "stone_path"
    WATER = "water"
    BUILDING_FLOOR = "building_floor"
    BUILDING_WALL = "building_wall"


class Tile(BaseModel):
    x: int
    y: int
    tile_type: TileType
    passable: bool
    building_id: Optional[str] = None
    resource: Optional[str] = None


class Building(BaseModel):
    id: str
    name: str
    building_type: str
    x: int
    y: int
    width: int
    height: int
    owner_npc_id: Optional[str] = None


class Region(BaseModel):
    id: str
    name: str
    width: int
    height: int
    biome: str
    tiles: list[list[Tile]]
    buildings: list[Building]
    current_weather: str = "clear"
    season: str = "spring"


class WorldState(BaseModel):
    region: Region
    current_day: int = 1
    current_hour: int = 6
    demon_lord_npc_id: Optional[str] = None
    player_npc_id: Optional[str] = None
    game_started: bool = False
    # Day 6: rolling record of the Demon Lord's dawn decisions
    # ({day, action_type, summary} entries, newest last, capped).
    demon_lord_decisions: list[dict] = Field(default_factory=list)
    # Day 7: persisted fog-of-war exploration set ("x,y" keys for every tile the
    # player has ever seen). Survives restarts; grows as the host NPC walks.
    explored_tiles: list[str] = Field(default_factory=list)


class RenderPayload(BaseModel):
    tiles: list[dict] = Field(default_factory=list)
    npcs: list[dict] = Field(default_factory=list)
    player: Optional[dict] = None
    time_of_day: str
    weather: str
    dialogue: Optional[dict] = None
    notifications: list[str] = Field(default_factory=list)
    faction_reputations: dict[str, int] = Field(default_factory=dict)
    # Day 7: faction cohesion/wellbeing, distinct from player_reputation.
    faction_morale: dict[str, int] = Field(default_factory=dict)
    current_day: int = 1
    current_hour: int = 6
    fog_map: list[dict] = Field(default_factory=list)
    # Day 8 visual flavor: display-ready building footprints (drawn as sprites)
    # and the static decoration scatter (trees/bushes/rocks). Both are
    # render-only - simulation fields stay backend-side.
    buildings: list[dict] = Field(default_factory=list)
    decorations: list[dict] = Field(default_factory=list)
    # Day 8: static dirt-road network connecting building entrances (list of
    # {x, y} tiles), drawn with the kenney dirt tile beneath everything else.
    paths: list[dict] = Field(default_factory=list)
    # Day 8: static town-prop placements ({prop_type, x, y}) dressed around
    # buildings (barrels, crates, haystacks, lamps, signs, wells).
    props: list[dict] = Field(default_factory=list)
    # Day 6: display-ready strings only - rumor summaries and the Demon Lord's
    # recent decisions for the HUD.
    rumors: list[str] = Field(default_factory=list)
    demon_lord_decisions: list[str] = Field(default_factory=list)
    # True while the world clock holds still (dialogue open / daily decision /
    # manual pause). `manually_paused` isolates the sticky demo pause so the UI
    # can show a distinct paused state and a Resume control.
    world_paused: bool = False
    manually_paused: bool = False
    # Demo: which LLM backs conversations now, how long the last call took, and
    # whether the Azure provider is configured (gates the toggle in the UI).
    llm_provider: str = "local"
    llm_last_seconds: float = 0.0
    azure_available: bool = False
    # Day 9 audio: whether Azure NPC voices are configured (creds present) and
    # whether the process-global voice toggle is currently on. The frontend uses
    # the pair to gate its speaker control and the per-reply /api/voice fetch.
    voice_available: bool = False
    voice_enabled: bool = True