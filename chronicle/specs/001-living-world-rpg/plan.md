# Implementation Plan: Living World RPG Simulation

**Branch**: `001-living-world-rpg` | **Date**: 2026-06-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from [spec.md](spec.md)

## Summary

Build a browser-based RPG simulation where the backend is the single source of
truth, the frontend is a dumb renderer, and the world advances independently of
the player. The demo will emphasize one region, about 80 NPCs across three
tiers, daily world ticks, persistent NPC memory, rumor propagation, visible ML
behavior changes, and an observable Demon Lord antagonist.

## Technical Context

**Language/Version**: Python 3.11 for backend, modern JavaScript for frontend

**Primary Dependencies**: FastAPI, Uvicorn, Pydantic, sqlite3, scikit-learn,
Ollama, React, Vite, HTML5 canvas

**Storage**: SQLite with JSON blobs for all durable world state

**Testing**: Pytest for backend checks, browser-driven manual verification for
the render loop and polling contract

**Target Platform**: Local desktop development on Windows with a browser client

**Project Type**: Web application with backend API and frontend renderer

**Performance Goals**: Stable 500ms polling, responsive local API calls, and
smooth rendering for a single region with roughly 80 NPCs

**Constraints**: Backend owns all game logic, frontend stores no gameplay state,
SQLite is the only persistence layer, and the scope stays within the 8-day solo
capstone window

**Scale/Scope**: One region only, three NPC tiers, around 80 total NPCs, and a
single playable demo loop rather than a general-purpose simulation platform

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Backend is the source of truth for all state and decisions.
- Frontend is a dumb renderer that polls the backend and posts player input.
- SQLite stores all durable state as JSON blobs.
- Scope is limited to the defined demo and avoids feature creep.
- Complexity is concentrated in backend AI systems, not UI layers.
- The plan keeps each system contained to one file where practical.

## Project Structure

### Documentation (this feature)

```text
specs/001-living-world-rpg/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
└── contracts/
    └── api.md
```

### Source Code (repository root)

```text
backend/
├── main.py
├── database.py
├── models/
│   ├── __init__.py
│   ├── world.py
│   ├── npc.py
│   ├── faction.py
│   └── rumor.py
├── systems/
│   ├── __init__.py
│   ├── world_gen.py
│   ├── behavior.py
│   ├── weather.py
│   ├── conversation.py
│   ├── demon_lord.py
│   └── rumors.py
├── ml/
│   ├── __init__.py
│   └── train.py
└── data/
    └── names.json

frontend/
├── package.json
├── index.html
├── src/
│   ├── main.jsx
│   ├── App.jsx
│   ├── GameCanvas.jsx
│   ├── DialogueBox.jsx
│   ├── HUD.jsx
│   └── api.js
├── public/
│   └── assets/
└── vite.config.js
```

**Structure Decision**: Use a two-part web application: `backend/` for all game
logic and persistence, and `frontend/` for rendering the backend payload and
relaying player input. Each simulation domain is separated into its own backend
module so the codebase stays navigable during the solo 8-day build.

## Complexity Tracking

No constitution violations require justification for this plan.

## 8-Day Build Roadmap

### Day 1: Skeleton and Data Structures

**Goal**: FastAPI + SQLite running locally, Vite + React running with proxy configured,
all data structures defined in Python before writing any logic.

**Deliverables**:
- Backend running on port 8000, serving static files from `frontend/dist`
- Frontend running on port 5173 with API proxy to backend
- All Pydantic models implemented: WorldState, Region, Tile, Building, CharacterCard,
  NPCSkills, NPCRelationship, FactionAffiliation, Faction, FactionRelationship, Rumor
- SQLite database schema created with tables: world_state, npcs, factions,
  faction_relationships, rumors, game_log
- API stubs working: GET /api/state, POST /api/input, POST /api/generate-world,
  GET /api/npcs, GET /api/log
- Frontend polls backend every 500ms and receives RenderPayload stub

**No scope**: No ML, no LLM, no rendering, no simulation logic. Skeleton only.

**Acceptance**: `GET /docs` shows all endpoints working, database initializes cleanly
on startup, frontend polls backend without errors.

---

### Day 2: World Generation

**Goal**: Single region generates on startup with tilemap, buildings, NPCs seeded into
positions. Biome and civilization seed models trained and running. World persists to SQLite.

**Deliverables**:
- Tilemap generator: grass/path/water tiles placed procedurally, with buildings
  (tavern, blacksmith, market, church, houses) positioned in reasonable clusters
- ~80 NPCs seeded across three tiers: 10 Tier 1 (named, full detail), 30 Tier 2
  (peripheral, shallow detail), 40 Tier 3 (background, minimal)
- Biome assignment model trained and applied to region
- Civilization seed model trained and applied to initial NPC distribution
- World persists to SQLite on generation
- Player host NPC selected from Tier 1 at startup

**No scope**: No rendering, no behavior, no conversations, no rumors spreading.

**Acceptance**: `/api/state` returns a fully populated region with NPCs at positions,
database contains the full world state after startup, biome and seed models trained
without errors.

---

### Day 3: Frontend Rendering

**Goal**: Canvas renderer reads backend payload, displays tilemap, NPCs as sprites,
player on screen, day/night cycle. Nothing AI yet.

**Deliverables**:
- Canvas-based tilemap renderer (32px tiles)
- NPC sprites from the Pixel Crawler pack rendered at NPC positions (backend emits
  sprite_id; frontend maps it via a static sprite atlas)
- Player sprite centered on screen
- Arrow key movement sends input to backend
- Day/night visual cycle (lighting/color shift)
- Basic HUD showing day, time, weather, faction reputations
- Dialogue box UI shell (displays text, not yet interactive)

