from __future__ import annotations

import asyncio
import random
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database import (
    get_all_factions,
    get_all_npcs,
    get_npc,
    get_npcs_by_tier,
    get_recent_log,
    get_world_state,
    init_db,
    log_event,
    save_npc,
    save_npcs,
    save_rumor,
    save_world_state,
    world_is_generated,
)
from models.world import RenderPayload, WorldState
from systems import behavior, conversation, weather, world_gen


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

# Local frontend dev origins (Vite). Explicit origins instead of "*" so the CORS
# config stays valid even if credentialed requests are ever introduced.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Autonomous world clock (Day 4): each real-time interval advances one in-game
# hour, re-classifying NPC behavior and caching paths; at dawn the daily tick
# rolls weather, moods, memories, and rumor structures. Between hours, a faster
# movement sub-tick pops one cached path step per second so NPC motion is
# visible at the frontend's 500ms polling cadence instead of jumping hourly.
TICK_ENABLED = True
REAL_SECONDS_PER_GAME_HOUR = 5.0
REAL_SECONDS_PER_MOVE_STEP = 1.0
MOVE_STEPS_PER_HOUR = max(1, int(REAL_SECONDS_PER_GAME_HOUR / REAL_SECONDS_PER_MOVE_STEP))

_tick_rng = random.Random()

# Serializes simulation writes. The tick functions load-mutate-save NPC dicts
# on a worker thread; any other writer that touches simulated NPC state (the
# Day 5 conversation endpoint applying card deltas) MUST hold this lock for its
# whole read-modify-write, or the tick's bulk save will silently overwrite it.
# Player-only writes (_apply_move) don't need it: the simulation never writes
# the player NPC.
_sim_lock = threading.Lock()


def _advance_one_hour() -> None:
    """Advance the authoritative clock by one in-game hour.

    Hourly: the behavior classifier re-evaluates every simulated NPC and walks
    them toward home/work/tavern. Daily (at dawn): the weather classifier rolls
    the region's weather, the mood model updates every NPC, significant events
    land in rolling memory buffers, and new rumor structures persist (no
    propagation until Day 6). Demon Lord updates join on Day 6.
    """
    with _sim_lock:
        _advance_one_hour_locked()


def _advance_one_hour_locked() -> None:
    state = get_world_state()
    if not state:
        return
    hour = int(state.get("current_hour", 6)) + 1
    if hour >= 24:
        hour = 0
        state["current_day"] = int(state.get("current_day", 1)) + 1
    state["current_hour"] = hour
    day = int(state.get("current_day", 1))

    npcs = get_all_npcs()
    changed_ids: set[str] = set()
    changed: list[dict[str, Any]] = []

    def _collect(updated: list[dict[str, Any]]) -> None:
        for npc in updated:
            if npc["id"] not in changed_ids:
                changed_ids.add(npc["id"])
                changed.append(npc)

    if weather.is_daily_tick(hour):
        weather_changed = weather.advance_weather(state["region"], _tick_rng)
        if weather_changed:
            log_event(
                day, hour, "weather",
                f"The weather turned to {state['region']['current_weather']}.",
            )
        daily = behavior.update_daily(state, npcs, weather_changed, _tick_rng)
        _collect(daily["changed"])
        for rumor in daily["rumors"]:
            save_rumor(rumor)
            log_event(day, hour, "rumor", f"Word spreads: {rumor['current_text']}")
        log_event(
            day, hour, "daily_tick",
            f"Dawn of day {day}: {daily['mood_changes']} moods shifted, "
            f"weather {state['region']['current_weather']}.",
        )

    hourly = behavior.update_hourly(state, npcs, _tick_rng)
    _collect(hourly["changed"])
    # Take the hour's first movement step immediately so the hour boundary
    # isn't a frozen second; the sub-tick loop pops the rest.
    _collect(behavior.update_movement(npcs))

    save_npcs(changed)
    save_world_state(state)


def _advance_one_move_step() -> None:
    """Pop one cached path step per NPC (movement sub-tick, no clock change)."""
    with _sim_lock:
        npcs = get_all_npcs()
        moved = behavior.update_movement(npcs)
        save_npcs(moved)


