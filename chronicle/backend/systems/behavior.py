"""NPC behavior system (Day 4 / User Story 2).

Each hourly tick re-classifies every simulated NPC's behavior state with the
ML behavior classifier and caches a BFS path toward the place that behavior
implies (home, workplace, tavern, market). A faster movement sub-tick then
pops one path step per real second so NPCs visibly walk at the frontend's
polling cadence instead of teleporting once per hour. Each daily tick (dawn)
rolls every NPC's mood forward with the mood model, appends significant events
to rolling memory buffers, and records dramatic moments as persisted rumors
(structure only — propagation arrives on Day 6).

Operates on the plain dict shapes stored in SQLite; the backend stays the
single source of truth and nothing here touches rendering.
"""

from __future__ import annotations

import math
import random
import re
from collections import deque
from typing import Any, Optional

from ml import train as ml


# Rolling memory: keep only the most recent significant events per NPC.
# Day 8 (RAG): the store holds a deep life now - conversations inject only the
# few memories RELEVANT to what the player just said (systems/recall.py), not
# the most recent, so a large buffer no longer bloats the prompt. The day-stamp
# dedup below still keeps repeats from filling it.
MEMORY_BUFFER_CAP = 50

# Tiles walked per movement sub-tick. The clock pops cached path steps once per
# real second; at 5 real seconds per game hour that is 5 tiles/hour walking and
# 10 tiles/hour fleeing.
WALK_TILES_PER_STEP = 1
FLEE_TILES_PER_STEP = 2

# How NPCs read each mood when deciding what to do and how they feel.
MOOD_VALENCE = {
    "happy": 0.90,
    "content": 0.70,
    "neutral": 0.50,
    "suspicious": 0.40,
    "anxious": 0.35,
    "angry": 0.25,
    "grieving": 0.20,
    "fearful": 0.15,
}

WEATHER_SEVERITY = {"clear": 0.0, "fog": 0.4, "rain": 0.6, "storm": 1.0}

# Moods that mark a day as significant enough to remember and gossip about.
DRAMATIC_MOODS = {"fearful", "angry", "grieving"}
MAX_RUMORS_PER_DAY = 2

_TRAIT_SOCIABILITY = {
    "cheerful": 0.20, "generous": 0.10, "loyal": 0.05,
    "melancholic": -0.20, "suspicious": -0.10, "cautious": -0.05,
}
_OCC_SOCIABILITY = {
    "tavern_keeper": 0.25, "merchant": 0.15, "trader": 0.15,
    "beggar": 0.10, "priest": 0.05,
}
_RESTLESS_OCCUPATIONS = {"courier": 0.85, "wanderer": 0.85, "trader": 0.70, "child": 0.65}

_behavior_model: Optional[Any] = None
_mood_model: Optional[Any] = None
_tile_model: Optional[Any] = None
_models_trained = False

# Day 8 (Model 6): the Witness Memory Tagger trains lazily and separately so
# the event-seeding paths (here and in demon_lord) can share one instance.
_witness_model: Optional[Any] = None
_witness_trained = False

# Drama (0..1) of the standing event kinds, for the witness tagger.
STORM_DRAMA = 0.70
MOOD_RUMOR_DRAMA = 0.55


def _get_models() -> tuple[Optional[Any], Optional[Any], Optional[Any]]:
    """Train the behavior, mood, and tile-interaction models once per process."""
    global _behavior_model, _mood_model, _tile_model, _models_trained
    if not _models_trained:
        _behavior_model = ml.train_behavior_model()
        _mood_model = ml.train_mood_model()
        _tile_model = ml.train_tile_interaction_model()
        _models_trained = True
    return _behavior_model, _mood_model, _tile_model


def _get_witness_model() -> Optional[Any]:
    """Train the Witness Memory Tagger once per process (Model 6)."""
    global _witness_model, _witness_trained
    if not _witness_trained:
        _witness_model = ml.train_witness_model()
        _witness_trained = True
    return _witness_model


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


