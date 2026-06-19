"""Demon Lord antagonist system (Day 6 / User Story 5).

The Demon Lord is injected into the EXISTING live world (a new NPC card plus
world_state.demon_lord_npc_id) - the world is never regenerated for it, since
regeneration would wipe every NPC's accumulated memories and conversations.

Once per in-game day, at dawn, it makes one strategic decision via the LLM:
the prompt carries its strategy profile, the factions (by faction id, never
display name), current whispers, and its recent moves; the model answers with
a JSON decision. action_type is constrained to a fixed enum and re-rolled once
on invalid output; faction_reputation_effects keys are validated exact-first
then fuzzily and unknown keys are dropped. When Ollama is down a rule-based
decision keeps the antagonist visibly active (SC-005: one decision per day).

Locking contract (same as conversations): the slow LLM call runs OUTSIDE the
simulation lock against snapshots; main.py applies the decision's effects
under _sim_lock via apply_decision, which writes faction reputations, victim
moods (this is where the reserved grieving/suspicious moods enter the world),
a fresh high-drama rumor, the game log, and the decision record on world
state. LLM transport reuses conversation._call_llm, so every call rides the
single-call queue with think=False.
"""

from __future__ import annotations

import random
import re
from typing import Any, Optional

import database
from models.npc import CharacterCard, NPCSkills, NPCTier
from systems import behavior, conversation


DEMON_LORD_ID = "npc_demon_lord"
DEMON_LORD_NAME = "Vhal'Zur, the Veiled Flame"
DEMON_LORD_SPRITE = "npc_wizard"

# The only moves the Demon Lord can make. The LLM picks one; everything else
# about the decision (announcement, effects) colors how it lands.
ACTION_TYPES = (
    "spread_fear",
    "raid_supplies",
    "demand_tribute",
    "corrupt_official",
    "dark_omen",
)

# Per-action fallout: (mood for the worst-affected villagers, victim count).
# raid_supplies and corrupt_official/dark_omen are the story events that emit
# the reserved grieving/suspicious moods the daily mood model never produces.
ACTION_MOODS = {
    "spread_fear": ("fearful", 3),
    "raid_supplies": ("grieving", 2),
    "demand_tribute": ("anxious", 2),
    "corrupt_official": ("suspicious", 3),
    "dark_omen": ("suspicious", 2),
}

ACTION_PHRASES = {
    "spread_fear": "whispered terrors",
    "raid_supplies": "night raid",
    "demand_tribute": "demand for tribute",
    "corrupt_official": "corrupting whispers",
    "dark_omen": "dark omen",
}

# Reputation fallout when the LLM supplies no usable effects of its own.
ACTION_DEFAULT_EFFECTS = {
    "spread_fear": {"faction_commons": -4},
    "raid_supplies": {"faction_guild": -6},
    "demand_tribute": {"faction_guild": -5},
    "corrupt_official": {"faction_watch": -6},
    "dark_omen": {"faction_church": -4},
}

REPUTATION_EFFECT_LIMIT = 8
ANNOUNCEMENT_MAX_CHARS = 240
DECISIONS_KEPT = 7
DECISION_NUM_PREDICT = 300

STRATEGY_PROFILE = (
    "Your long game is to break Aldenmoor's will without open war: erode trust "
    "between the factions, let fear and suspicion do the killing, and keep your "
    "own hand hidden. You are patient, theatrical, and contemptuous of mortals. "
    "You prefer whispers, omens, and proxies over slaughter - terror spent "
    "carefully lasts longer than blood."
)

_rng = random.Random()

_STUB_ANNOUNCEMENTS = {
    "spread_fear": "Voices in the night fog repeat the Demon Lord's name, and doors are barred before dusk.",
    "raid_supplies": "Cultists struck the market stores before dawn and melted away, leaving ash sigils on the doors.",
    "demand_tribute": "A black-sealed letter demands tribute for the Veiled Flame, or the river will run thick with rot.",
    "corrupt_official": "Someone in Aldenmoor now answers to the Demon Lord, the whispers say - but no one knows who.",
    "dark_omen": "The dawn sky bled red over the eastern hills, and every bell in the chapel rang on its own.",
}


