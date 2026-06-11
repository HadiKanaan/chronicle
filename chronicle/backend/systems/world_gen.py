"""Single-region world generation (Day 2 / User Story 1).

Generates one playable region: a procedural tilemap with a river, clustered
buildings, and ~80 NPCs across three tiers seeded into sensible positions. A
biome clustering model classifies the region and a civilization-seed model
biases where settlement (and therefore NPC homes/work) concentrates. One Tier 1
NPC is chosen as the player's host identity, inheriting that character's
relationships and social context.

The backend is the source of truth: this module builds plain Pydantic models and
hands them to ``database`` for persistence. It performs no rendering.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Optional

import database
from ml import train as ml
from models.faction import Faction, FactionRelationship
from models.npc import (
    BehaviorState,
    CharacterCard,
    FactionAffiliation,
    MoodType,
    NPCRelationship,
    NPCSkills,
    NPCTier,
)
from models.world import Building, Region, Tile, TileType, WorldState


BASE_DIR = Path(__file__).resolve().parent.parent
NAMES_PATH = BASE_DIR / "data" / "names.json"

REGION_ID = "region_aldenmoor"
REGION_NAME = "Aldenmoor"
GRID_W = 48
GRID_H = 48

TIER1_COUNT = 10
TIER2_COUNT = 30
TIER3_COUNT = 40

# Civic buildings: (building_id, display name, type, width, height).
CIVIC_BUILDINGS = [
    ("bld_tavern", "The Gilded Tankard", "tavern", 6, 5),
    ("bld_smithy", "Vane Smithy", "blacksmith", 5, 4),
    ("bld_market", "Aldenmoor Market", "market", 6, 5),
    ("bld_church", "Chapel of the Ashen Light", "church", 6, 6),
    ("bld_hall", "Magistrate Hall", "magistrate_hall", 6, 5),
]
HOUSE_COUNT = 10

# Occupation -> civic building type the NPC works at.
OCC_WORKPLACE = {
    "blacksmith": "blacksmith",
    "magistrate": "magistrate_hall",
    "guard_captain": "magistrate_hall",
    "guard": "magistrate_hall",
    "tavern_keeper": "tavern",
    "merchant": "market",
    "trader": "market",
    "herbalist": "market",
    "priest": "church",
    "courier": "market",
}

# Occupation -> faction id.
FACTION_BY_OCC = {
    "guard_captain": "faction_watch",
    "guard": "faction_watch",
    "magistrate": "faction_watch",
    "merchant": "faction_guild",
    "trader": "faction_guild",
    "tavern_keeper": "faction_guild",
    "blacksmith": "faction_guild",
    "herbalist": "faction_guild",
    "fisherman": "faction_guild",
    "courier": "faction_guild",
    "priest": "faction_church",
}

RELATIONSHIP_TYPES = ["friend", "rival", "business_partner", "kin", "mentor", "neighbor"]

# Starting mood distribution: mostly settled villagers with a few outliers for
# flavor. A uniform draw over MoodType made ~3 in 8 NPCs start fearful/anxious/
# suspicious, which the behavior classifier read as a town in panic on day 1.
INITIAL_MOOD_WEIGHTS = [
    (MoodType.NEUTRAL, 30),
    (MoodType.CONTENT, 30),
    (MoodType.HAPPY, 15),
    (MoodType.ANXIOUS, 8),
    (MoodType.SUSPICIOUS, 7),
    (MoodType.ANGRY, 4),
    (MoodType.GRIEVING, 3),
    (MoodType.FEARFUL, 3),
]


# --------------------------------------------------------------------------- #
# Source data
# --------------------------------------------------------------------------- #
def _load_names() -> dict[str, Any]:
    with NAMES_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# --------------------------------------------------------------------------- #
# Tilemap + buildings
# --------------------------------------------------------------------------- #
def _blank_tiles() -> list[list[Tile]]:
    return [
        [Tile(x=x, y=y, tile_type=TileType.GRASS, passable=True) for x in range(GRID_W)]
        for y in range(GRID_H)
    ]


def _carve_river(tiles: list[list[Tile]], rng: random.Random) -> list[int]:
    """Carve a meandering vertical river near the west edge. Returns river column per row."""
    river_x = 6
    river_columns: list[int] = []
    for y in range(GRID_H):
        river_x += rng.choice([-1, 0, 0, 1])
        river_x = max(3, min(10, river_x))
        river_columns.append(river_x)
        for dx in range(2):
            tile = tiles[y][river_x + dx]
            tile.tile_type = TileType.WATER
            tile.passable = False
    return river_columns


def _plot_features(ax: int, ay: int, river_columns: list[int], rng: random.Random):
    """Derive (fertility, water_proximity, elevation, openness) for a candidate plot."""
    river_x = river_columns[min(ay, GRID_H - 1)]
    dist_to_water = abs(ax - river_x)
    water_proximity = max(0.0, 1.0 - dist_to_water / 20.0)
    fertility = min(1.0, 0.4 + water_proximity * 0.5 + rng.uniform(-0.1, 0.1))
    # Elevation rises toward the eastern edge (away from the valley floor).
    elevation = min(1.0, ax / GRID_W + rng.uniform(-0.05, 0.05))
    openness = rng.uniform(0.3, 0.9)
    return fertility, water_proximity, elevation, openness


def _area_is_clear(tiles: list[list[Tile]], ax: int, ay: int, w: int, h: int) -> bool:
    if ax < 1 or ay < 1 or ax + w >= GRID_W - 1 or ay + h >= GRID_H - 1:
        return False
    for yy in range(ay - 1, ay + h + 1):
        for xx in range(ax - 1, ax + w + 1):
            if tiles[yy][xx].tile_type != TileType.GRASS:
                return False
    return True


def _carve_building(
    tiles: list[list[Tile]],
    b_id: str,
    name: str,
    btype: str,
    ax: int,
    ay: int,
    w: int,
    h: int,
) -> tuple[Building, tuple[int, int]]:
    for yy in range(ay, ay + h):
        for xx in range(ax, ax + w):
            tile = tiles[yy][xx]
            is_border = xx in (ax, ax + w - 1) or yy in (ay, ay + h - 1)
            tile.tile_type = TileType.BUILDING_WALL if is_border else TileType.BUILDING_FLOOR
            tile.passable = not is_border
            tile.building_id = b_id
    # Door at bottom-centre, passable.
    door_x, door_y = ax + w // 2, ay + h - 1
    door = tiles[door_y][door_x]
    door.tile_type = TileType.STONE_PATH
    door.passable = True
    door.building_id = b_id
    centre = (ax + w // 2, ay + h // 2)
    return Building(id=b_id, name=name, building_type=btype, x=ax, y=ay, width=w, height=h), centre


def _generate_layout(
    rng: random.Random,
    river_columns: list[int],
    civ_model: Optional[Any],
    tiles: list[list[Tile]],
) -> tuple[list[Building], dict[str, tuple[int, int]], list[tuple[int, int]]]:
    """Place civic buildings (best plots first) then houses. Uses the civ-seed model
    to rank settlement plots so structures cluster where settlement is plausible."""
    # Candidate anchor grid east of the river.
    plots: list[tuple[int, int]] = []
    for ay in range(4, GRID_H - 8, 8):
        for ax in range(14, GRID_W - 8, 9):
            plots.append((ax, ay))

    scored = [
        (ml.settlement_suitability(civ_model, *_plot_features(ax, ay, river_columns, rng)), ax, ay)
        for (ax, ay) in plots
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    ordered_plots = [(ax, ay) for _, ax, ay in scored]

    buildings: list[Building] = []
    building_centres: dict[str, tuple[int, int]] = {}
    house_centres: list[tuple[int, int]] = []

    queue: list[tuple[str, str, str, int, int]] = list(CIVIC_BUILDINGS)
    for i in range(HOUSE_COUNT):
        queue.append((f"bld_house_{i:02d}", f"House {i + 1}", "house", 3, 3))

    plot_idx = 0
    for b_id, name, btype, w, h in queue:
        placed = False
        while plot_idx < len(ordered_plots):
            ax, ay = ordered_plots[plot_idx]
            plot_idx += 1
            # Small jitter inside the plot for a less grid-like look.
            ax = min(GRID_W - w - 2, ax + rng.randint(0, 2))
            ay = min(GRID_H - h - 2, ay + rng.randint(0, 2))
            if _area_is_clear(tiles, ax, ay, w, h):
                building, centre = _carve_building(tiles, b_id, name, btype, ax, ay, w, h)
                buildings.append(building)
                building_centres[btype if btype != "house" else b_id] = centre
                if btype == "house":
                    house_centres.append(centre)
                placed = True
                break
        if not placed:
            # Fallback: drop the building on the first clear scanline cell.
            for ay in range(4, GRID_H - h - 2):
                for ax in range(14, GRID_W - w - 2):
                    if _area_is_clear(tiles, ax, ay, w, h):
                        building, centre = _carve_building(tiles, b_id, name, btype, ax, ay, w, h)
                        buildings.append(building)
                        building_centres[btype if btype != "house" else b_id] = centre
                        if btype == "house":
                            house_centres.append(centre)
                        placed = True
                        break
                if placed:
                    break
    return buildings, building_centres, house_centres


# --------------------------------------------------------------------------- #
# Factions
# --------------------------------------------------------------------------- #
def _build_factions() -> list[Faction]:
    return [
        Faction(
            id="faction_watch",
            name="Aldenmoor Watch",
            faction_type="civic",
            description="The magistrate's guard, keepers of order and the town gates.",
            color="#3b6fb0",
        ),
        Faction(
            id="faction_guild",
            name="Merchants' Concord",
            faction_type="economic",
            description="A loose guild of traders, smiths, and tavern owners.",
            color="#b0892f",
        ),
        Faction(
            id="faction_church",
            name="Order of the Ashen Light",
            faction_type="religious",
            description="The dominant faith, tending the chapel and the dead.",
            color="#9a9a9a",
        ),
        Faction(
            id="faction_commons",
            name="The Commons",
            faction_type="populace",
            description="Farmers, labourers, and folk with no other banner.",
            color="#5a7d4f",
        ),
    ]


def _faction_relationships() -> list[FactionRelationship]:
    return [
        FactionRelationship(faction_a_id="faction_watch", faction_b_id="faction_guild", relationship_score=60),
        FactionRelationship(faction_a_id="faction_watch", faction_b_id="faction_church", relationship_score=55),
        FactionRelationship(faction_a_id="faction_guild", faction_b_id="faction_church", relationship_score=45),
        FactionRelationship(faction_a_id="faction_commons", faction_b_id="faction_watch", relationship_score=40),
        FactionRelationship(faction_a_id="faction_commons", faction_b_id="faction_guild", relationship_score=50),
    ]


# --------------------------------------------------------------------------- #
# NPCs
# --------------------------------------------------------------------------- #
def _skills_for(occ: str, rng: random.Random) -> NPCSkills:
    skills = NPCSkills(
        combat=rng.randint(5, 25),
        negotiation=rng.randint(5, 25),
        perception=rng.randint(5, 25),
    )
    if occ == "blacksmith":
        skills.smithing = rng.randint(60, 90)
    if occ in ("guard", "guard_captain"):
        skills.combat = rng.randint(50, 85)
        skills.leadership = rng.randint(25, 60)
    if occ in ("merchant", "trader", "tavern_keeper"):
        skills.negotiation = rng.randint(50, 85)
    if occ in ("priest", "herbalist"):
        skills.magic = rng.randint(20, 55)
        skills.perception = rng.randint(40, 70)
    if occ in ("farmer", "peasant", "laborer"):
        skills.farming = rng.randint(40, 75)
    if occ == "magistrate":
        skills.leadership = rng.randint(55, 85)
        skills.negotiation = rng.randint(50, 80)
    return skills


def _age_for(occ: str, tier: int, rng: random.Random) -> int:
    if occ == "child":
        return rng.randint(6, 14)
    if occ == "elder":
        return rng.randint(60, 82)
    if tier == 1:
        return rng.randint(30, 58)
    return rng.randint(18, 65)


def _make_card(
    npc_id: str,
    tier: int,
    occ: str,
    pos: tuple[int, int],
    home: tuple[int, int],
    work: tuple[int, int],
    names: dict[str, Any],
    factions_by_id: dict[str, Faction],
    rng: random.Random,
) -> CharacterCard:
    first = rng.choice(names["human_first"])
    last = rng.choice(names["human_last"])
    name = f"{first} {last}"

    trait_pool = names["personality_traits"]
    if tier == 1:
        traits = rng.sample(trait_pool, 3)
    elif tier == 2:
        traits = rng.sample(trait_pool, 2)
    else:
        traits = rng.sample(trait_pool, 1)

    card = CharacterCard(
        id=npc_id,
        tier=NPCTier(tier),
        name=name,
        age=_age_for(occ, tier, rng),
        species="human",
        occupation=occ,
        region_id=REGION_ID,
        x=float(pos[0]),
        y=float(pos[1]),
        personality_traits=traits,
        skills=_skills_for(occ, rng),
        current_mood=rng.choices(
            [mood for mood, _ in INITIAL_MOOD_WEIGHTS],
            weights=[weight for _, weight in INITIAL_MOOD_WEIGHTS],
        )[0],
        current_behavior=BehaviorState.WORKING,
        home_x=float(home[0]),
        home_y=float(home[1]),
        work_x=float(work[0]),
        work_y=float(work[1]),
        sprite_id="human_base",
    )

    if tier <= 2:
        card.appearance = rng.choice(
            ["weather-worn and lean", "broad-shouldered", "slight and watchful", "greying and tired"]
        )
    if tier == 1:
        card.dark_trait = rng.choice(names["dark_traits"])
        card.redeeming_quality = rng.choice(names["redeeming_qualities"])
        card.trauma = rng.choice(
            [
                "lost family to the eastern plague",
                "survived a raid that razed their birth village",
                "betrayed by a partner and never recovered the debt",
            ]
        )

    # Faction affiliation.
    faction_id = FACTION_BY_OCC.get(occ, "faction_commons")
    faction = factions_by_id[faction_id]
    role = "officer" if tier == 1 and faction_id != "faction_commons" else "member"
    card.faction_affiliations.append(
        FactionAffiliation(
            faction_id=faction_id,
            faction_name=faction.name,
            loyalty=rng.randint(45, 90),
            role=role,
        )
    )
    faction.member_npc_ids.append(npc_id)
    return card


def _work_centre(occ: str, building_centres: dict[str, tuple[int, int]], plaza: tuple[int, int]) -> tuple[int, int]:
    btype = OCC_WORKPLACE.get(occ)
    if btype and btype in building_centres:
        return building_centres[btype]
    return plaza


def _link_relationships(tier1: list[CharacterCard], rng: random.Random) -> None:
    """Give Tier 1 NPCs a small relationship graph among themselves."""
    for card in tier1:
        others = [c for c in tier1 if c.id != card.id]
        for partner in rng.sample(others, k=min(3, len(others))):
            card.relationships.append(
                NPCRelationship(
                    npc_id=partner.id,
                    name=partner.name,
                    relationship_type=rng.choice(RELATIONSHIP_TYPES),
                    sentiment=rng.randint(-40, 80),
                    notes="",
                )
            )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def build_world(seed: Optional[int] = None) -> dict[str, Any]:
    """Build (but do not persist) a full world. Returns models for the caller."""
    rng = random.Random(seed)
    names = _load_names()

    # ML hooks: biome classification + settlement-suitability scoring.
    biome_model = ml.train_biome_model()
    civ_model = ml.train_civilization_seed_model()
    biome = ml.assign_region_biome(biome_model)

    tiles = _blank_tiles()
    river_columns = _carve_river(tiles, rng)
    buildings, building_centres, house_centres = _generate_layout(rng, river_columns, civ_model, tiles)

    plaza = building_centres.get("market") or (GRID_W // 2, GRID_H // 2)
    if not house_centres:
        house_centres = [plaza]

    region = Region(
        id=REGION_ID,
        name=REGION_NAME,
        width=GRID_W,
        height=GRID_H,
        biome=biome,
        tiles=tiles,
        buildings=buildings,
        current_weather="clear",
        season="spring",
    )

    factions = _build_factions()
    factions_by_id = {f.id: f for f in factions}

    # Tier roster: (tier, occupation_pool_key).
    roster: list[tuple[int, str]] = []
    for _ in range(TIER1_COUNT):
        roster.append((1, rng.choice(names["occupations_tier1"])))
    for _ in range(TIER2_COUNT):
        roster.append((2, rng.choice(names["occupations_tier2"])))
    for _ in range(TIER3_COUNT):
        roster.append((3, rng.choice(names["occupations_tier3"])))

    npcs: list[CharacterCard] = []
    for idx, (tier, occ) in enumerate(roster):
        npc_id = f"npc_{idx:05d}"
        home = house_centres[idx % len(house_centres)]
        work = _work_centre(occ, building_centres, plaza)
        # Initial position: at home for Day 2 (no movement yet).
        pos = home
        card = _make_card(npc_id, tier, occ, pos, home, work, names, factions_by_id, rng)
        npcs.append(card)

    tier1 = [c for c in npcs if c.tier == NPCTier.TIER_1]
    _link_relationships(tier1, rng)

    # Host NPC selection: the player inherits an existing Tier 1 identity.
    host = tier1[0]
    host.is_player = True

    world_state = WorldState(
        region=region,
        current_day=1,
        current_hour=6,
        demon_lord_npc_id=None,
        player_npc_id=host.id,
        game_started=True,
    )

    return {
        "world_state": world_state,
        "npcs": npcs,
        "factions": factions,
        "faction_relationships": _faction_relationships(),
        "host_npc_id": host.id,
    }


def generate_world(seed: Optional[int] = None) -> dict[str, Any]:
    """Build a world and persist it to SQLite. Returns a summary dict."""
    world = build_world(seed)

    database.save_world(
        world_state=world["world_state"].model_dump(),
        npcs=[npc.model_dump() for npc in world["npcs"]],
        factions=[faction.model_dump() for faction in world["factions"]],
        faction_relationships=[rel.model_dump() for rel in world["faction_relationships"]],
    )

    host = next(npc for npc in world["npcs"] if npc.id == world["host_npc_id"])
    database.log_event(
        1, 6, "generate_world",
        f"World '{REGION_NAME}' generated: {len(world['npcs'])} NPCs, "
        f"{len(world['factions'])} factions. Player host: {host.name} ({host.occupation}).",
    )

    return {
        "region": REGION_NAME,
        "biome": world["world_state"].region.biome,
        "npc_count": len(world["npcs"]),
        "building_count": len(world["world_state"].region.buildings),
        "faction_count": len(world["factions"]),
        "host_npc_id": world["host_npc_id"],
        "host_name": host.name,
        "ml_available": ml.ml_available(),
    }