async def _world_tick_loop() -> None:
    """Advance game time on a real-time interval, independent of the player.

    Every REAL_SECONDS_PER_MOVE_STEP a movement sub-tick pops cached path
    steps; every MOVE_STEPS_PER_HOUR-th tick advances the in-game hour instead
    (which also re-classifies behavior and recomputes paths). Runs in the
    background so the world progresses whether or not the frontend is polling.
    DB work is offloaded to a thread so it never blocks the event loop that
    serves /api/state, and each tick is isolated so one failure can't stop the
    clock.
    """
    step = 0
    while True:
        await asyncio.sleep(REAL_SECONDS_PER_MOVE_STEP)
        step = (step + 1) % MOVE_STEPS_PER_HOUR
        advance = _advance_one_hour if step == 0 else _advance_one_move_step
        try:
            await asyncio.to_thread(advance)
        except Exception as exc:  # noqa: BLE001 - never let one tick kill the clock
            log_event(0, 0, "tick_error", f"World tick failed: {exc}")


def _warm_llm_and_enrich_tier1() -> None:
    """Pre-warm the LLM, then enrich any un-enriched Tier 1 cards (Day 5).

    Runs once per startup on a daemon thread. The slow LLM calls happen outside
    the simulation lock (each one rides the conversation module's single-call
    queue); only the read-modify-write of each card holds _sim_lock, so the
    world clock never stalls behind a generation. Conversations that arrive
    mid-enrichment simply queue behind the in-flight call.
    """
    if not conversation.llm_available():
        log_event(0, 0, "llm", "Ollama unreachable; conversations will use stub replies.")
        return
    conversation.prewarm()
    enriched = 0
    for npc in get_npcs_by_tier(1):
        if npc.get("is_player") or npc.get("llm_enriched"):
            continue
        details = conversation.generate_card_details(npc)
        if details is None:
            continue
        with _sim_lock:
            fresh = get_npc(npc["id"])
            if fresh is None:
                continue
            fresh.update(details)
            fresh["llm_enriched"] = True
            save_npc(fresh)
        enriched += 1
    if enriched:
        log_event(0, 0, "llm", f"LLM enriched {enriched} Tier 1 character card(s).")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    # Generate the single region once; reopen the existing world on later starts.
    if not world_is_generated():
        summary = world_gen.generate_world()
        log_event(
            1, 6, "startup",
            f"Generated new world: {summary['npc_count']} NPCs in {summary['region']} "
            f"({summary['biome']}).",
        )
    tick_task = asyncio.create_task(_world_tick_loop()) if TICK_ENABLED else None
    # Day 5: warm the conversation model and flesh out Tier 1 cards without
    # blocking startup; daemon so it never holds up shutdown.
    threading.Thread(target=_warm_llm_and_enrich_tier1, daemon=True).start()
    try:
        yield
    finally:
        if tick_task is not None:
            tick_task.cancel()


