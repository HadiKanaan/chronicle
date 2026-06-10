# API Contract: Living World RPG Simulation

## GET /api/state

Returns the current render payload for the browser.

### Response Shape

- tiles: list of visible tiles with x, y, tile_type
- npcs: list of visible NPC summaries with id, x, y, sprite_id, name, tier
- player: player summary or null with x, y, sprite_id
- time_of_day: dawn, morning, afternoon, dusk, or night
- weather: clear, rain, fog, or storm
- dialogue: current dialogue or null
- notifications: list of recent player-facing events
- faction_reputations: mapping of faction name to score
- current_day: current in-game day
- current_hour: current in-game hour
- fog_map: list of x, y, fog_tier entries

## POST /api/input

Accepts a player action and records it for backend processing.

### Request Shape

- type: action type such as movement or interaction
- payload: action-specific data

### Response Shape

- status: ok
- accepted: boolean

## POST /api/generate-world

Triggers initial world generation.

### Response Shape

- status: not implemented during the early scaffold phase

## GET /api/npcs

Returns the list of stored NPC records.

### Response Shape

- list of NPC JSON objects

## GET /api/log

Returns recent game log entries.

### Response Shape

- list of day, hour, event_type, description, timestamp records