# --------------------------------------------------------------------------- #
# Feature derivation
# --------------------------------------------------------------------------- #
def _npc_features(npc: dict[str, Any], weather: str, rng: random.Random) -> dict[str, float]:
    """Derive the behavior-classifier features from an NPC card."""
    traits = npc.get("personality_traits", [])
    occupation = npc.get("occupation", "")
    mood = npc.get("current_mood", "neutral")

    sociability = 0.45 + _OCC_SOCIABILITY.get(occupation, 0.0)
    sociability += sum(_TRAIT_SOCIABILITY.get(trait, 0.0) for trait in traits)

    fear = {"fearful": 0.90, "anxious": 0.55, "suspicious": 0.45}.get(mood, 0.20)
    if "cowardly" in traits:
        fear += 0.15
    if "brave" in traits:
        fear -= 0.15
    if weather == "storm":
        fear += 0.10

    restlessness = _RESTLESS_OCCUPATIONS.get(occupation, 0.25)
    if "reckless" in traits:
        restlessness += 0.10
    if "ambitious" in traits:
        restlessness += 0.05

    curiosity = 0.35
    if "curious" in traits:
        curiosity += 0.35
    if "suspicious" in traits:
        curiosity += 0.25

    jitter = lambda v: _clamp(v + rng.uniform(-0.05, 0.05))  # noqa: E731 - tiny local helper
    return {
        "valence": jitter(MOOD_VALENCE.get(mood, 0.5)),
        "sociability": jitter(sociability),
        "fear": jitter(fear),
        "restlessness": jitter(restlessness),
        "curiosity": jitter(curiosity),
        # Occupation's social leaning, fed to the Tile Interaction Scorer so the
        # destination choice knows a tavern-keeper gravitates to the crowd.
        "occ_social": _OCC_SOCIABILITY.get(occupation, 0.0),
    }


# --------------------------------------------------------------------------- #
# Movement
# --------------------------------------------------------------------------- #
def building_centres(region: dict[str, Any]) -> dict[str, tuple[int, int]]:
    """Map building_type -> interior centre tile for behavior destinations."""
    centres: dict[str, tuple[int, int]] = {}
    for building in region.get("buildings", []):
        centre = (
            int(building["x"]) + int(building["width"]) // 2,
            int(building["y"]) + int(building["height"]) // 2,
        )
        centres.setdefault(building["building_type"], centre)
    return centres


def _plaza_centre(centres: dict[str, tuple[int, int]]) -> Optional[tuple[int, int]]:
    """The town's public square: the civic hall, else the chapel, else market."""
    return centres.get("magistrate_hall") or centres.get("church") or centres.get("market")


def _behavior_target(
    npc: dict[str, Any],
    behavior: str,
    hour: int,
    centres: dict[str, tuple[int, int]],
    features: dict[str, float],
    tile_model: Optional[Any],
) -> Optional[tuple[int, int]]:
    """Choose the target tile for an NPC's behavior via the Tile Interaction
    Scorer (Model 5), then resolve the chosen kind to a concrete centre.

    The model only picks the destination KIND; movement and pathing are
    unchanged. Unlike the old random roam, the choice is deterministic given
    the NPC's state, so travelers no longer re-path to a different landmark
    every hour (no thrashing).
    """
    home = (int(npc.get("home_x", 0)), int(npc.get("home_y", 0)))
    work = (int(npc.get("work_x", 0)), int(npc.get("work_y", 0)))
    kind = ml.predict_destination(
        tile_model,
        behavior,
        hour,
        features["valence"],
        features["sociability"],
        features.get("occ_social", 0.0),
    )
    if kind == "work":
        return work
    if kind == "tavern":
        return centres.get("tavern") or centres.get("market") or home
    if kind == "market":
        return centres.get("market") or centres.get("tavern") or home
    if kind == "plaza":
        return _plaza_centre(centres) or home
    # "home" (staying_home, sleeping, fleeing) and any unknown kind shelter home.
    return home


def _compute_path(
    tiles: list[list[dict[str, Any]]],
    start: tuple[int, int],
    target: tuple[int, int],
) -> list[tuple[int, int]]:
    """BFS over passable tiles; return the full path from start to target.

    Full-grid BFS on the 48x48 region is cheap and, unlike greedy stepping,
    routes NPCs through building doors instead of pinning them against walls.
    The path excludes the start tile; it is empty when the NPC has already
    arrived or the target is unreachable. Computed once per hour and cached on
    the NPC so the movement sub-tick only pops steps.
    """
    if start == target:
        return []
    height, width = len(tiles), len(tiles[0])
    if not (0 <= target[0] < width and 0 <= target[1] < height):
        return []
    came_from: dict[tuple[int, int], tuple[int, int]] = {start: start}
    queue: deque[tuple[int, int]] = deque([start])
    while queue:
        current = queue.popleft()
        if current == target:
            break
        cx, cy = current
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in came_from:
                continue
            if not tiles[ny][nx].get("passable", True):
                continue
            came_from[(nx, ny)] = current
            queue.append((nx, ny))
    if target not in came_from:
        return []
    path: list[tuple[int, int]] = []
    node = target
    while node != start:
        path.append(node)
        node = came_from[node]
    path.reverse()
    return path


