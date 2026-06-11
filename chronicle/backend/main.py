from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database import (
    get_all_factions,
    get_all_npcs,
    get_recent_log,
    get_world_state,
    init_db,
    log_event,
    save_world_state,
    world_is_generated,
)
from models.world import RenderPayload, WorldState
from systems import world_gen


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

# Local frontend dev origins (Vite). Explicit origins instead of "*" so the CORS
# config stays valid even if credentialed requests are ever introduced.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Autonomous world clock. Disabled until Day 4 wires the simulation systems; the
# scaffold lives here now so the architecture (backend-driven time, dumb frontend)
# is fixed and the frontend never needs to know ticks exist.
TICK_ENABLED = False
REAL_SECONDS_PER_GAME_HOUR = 5.0


def _advance_one_hour() -> None:
    """Advance the authoritative clock by one in-game hour.

    Day 4 will apply behavior, weather, rumor, and Demon Lord updates here. For
    now it only moves time forward so the loop is exercisable end to end.
    """
    state = get_world_state()
    if not state:
        return
    hour = int(state.get("current_hour", 6)) + 1
    if hour >= 24:
        hour = 0
        state["current_day"] = int(state.get("current_day", 1)) + 1
    state["current_hour"] = hour
    save_world_state(state)


async def _world_tick_loop() -> None:
    """Advance game time on a real-time interval, independent of the player.

    Runs in the background so the world progresses whether or not the frontend is
    polling. DB work is offloaded to a thread so it never blocks the event loop
    that serves /api/state, and each tick is isolated so one failure can't stop
    the clock.
    """
    while True:
        await asyncio.sleep(REAL_SECONDS_PER_GAME_HOUR)
        try:
            await asyncio.to_thread(_advance_one_hour)
        except Exception as exc:  # noqa: BLE001 - never let one tick kill the clock
            log_event(0, 0, "tick_error", f"World tick failed: {exc}")


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


def _hour_to_time_of_day(hour: int) -> str:
    if 5 <= hour <= 7:
        return "dawn"
    if 8 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 16:
        return "afternoon"
    if 17 <= hour <= 19:
        return "dusk"
    return "night"


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
        time_of_day=_hour_to_time_of_day(world_state.current_hour),
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
    log_event(1, 6, player_input.type, f"Input received: {player_input.type}")
    return JSONResponse({"status": "ok", "accepted": True})


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