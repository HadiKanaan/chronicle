from __future__ import annotations

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
)
from models.world import RenderPayload, WorldState


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

app = FastAPI(title="Chronicle of the Velvet Lies API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
                "x": visible["x"],
                "y": visible["y"],
                "sprite_id": visible["sprite_id"],
            }
            continue
        npc_payload.append(visible)

    tiles = [tile.model_dump() for row in region.tiles for tile in row]
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


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/state", response_model=RenderPayload)
def get_state() -> RenderPayload:
    return _build_render_payload()


@app.post("/api/input")
def post_input(player_input: PlayerInput) -> JSONResponse:
    log_event(1, 6, player_input.type, f"Input received: {player_input.type}")
    return JSONResponse({"status": "ok", "accepted": True})


@app.post("/api/generate-world")
def generate_world() -> JSONResponse:
    log_event(1, 6, "generate_world", "World generation requested")
    return JSONResponse({"status": "not implemented"})


@app.get("/api/npcs")
def get_npcs() -> list[dict[str, Any]]:
    return get_all_npcs()


@app.get("/api/log")
def get_log() -> list[dict[str, Any]]:
    return get_recent_log()


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")