# --------------------------------------------------------------------------- #
# Injection into the existing world
# --------------------------------------------------------------------------- #
def _lair_position(region: dict[str, Any]) -> tuple[float, float]:
    """A passable tile near the north-east corner: far from town, still on map."""
    tiles = region.get("tiles", [])
    height = int(region.get("height", len(tiles)))
    width = int(region.get("width", len(tiles[0]) if tiles else 0))
    for y in range(1, height - 1):
        for x in range(width - 2, 0, -1):
            row_y, col_x = y, x
            try:
                tile = tiles[row_y][col_x]
            except (IndexError, TypeError):
                continue
            passable = tile.get("passable", True) if isinstance(tile, dict) else tile.passable
            if passable:
                return float(col_x), float(row_y)
    return float(max(0, width - 2)), 1.0


def build_demon_lord(region: dict[str, Any]) -> dict[str, Any]:
    """A hand-authored Tier 1 card for the antagonist (no LLM enrichment pass)."""
    x, y = _lair_position(region)
    card = CharacterCard(
        id=DEMON_LORD_ID,
        tier=NPCTier.TIER_1,
        name=DEMON_LORD_NAME,
        age=666,
        species="demon",
        occupation="demon lord",
        region_id=str(region.get("id", "region_aldenmoor")),
        x=x,
        y=y,
        appearance="a tall figure wrapped in heat-shimmer, eyes like banked coals",
        personality_traits=["ancient", "patient", "cruel"],
        dark_trait="feeds on a town's slow despair, savoring it like wine",
        redeeming_quality="keeps every bargain to the letter",
        trauma="cast down once by a faith that has since forgotten how",
        skills=NPCSkills(combat=95, magic=95, leadership=80, perception=85, negotiation=70),
        conversation_style="cold, courteous, and threatening; never raises its voice",
        # Hand-authored card: skip the Tier 1 LLM enrichment pass.
        llm_enriched=True,
        is_demon_lord=True,
        home_x=x,
        home_y=y,
        work_x=x,
        work_y=y,
        sprite_id=DEMON_LORD_SPRITE,
    )
    return card.model_dump()


# --------------------------------------------------------------------------- #
# Decision generation (LLM with one re-roll, then rule-based fallback)
# --------------------------------------------------------------------------- #
def _normalize_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def match_faction_id(value: Any, factions: list[dict[str, Any]]) -> Optional[str]:
    """Resolve a model-written faction reference to a real faction id.

    Exact id match first; then fuzzy: ids without the faction_ prefix, display
    names, and substring containment either way. Returns None when nothing
    matches - the caller drops the entry rather than guessing.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    key = _normalize_key(value)
    ids = [str(f.get("id", "")) for f in factions]
    if key in ids:
        return key
    for faction in factions:
        faction_id = str(faction.get("id", ""))
        if key == faction_id.removeprefix("faction_"):
            return faction_id
        name = _normalize_key(str(faction.get("name", "")))
        if name and (key == name or key in name or name in key):
            return faction_id
        if key in faction_id:
            return faction_id
    return None


def _validate_effects(
    raw: Any,
    factions: list[dict[str, Any]],
) -> dict[str, int]:
    """Keep only effects whose keys resolve to real faction ids, clamped."""
    effects: dict[str, int] = {}
    if not isinstance(raw, dict):
        return effects
    for key, value in raw.items():
        faction_id = match_faction_id(key, factions)
        if faction_id is None:
            continue
        try:
            delta = int(value)
        except (TypeError, ValueError):
            continue
        effects[faction_id] = max(-REPUTATION_EFFECT_LIMIT, min(REPUTATION_EFFECT_LIMIT, delta))
    return effects


def parse_decision(raw: str, factions: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Validate one LLM decision. None means invalid -> the caller re-rolls."""
    data = conversation._extract_json(raw)
    if data is None:
        return None
    action = _normalize_key(str(data.get("action_type", "")))
    if action not in ACTION_TYPES:
        return None
    target = match_faction_id(data.get("target_faction"), factions)
    announcement = str(data.get("announcement", "")).strip()
    # Strip a leading "Day N:" the model sometimes copies from the stamped
    # whispers in its prompt - otherwise it doubles when remember()/the summary
    # prepend the day, and rides into the rumor text.
    announcement = re.sub(r"^\s*Day\s+\d+:\s*", "", announcement)[:ANNOUNCEMENT_MAX_CHARS]
    if not announcement:
        announcement = _STUB_ANNOUNCEMENTS[action]
    effects = _validate_effects(data.get("faction_reputation_effects"), factions)
    if not effects:
        effects = {target: -5} if target else dict(ACTION_DEFAULT_EFFECTS[action])
    return {
        "action_type": action,
        "target_faction": target,
        "announcement": announcement,
        "faction_reputation_effects": effects,
        "used_llm": True,
    }