**No scope**: No AI, no behavior, no Ollama calls, no conversations.

**Acceptance**: Browser shows a game-like appearance with world visible, player moves
with arrow keys, visual day/night cycle is observable, game feels like a game (not just
a grid of data).

---

### Day 4: ML Behavior Layer

**Goal**: NPC behavior classifier, mood update model, weather classifier running on
daily tick. NPCs visibly moving between states. Rumor structure in place (no propagation yet).

**Deliverables**:
- NPC behavior classifier: WORKING, SOCIALIZING, STAYING_HOME, TRAVELING, SLEEPING,
  FLEEING, SEEKING_INFO
- Mood update model trained and applied per NPC per daily tick
- Weather classifier generating new weather states (clear, rain, fog, storm)
- NPCs move between home/work/tavern based on behavior state and time of day
- Memory buffer rolling on significant events
- Rumor data structure persisted but no propagation yet
- Daily tick orchestration working: time advances, behavior updates, NPCs move

**No scope**: No LLM, no NPC conversation, no rumor propagation, no Demon Lord.

**Acceptance**: Running the backend for several in-game days shows NPCs visibly changing
behavior (going to work, tavern, home). Weather changes over time. Memory buffer fills
with events. World feels alive (first sign of emergent behavior).

---

### Day 5: LLM Integration

**Goal**: Ollama connected and working. Tier 1 NPC cards generated at world start via LLM.
Conversation endpoint working: player clicks NPC, dialogue box appears, LLM responds
in character, card delta applied after.

**Deliverables**:
- Ollama instance running locally with qwen3:4b (thinking disabled per call;
  see research.md decision 4 — Gemma 3 1B was dropped after testing)
- Tier 1 NPC card generation prompt designed and tested (personality, dark trait,
  redeeming quality, conversation style)
- POST /api/conversation endpoint: accepts npc_id + player_text, returns npc_response
  and card_delta (mood shift, memory add, sentiment update)
- Frontend dialogue box: click NPC → show dialogue → player types → submit → backend
  calls LLM → response displayed → card updated
- Single call queue in backend to prevent concurrent Ollama requests
- Async/await pattern for LLM calls so frontend doesn't block

**No scope**: No rumor propagation, no Demon Lord, no Tier 2/3 LLM cards. Tier 2/3 use
stubs or simpler rule-based responses.

**Acceptance**: Clicking a Tier 1 NPC opens a conversation, LLM responds in character,
mood/memory visibly change after interaction, multiple conversations with same NPC
reflect prior interactions. This is the hardest day and the technical linchpin.

---

### Day 6: Demon Lord + Rumor Propagation

**Goal**: Demon Lord spawned with strategy profile. Daily LLM strategy call at dawn,
actions executing through behavior system. Rumor propagation running on daily tick.

**Deliverables**:
- Demon Lord NPC spawned at world start with is_demon_lord flag
- Daily strategy generation prompt: Demon Lord makes one strategic decision per dawn
  (e.g., "send cultists to raid the market", "spread fear through rumors", "demand
  tribute from a faction")
- Strategy decisions execute as NPC behaviors and affect faction sentiment
- Rumor propagation: each daily tick, rumors spread across character relationships
  based on gossip probability and drama score
- Faction reputation visibly affected by Demon Lord actions and other events
- Player can observe rumors spreading through dialogue and NPC knowledge

**No scope**: No complex faction warfare, no Demon Lord combat system, no consequences
beyond NPC sentiment and reputation.

**Acceptance**: Demon Lord makes one observable decision per day, rumors visible spread
to multiple NPCs over time, faction reputations change in response to world events.
Demon Lord feels like an active antagonist.

---

### Day 7: Fog of War + Save System

**Goal**: All three fog of war tiers rendering correctly. Complete world state
serialization. Save on exit, load on start. Player spawn sequence with inherited NPC card.
First full integration test.

**Deliverables**:
- Fog of war three tiers implemented and rendering (explored, explored-stale, unexplored)
- Full world state serialization to SQLite: all NPC cards, factions, rumors, buildings,
  fog map, current time, Demon Lord status
- Save on backend shutdown, load on startup
- Player spawn sequence: load host NPC card, inherit relationships and sentiment,
  display inherited context on HUD
- All systems running together: rendering + polling + behavior + conversation +
  rumor propagation + Demon Lord + save/load
- No new bugs introduced; integration test passes

**No scope**: No new features, only integration and persistence.

**Acceptance**: Close the browser, restart backend, reload frontend → world persists
identically. Player spawns with inherited NPC identity and all accumulated state.
Full simulation loop runs without crashes for at least 10 simulated days.

---

### Day 8: Buffer and Presentation Prep

**Goal**: Not for building features. Fix integration issues, polish demo flow, prepare
to present confidently. Optional: add one impressive-but-safe feature if time permits.

**Deliverables**:
- All critical bugs fixed from Day 7 integration
- Demo sequence scripted: start → show world → walk around → talk to NPC → observe
  behavior changes → observe rumors spreading → watch Demon Lord decision → demonstrate
  save/load
- Architecture diagram drawn and explained
- Console output clean (no noisy debug logs during demo)
- Performance acceptable (no freezing, ~500ms polling response time)
- Optional polish: improved sprite rendering, better visual feedback, one small
  "wow factor" moment (e.g., a dramatic Demon Lord decision text display)

**No scope**: No new game mechanics, no additional NPCs, no new data structures.

**Acceptance**: Demo runs smoothly from start to finish, all five core features visible
and working, presentation is coherent and well-rehearsed.