app = FastAPI(title="Chronicle of the Velvet Lies API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PlayerInput(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


_MOVE_DELTAS = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


def _apply_move(direction: str) -> bool:
    """Move the player's host NPC one passable tile and persist it.

    The backend stays authoritative for position: the frontend only posts intent
    ("move left"), and the camera scroll the player sees is a consequence of this
    write showing up on the next /api/state poll.
    """
    delta = _MOVE_DELTAS.get(direction)
    if delta is None:
        return False
    state = get_world_state()
    if not state:
        return False
    player_id = state.get("player_npc_id")
    if not player_id:
        return False
    npc = get_npc(player_id)
    if not npc:
        return False

    region = state["region"]
    target_x = int(round(npc.get("x", 0))) + delta[0]
    target_y = int(round(npc.get("y", 0))) + delta[1]
    if not (0 <= target_x < region["width"] and 0 <= target_y < region["height"]):
        return False
    tile = region["tiles"][target_y][target_x]
    if not tile.get("passable", True):
        return False

    npc["x"] = float(target_x)
    npc["y"] = float(target_y)
    save_npc(npc)
    return True


def _empty_render_payload() -> RenderPayload:
    return RenderPayload(
        tiles=[],
        npcs=[],
        player=None,
        time_of_day="dawn",
        weather="clear",
        dialogue=None,
        notifications=[],
        faction_reputations={},
        current_day=1,
        current_hour=6,
        fog_map=[],
    )


def _visible_npc_summary(npc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": npc.get("id"),
        "x": npc.get("x", 0),
        "y": npc.get("y", 0),
        "sprite_id": npc.get("sprite_id", "human_base"),
        "name": npc.get("name", "Unknown"),
        "tier": npc.get("tier", 3),
        # Day 4: behavior and mood summaries so the renderer can show why NPCs
        # are where they are (display-only; backend remains the authority).
        "behavior": npc.get("current_behavior", "working"),
        "mood": npc.get("current_mood", "neutral"),
    }


def _build_render_payload() -> RenderPayload:
    world_state_data = get_world_state()
    if world_state_data is None:
        return _empty_render_payload()

    world_state = WorldState.model_validate(world_state_data)
    region = world_state.region
    all_npcs = get_all_npcs()

    npc_payload: list[dict[str, Any]] = []
    player_payload: Optional[dict[str, Any]] = None
    for npc in all_npcs:
        visible = _visible_npc_summary(npc)
        if world_state.player_npc_id is not None and npc.get("id") == world_state.player_npc_id:
            player_payload = {
                "npc_id": npc.get("id"),
                "x": visible["x"],
                "y": visible["y"],
                "sprite_id": visible["sprite_id"],
                "name": npc.get("name", "Unknown"),
                "occupation": npc.get("occupation", ""),
                "tier": npc.get("tier", 1),
                "mood": npc.get("current_mood", "neutral"),
                # Inherited social context from the host NPC identity (US1).
                "relationships": npc.get("relationships", []),
                "faction_affiliations": npc.get("faction_affiliations", []),
            }
            continue
        npc_payload.append(visible)

    # Render tiles carry only display fields (x, y, tile_type) per the API
    # contract; simulation-only fields (passable, building_id, resource) stay on
    # the backend so the per-poll payload stays lean and the frontend stays dumb.
    tiles = [
        {"x": tile.x, "y": tile.y, "tile_type": tile.tile_type.value}
        for row in region.tiles
        for tile in row
    ]
    faction_reputations = {
        faction["name"]: faction.get("player_reputation", 50)
        for faction in get_all_factions()
    }
    notifications = [entry["description"] for entry in get_recent_log(limit=5)]

    fog_map = world_state_data.get("fog_map", []) if isinstance(world_state_data, dict) else []

    return RenderPayload(
        tiles=tiles,
        npcs=npc_payload,
        player=player_payload,
        time_of_day=weather.hour_to_time_of_day(world_state.current_hour),
        weather=region.current_weather,
        dialogue=world_state_data.get("dialogue") if isinstance(world_state_data, dict) else None,
        notifications=notifications,
        faction_reputations=faction_reputations,
        current_day=world_state.current_day,
        current_hour=world_state.current_hour,
        fog_map=fog_map,
    )


@app.get("/api/state", response_model=RenderPayload)
def get_state() -> RenderPayload:
    return _build_render_payload()


@app.post("/api/input")
def post_input(player_input: PlayerInput) -> JSONResponse:
    # Movement is high-frequency, so it updates state silently (no log spam).
    # Interactions are rare and player-facing, so they are logged.
    if player_input.type == "move":
        accepted = _apply_move(str(player_input.payload.get("direction", "")))
        return JSONResponse({"status": "ok", "accepted": accepted})

    log_event(1, 6, player_input.type, f"Input received: {player_input.type}")
    return JSONResponse({"status": "ok", "accepted": True})


class ConversationInput(BaseModel):
    npc_id: str
    player_text: str = Field(min_length=1, max_length=300)


def _apply_conversation_delta(
    npc_id: str,
    player_name: str,
    player_text: str,
    delta: dict[str, Any],
    day: int,
    hour: int,
) -> Optional[dict[str, Any]]:
    """Apply a parsed card delta to the NPC and persist it. Returns the card.

    Holds _sim_lock for the whole read-modify-write: the hourly tick bulk-saves
    NPCs from its own snapshot, so an unlocked write here would be silently
    overwritten. The NPC is re-fetched inside the lock because the tick may
    have moved or re-moodified it while the LLM was generating.
    """
    with _sim_lock:
        npc = get_npc(npc_id)
        if npc is None:
            return None
        npc["current_mood"] = delta.get("mood", npc.get("current_mood", "neutral"))
        npc["mood_reason"] = f"after speaking with {player_name}"
        sentiment = int(npc.get("player_sentiment", 50)) + int(delta.get("sentiment_delta", 0))
        npc["player_sentiment"] = max(0, min(100, sentiment))
        if delta.get("memory"):
            behavior.remember(npc, f"Day {day}: {delta['memory']}")
        history = npc.setdefault("conversation_history", [])
        history.append(
            {
                "day": day,
                "hour": hour,
                "player_text": player_text,
                "npc_response": delta.get("reply", ""),
            }
        )
        if len(history) > conversation.HISTORY_CAP:
            del history[: len(history) - conversation.HISTORY_CAP]
        save_npc(npc)
        return npc


def _run_conversation(npc_id: str, player_text: str) -> dict[str, Any]:
    """One full conversation turn (runs on a worker thread).

    The LLM call happens against a snapshot of the card, outside _sim_lock --
    it can take seconds, and holding the lock would freeze the world clock.
    Only the delta application locks.
    """
    state = get_world_state()
    if not state:
        raise HTTPException(status_code=409, detail="World not generated yet")
    npc = get_npc(npc_id)
    if npc is None:
        raise HTTPException(status_code=404, detail="Unknown NPC")
    if npc.get("is_player"):
        raise HTTPException(status_code=400, detail="You mutter to yourself.")

    player = get_npc(state.get("player_npc_id") or "")
    player_name = player.get("name", "a stranger") if player else "a stranger"
    day = int(state.get("current_day", 1))
    hour = int(state.get("current_hour", 6))

    if int(npc.get("tier", 3)) == 1:
        delta = conversation.converse_tier1(npc, player_name, player_text)
    else:
        delta = conversation.stub_converse(npc)

    updated = _apply_conversation_delta(npc_id, player_name, player_text, delta, day, hour)
    if updated is None:
        raise HTTPException(status_code=404, detail="Unknown NPC")
    log_event(day, hour, "conversation", f"{player_name} spoke with {updated['name']}.")

    # Display-ready contract: the parsed reply and the post-delta mood only.
    # The raw card-delta JSON never leaves the backend.
    return {
        "npc_response": delta.get("reply", "..."),
        "mood": updated.get("current_mood", "neutral"),
    }


@app.post("/api/conversation")
async def post_conversation(payload: ConversationInput) -> JSONResponse:
    # Offloaded to a thread so the multi-second LLM call never blocks the event
    # loop serving /api/state polls; the frontend awaits with a thinking state.
    result = await asyncio.to_thread(_run_conversation, payload.npc_id, payload.player_text.strip())
    return JSONResponse(result)


@app.get("/api/conversation/{npc_id}")
def get_conversation_context(npc_id: str) -> JSONResponse:
    """Display-ready context for opening a dialogue: who the NPC is, how they
    feel about the player, what they remember, and recent exchanges (US3)."""
    npc = get_npc(npc_id)
    if npc is None:
        raise HTTPException(status_code=404, detail="Unknown NPC")
    history = [
        {"player_text": entry.get("player_text", ""), "npc_response": entry.get("npc_response", "")}
        for entry in npc.get("conversation_history", [])[-conversation.HISTORY_CAP:]
    ]
    return JSONResponse(
        {
            "npc_id": npc.get("id"),
            "npc_name": npc.get("name", "Unknown"),
            "occupation": npc.get("occupation", ""),
            "tier": npc.get("tier", 3),
            "mood": npc.get("current_mood", "neutral"),
            "disposition": conversation.sentiment_phrase(int(npc.get("player_sentiment", 50))),
            "remembered": npc.get("memory_buffer", [])[-5:],
            "history": history,
        }
    )


@app.post("/api/generate-world")
def generate_world() -> JSONResponse:
    summary = world_gen.generate_world()
    return JSONResponse({"status": "generated", **summary})


@app.get("/api/npcs")
def get_npcs() -> list[dict[str, Any]]:
    return get_all_npcs()


@app.get("/api/log")
def get_log() -> list[dict[str, Any]]:
    return get_recent_log()


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")