def stub_decision(factions: list[dict[str, Any]]) -> dict[str, Any]:
    """Rule-based decision so the antagonist still acts when Ollama is down."""
    action = _rng.choice(ACTION_TYPES)
    effects = {
        fid: delta
        for fid, delta in ACTION_DEFAULT_EFFECTS[action].items()
        if match_faction_id(fid, factions)
    }
    return {
        "action_type": action,
        "target_faction": next(iter(effects), None),
        "announcement": _STUB_ANNOUNCEMENTS[action],
        "faction_reputation_effects": effects,
        "used_llm": False,
    }


def build_decision_prompt(
    demon: dict[str, Any],
    state: dict[str, Any],
    factions: list[dict[str, Any]],
    recent_rumors: list[dict[str, Any]],
) -> str:
    day = int(state.get("current_day", 1))
    weather = state.get("region", {}).get("current_weather", "clear")
    actions = ", ".join(ACTION_TYPES)
    # Static text (identity, profile, contract) leads; volatile state (day,
    # standings, whispers, past moves) trails - so consecutive dawn calls share
    # a prompt prefix and Ollama's cache skips re-evaluating the fixed half.
    lines = [
        f"You are {demon.get('name', DEMON_LORD_NAME)}, the Demon Lord whose shadow "
        "lengthens over Aldenmoor, a small medieval river town.",
        STRATEGY_PROFILE,
        "Each dawn you make ONE strategic move. Respond ONLY with one JSON "
        'object exactly like this: {"action_type": "<one of: ' + actions + '>", '
        '"target_faction": "<a faction id from the list below, or empty string>", '
        '"announcement": "<1-2 plain, concrete sentences naming what you actually '
        "did this dawn (the action above) and what changed in the town - who or "
        "what was struck. Do NOT open with generic night/shadow/silence imagery "
        "(no 'night fell', 'shadows stir', 'something shifted'), do NOT start with "
        "a date, and do NOT reuse the wording of your recent moves below>\", "
        '"faction_reputation_effects": {"<faction id>": <integer -8..8>}} '
        "Every key in faction_reputation_effects must be a faction id from the "
        "list below. Always include all four fields.",
        f"Today is day {day}. The weather is {weather}.",
        "The factions of Aldenmoor - refer to them ONLY by faction id:",
    ]
    for faction in factions:
        lines.append(
            f"- {faction.get('id')} (standing {faction.get('player_reputation', 50)}/100): "
            f"{faction.get('description', '')}"
        )
    rumor_texts = [r.get("current_text", "") for r in recent_rumors if r.get("current_text")]
    if rumor_texts:
        lines.append("What the town already whispers:")
        lines.extend(f"- {text}" for text in rumor_texts[-3:])
    past = state.get("demon_lord_decisions", [])
    if past:
        lines.append("Your recent moves (do not reuse their wording, imagery, or openings):")
        lines.extend(f"- {entry.get('summary', '')}" for entry in past[-3:])
    return "\n".join(lines)


def generate_decision(
    demon: dict[str, Any],
    state: dict[str, Any],
    factions: list[dict[str, Any]],
    recent_rumors: list[dict[str, Any]],
) -> dict[str, Any]:
    """One dawn decision. Slow: rides the single-call LLM queue - never call
    under the simulation lock. Re-rolls once on invalid output, then falls
    back to the rule-based decision."""
    prompt = build_decision_prompt(demon, state, factions, recent_rumors)
    for _ in range(2):
        raw = conversation._call_llm(
            system=prompt,
            user="Decide today's move now. Respond ONLY with the JSON object.",
            json_format=True,
            num_predict=DECISION_NUM_PREDICT,
            temperature=0.9,
        )
        if raw is None:
            break
        decision = parse_decision(raw, factions)
        if decision is not None:
            return decision
    return stub_decision(factions)