# --------------------------------------------------------------------------- #
# Hourly tick: behavior states + movement
# --------------------------------------------------------------------------- #
def _is_simulated(npc: dict[str, Any]) -> bool:
    """The player drives their own host; the Demon Lord gets its own system."""
    return not npc.get("is_player") and not npc.get("is_demon_lord")


def update_hourly(
    state: dict[str, Any],
    npcs: list[dict[str, Any]],
    rng: random.Random,
) -> dict[str, Any]:
    """Re-classify behaviors and cache each NPC's path for the coming hour.

    Movement itself happens in update_movement on the faster sub-tick. Mutates
    the NPC dicts in place and returns {"changed": [npc, ...],
    "behavior_counts": {...}} so the caller can persist only what changed.
    """
    behavior_model, _, tile_model = _get_models()
    region = state["region"]
    tiles = region["tiles"]
    weather = region.get("current_weather", "clear")
    hour = int(state.get("current_hour", 6))
    day = int(state.get("current_day", 1))
    centres = building_centres(region)

    changed: list[dict[str, Any]] = []
    behavior_counts: dict[str, int] = {}
    for npc in npcs:
        if not _is_simulated(npc):
            continue
        features = _npc_features(npc, weather, rng)
        behavior = ml.classify_behavior(
            behavior_model,
            hour,
            features["valence"],
            features["sociability"],
            WEATHER_SEVERITY.get(weather, 0.0),
            features["fear"],
            features["restlessness"],
            features["curiosity"],
        )
        behavior_counts[behavior] = behavior_counts.get(behavior, 0) + 1

        npc_changed = False
        if behavior != npc.get("current_behavior"):
            if behavior == "fleeing":
                remember(npc, f"Day {day}: fled to shelter in fear.")
            npc["current_behavior"] = behavior
            npc_changed = True

        target = _behavior_target(npc, behavior, hour, centres, features, tile_model)
        new_path: list[list[int]] = []
        if target is not None:
            start = (int(round(npc.get("x", 0))), int(round(npc.get("y", 0))))
            new_path = [[x, y] for x, y in _compute_path(tiles, start, target)]
        if new_path != npc.get("path", []):
            npc["path"] = new_path
            npc_changed = True

        if npc_changed:
            changed.append(npc)
    return {"changed": changed, "behavior_counts": behavior_counts}