# --------------------------------------------------------------------------- #
# Decision effects (caller holds the simulation lock)
# --------------------------------------------------------------------------- #
def _pick_victims(
    decision: dict[str, Any],
    npcs: list[dict[str, Any]],
    count: int,
) -> list[dict[str, Any]]:
    """The villagers who bear the brunt: members of the hardest-hit faction
    first, then any other simulated Tier 1/2 NPC."""
    effects = decision.get("faction_reputation_effects", {})
    worst_faction = min(effects, key=effects.get) if effects else None
    candidates = [
        npc for npc in npcs
        if not npc.get("is_player")
        and not npc.get("is_demon_lord")
        and int(npc.get("tier", 3)) <= 2
    ]
    in_faction = [
        npc for npc in candidates
        if any(a.get("faction_id") == worst_faction for a in npc.get("faction_affiliations", []))
    ]
    pool = in_faction or candidates
    return _rng.sample(pool, k=min(count, len(pool)))


def apply_decision(decision: dict[str, Any], day: int) -> dict[str, Any]:
    """Write one decision's effects into the world. Caller MUST hold _sim_lock.

    Effects: faction reputations shift, the worst-hit villagers take a story
    mood (grieving/suspicious enter here) and a memory, the announcement is
    born as a high-drama rumor seeded on its witnesses, the decision lands in
    the game log and in world_state.demon_lord_decisions (display-ready).
    """
    from systems import rumors as rumor_system

    action = decision["action_type"]
    announcement = decision["announcement"]

    # Day 7: the Demon Lord erodes faction MORALE (cohesion/wellbeing), not the
    # town's regard for the player. player_reputation is now purely player-driven
    # (the Player Reputation Scorer). Each hit also lands in the faction history.
    hit_factions = 0
    for faction_id, delta in decision.get("faction_reputation_effects", {}).items():
        if database.adjust_faction_morale(faction_id, delta) is not None:
            database.append_faction_history(
                faction_id, day, f"struck by the Demon Lord's {ACTION_PHRASES[action]}"
            )
            hit_factions += 1
    if hit_factions:
        database.log_event(
            day, 6, "faction",
            f"Morale falters in {hit_factions} faction(s) after the Demon Lord's "
            f"{ACTION_PHRASES[action]}.",
        )

    npcs = database.get_all_npcs()
    mood, victim_count = ACTION_MOODS[action]
    victims = _pick_victims(decision, npcs, victim_count)
    for victim in victims:
        victim["current_mood"] = mood
        victim["mood_reason"] = f"after the Demon Lord's {ACTION_PHRASES[action]}"
        behavior.remember(victim, f"Day {day}: {announcement}")

    witnesses = victims + [
        npc for npc in npcs
        if int(npc.get("tier", 3)) == 1
        and not npc.get("is_player")
        and not npc.get("is_demon_lord")
        and npc not in victims
    ][:2]
    rumor = {
        "id": f"rumor_d{day:03d}_demonlord",
        "original_event": announcement,
        "current_text": announcement,
        "distortion_level": 0,
        "known_by_npc_ids": [npc["id"] for npc in witnesses],
        "propagation_rate": 0.45,
        "decay_rate": 0.05,
        "drama_score": 85,
        "age_days": 0,
        "active": True,
    }
    rumor_system.seed_knowledge(rumor, {npc["id"]: npc for npc in witnesses})
    database.save_rumor(rumor)
    database.save_npcs(witnesses)

    summary = f"Day {day}: {announcement}"
    state = database.get_world_state()
    if state is not None:
        decisions = state.setdefault("demon_lord_decisions", [])
        decisions.append({"day": day, "action_type": action, "summary": summary})
        if len(decisions) > DECISIONS_KEPT:
            del decisions[: len(decisions) - DECISIONS_KEPT]
        database.save_world_state(state)

    database.log_event(day, 6, "demon_lord", f"The Demon Lord acts: {announcement}")
    return {"summary": summary, "victims": [npc["name"] for npc in victims], "mood": mood}