def update_movement(npcs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pop cached path steps for one movement sub-tick.

    Walking NPCs advance one tile, fleeing NPCs two. Returns the NPCs that
    moved so the caller can persist just those.
    """
    changed: list[dict[str, Any]] = []
    for npc in npcs:
        if not _is_simulated(npc):
            continue
        path = npc.get("path") or []
        if not path:
            continue
        steps = (
            FLEE_TILES_PER_STEP
            if npc.get("current_behavior") == "fleeing"
            else WALK_TILES_PER_STEP
        )
        taken = path[:steps]
        npc["path"] = path[len(taken):]
        npc["x"], npc["y"] = float(taken[-1][0]), float(taken[-1][1])
        changed.append(npc)
    return changed


# --------------------------------------------------------------------------- #
# Witness Memory Tagger (Day 8 / Model 6)
# --------------------------------------------------------------------------- #
def perception_norm(npc: dict[str, Any]) -> float:
    """The NPC's perception skill on a 0..1 scale (cards store it 0..100)."""
    skills = npc.get("skills")
    if isinstance(skills, dict):
        raw = skills.get("perception", 10)
    else:
        raw = getattr(skills, "perception", 10)
    try:
        return max(0.0, min(1.0, float(raw) / 100.0))
    except (TypeError, ValueError):
        return 0.10


def region_diagonal(region: dict[str, Any]) -> float:
    """Map diagonal in tiles, used to normalize event distances to 0..1."""
    tiles = region.get("tiles") or []
    width = int(region.get("width") or (len(tiles[0]) if tiles else 64))
    height = int(region.get("height") or (len(tiles) or 64))
    return math.hypot(width, height) or 1.0


def _npc_position(npc: dict[str, Any]) -> tuple[float, float]:
    return (
        float(npc.get("x", npc.get("home_x", 0)) or 0.0),
        float(npc.get("y", npc.get("home_y", 0)) or 0.0),
    )


def select_witnesses(
    candidates: list[dict[str, Any]],
    event_xy: tuple[float, float],
    drama: float,
    diagonal: float,
    *,
    floor: int = 1,
) -> list[dict[str, Any]]:
    """Return which candidate NPCs witness (and so remember) an event.

    Each NPC's chance to register the event rises with their perception, the
    drama, and their proximity to event_xy (Model 6). A floor guarantees at
    least `floor` witnesses - the most perceptive and nearest - so no event
    ever vanishes entirely unseen.
    """
    model = _get_witness_model()
    ex, ey = event_xy
    selected: list[dict[str, Any]] = []
    scored: list[tuple[dict[str, Any], float]] = []
    for npc in candidates:
        perception = perception_norm(npc)
        nx, ny = _npc_position(npc)
        distance = min(1.0, math.hypot(nx - ex, ny - ey) / diagonal)
        scored.append((npc, perception - distance))
        if ml.predict_witnessed(model, perception, distance, drama):
            selected.append(npc)
    if len(selected) < floor and scored:
        # Backfill from the most perceptive, closest candidates to honour the floor.
        for npc, _ in sorted(scored, key=lambda item: item[1], reverse=True):
            if npc not in selected:
                selected.append(npc)
            if len(selected) >= floor:
                break
    return selected


# --------------------------------------------------------------------------- #
# Daily tick: moods, memories, rumors
# --------------------------------------------------------------------------- #
# Memory entries are stamped "Day N: ..."; the stamp is ignored when checking
# for duplicates so a repeated event refreshes rather than stacks.
_DAY_STAMP = re.compile(r"^Day \d+:\s*")
# A doubled stamp ("Day 4: Day 4: ...") leaks when a caller prepends "Day N:" to
# text that already carried one (e.g. a Demon-Lord announcement the model wrote
# starting with a day stamp). Collapse any run of leading stamps to the first
# (the caller's, with the correct current day).
_DOUBLE_DAY_STAMP = re.compile(r"^(Day \d+:\s*)(?:Day \d+:\s*)+")


def remember(npc: dict[str, Any], text: str) -> None:
    """Append a significant event to the NPC's rolling memory buffer.

    A repeat of an event already in the buffer (same text apart from the day
    stamp) replaces the old entry instead of duplicating it - repeated LLM
    conversation memories and recurring storms were filling the 10-slot buffer
    with near-identical lines and squeezing everything else out.
    """
    buffer = npc.setdefault("memory_buffer", [])
    text = _DOUBLE_DAY_STAMP.sub(r"\1", text)  # never store a doubled "Day N: Day N:" stamp
    core = _DAY_STAMP.sub("", text)
    buffer[:] = [entry for entry in buffer if _DAY_STAMP.sub("", entry) != core]
    buffer.append(text)
    if len(buffer) > MEMORY_BUFFER_CAP:
        del buffer[: len(buffer) - MEMORY_BUFFER_CAP]


def _event_valence(npc: dict[str, Any], weather: str, rng: random.Random) -> tuple[float, str]:
    """Score yesterday's most significant event for the mood model."""
    behavior = npc.get("current_behavior", "working")
    if weather == "storm":
        return 0.15, "the storm"
    if behavior == "fleeing":
        return 0.10, "a terrifying flight"
    if behavior == "socializing":
        return 0.75, "an evening of company"
    return rng.uniform(0.35, 0.75), "an ordinary day"


def update_daily(
    state: dict[str, Any],
    npcs: list[dict[str, Any]],
    weather_changed: bool,
    rng: random.Random,
) -> dict[str, Any]:
    """Roll moods, record significant memories, and persist new rumor structures.

    Mutates NPC dicts in place; returns {"changed": [...], "rumors": [rumor, ...],
    "mood_changes": int} — the caller persists both. No propagation: each rumor
    starts known only by its witnesses.
    """
    _, mood_model, _ = _get_models()
    region = state["region"]
    weather = region.get("current_weather", "clear")
    severity = WEATHER_SEVERITY.get(weather, 0.0)
    day = int(state.get("current_day", 1))
    diagonal = region_diagonal(region)
    # Town events radiate from the centre of the map; distance to it gates who
    # actually witnesses them (Model 6).
    town_centre = (
        float(region.get("width", 64)) / 2.0,
        float(region.get("height", 64)) / 2.0,
    )

    npcs_by_id = {npc["id"]: npc for npc in npcs}
    changed: list[dict[str, Any]] = []
    changed_ids: set[str] = set()
    rumors: list[dict[str, Any]] = []
    mood_changes = 0

    def _mark_changed(npc: dict[str, Any]) -> None:
        if npc["id"] not in changed_ids:
            changed_ids.add(npc["id"])
            changed.append(npc)

    if weather_changed and weather == "storm":
        # Only NPCs who actually witness the storm (perception + proximity) carry
        # the memory - the oblivious and the far-flung sleep through it.
        storm_pool = [
            npc for npc in npcs if int(npc.get("tier", 3)) <= 2 and _is_simulated(npc)
        ]
        for npc in select_witnesses(storm_pool, town_centre, STORM_DRAMA, diagonal, floor=1):
            remember(npc, f"Day {day}: a storm broke over Aldenmoor.")
            _mark_changed(npc)
        # The rumor is seeded on the Tier 1 witnesses (its eventual tellers).
        tier1_pool = [n for n in storm_pool if int(n.get("tier", 3)) == 1]
        tier1_witnesses = (
            select_witnesses(tier1_pool, town_centre, STORM_DRAMA, diagonal, floor=1)
            if tier1_pool
            else []
        )
        witnesses = [n["id"] for n in tier1_witnesses][:4]
        rumors.append(
            {
                "id": f"rumor_d{day:03d}_storm",
                "original_event": f"A storm battered Aldenmoor on day {day}.",
                "current_text": f"A storm battered Aldenmoor on day {day}.",
                "distortion_level": 0,
                "known_by_npc_ids": witnesses,
                "propagation_rate": 0.3,
                "decay_rate": 0.05,
                "drama_score": 70,
                "age_days": 0,
                "active": True,
            }
        )

    for npc in npcs:
        if not _is_simulated(npc):
            continue
        old_mood = npc.get("current_mood", "neutral")
        features = _npc_features(npc, weather, rng)
        event_valence, event_desc = _event_valence(npc, weather, rng)
        social = features["sociability"]
        if npc.get("current_behavior") not in ("socializing", "working"):
            social *= 0.6
        new_mood = ml.predict_mood(
            mood_model,
            MOOD_VALENCE.get(old_mood, 0.5),
            event_valence,
            severity,
            social,
        )
        if new_mood == old_mood:
            continue
        npc["current_mood"] = new_mood
        npc["mood_reason"] = f"after {event_desc}"
        mood_changes += 1
        valence_swing = abs(MOOD_VALENCE.get(new_mood, 0.5) - MOOD_VALENCE.get(old_mood, 0.5))
        if new_mood in DRAMATIC_MOODS or valence_swing > 0.3:
            remember(npc, f"Day {day}: woke {new_mood} after {event_desc}.")
            if (
                int(npc.get("tier", 3)) == 1
                and new_mood in DRAMATIC_MOODS
                and len(rumors) < MAX_RUMORS_PER_DAY
                and rng.random() < 0.5
            ):
                text = f"{npc['name']} has been {new_mood} since {event_desc} on day {day}."
                # The NPC always knows their own state; relations learn it only
                # if they're perceptive/near enough to notice the change (Model 6).
                rel_npcs = [
                    npcs_by_id[r["npc_id"]]
                    for r in npc.get("relationships", [])[:2]
                    if r.get("npc_id") in npcs_by_id
                ]
                rel_witnesses = select_witnesses(
                    rel_npcs, _npc_position(npc), MOOD_RUMOR_DRAMA, diagonal, floor=0
                )
                relations = [n["id"] for n in rel_witnesses]
                rumors.append(
                    {
                        "id": f"rumor_d{day:03d}_{npc['id']}",
                        "original_event": text,
                        "current_text": text,
                        "distortion_level": 0,
                        "known_by_npc_ids": [npc["id"], *relations],
                        "propagation_rate": 0.3,
                        "decay_rate": 0.05,
                        "drama_score": 55,
                        "age_days": 0,
                        "active": True,
                    }
                )
        _mark_changed(npc)

    return {"changed": changed, "rumors": rumors, "mood_changes": mood_changes}
