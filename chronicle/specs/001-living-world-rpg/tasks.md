# Tasks: Living World RPG Simulation

**Input**: Design documents from `specs/001-living-world-rpg/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story the task belongs to, using `US1`, `US2`, `US3`, `US4`, or `US5`
- Include exact file paths in every task description

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure for the solo 8-day build

- [X] T001 Create the backend dependency manifest in `backend/requirements.txt` with FastAPI, Uvicorn, Pydantic, sqlite3, scikit-learn, numpy, and Ollama
- [X] T002 Create the frontend Vite scaffold in `frontend/package.json`, `frontend/vite.config.js`, and `frontend/index.html` with a development proxy to the backend
- [X] T003 [P] Create the frontend entry module and asset folder in `frontend/src/main.jsx` and `frontend/public/assets/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that must be complete before any user story can be implemented

- [X] T004 [P] Define the world data structures in `backend/models/world.py`
- [X] T005 [P] Define the NPC card and relationship data structures in `backend/models/npc.py`
- [X] T006 [P] Define the faction data structures in `backend/models/faction.py`
- [X] T007 [P] Define the rumor data structure in `backend/models/rumor.py`
- [X] T008 Create the package initializer modules in `backend/models/__init__.py`, `backend/systems/__init__.py`, and `backend/ml/__init__.py`
- [X] T009 Implement SQLite schema creation, JSON serialization, and CRUD helpers in `backend/database.py`
- [X] T010 Implement the FastAPI app shell, CORS, static file serving, startup initialization, and stub endpoints in `backend/main.py`
- [X] T011 Implement the frontend API client methods in `frontend/src/api.js`
- [X] T012 Implement the frontend polling shell and shared render-state holder in `frontend/src/App.jsx`

**Checkpoint**: The backend starts cleanly, the frontend shell loads, and the core data shapes exist before simulation logic is added.

---

## Phase 3: User Story 1 - Enter a Living World (Priority: P1)

**Goal**: The player begins as an existing NPC identity inside a pre-generated world and inherits that character's social context.

**Independent Test**: Start the app, inspect the active world state, and confirm that the player is mapped to an existing NPC with relationships already attached.

### Implementation for User Story 1

- [X] T013 [P] [US1] Implement the single-region world generator and host NPC selection flow in `backend/systems/world_gen.py`
- [X] T014 [P] [US1] Train or stub the biome and civilization seed hooks in `backend/ml/train.py`
- [X] T015 [US1] Generate the initial tilemap, buildings, and NPC placement in `backend/systems/world_gen.py`
- [X] T016 [US1] Persist the generated world state, faction records, and host NPC assignment in `backend/database.py`
- [X] T017 [US1] Populate the startup render payload with the player host NPC identity and inherited relationships in `backend/main.py`
- [X] T018 [US1] Seed the names, occupations, and personality source data in `backend/data/names.json`

**Checkpoint**: The world can be generated once, saved, and reopened with the player occupying an existing NPC identity.

---

## Phase 4: User Story 2 - Observe Autonomous World Behavior (Priority: P1)

**Goal**: The world advances on daily ticks and NPCs visibly change behavior without the player driving the simulation.

**Independent Test**: Let the simulation run for several in-game days and confirm that NPC movement, weather, and state changes appear without direct player intervention.

### Implementation for User Story 2

- [X] T019 [P] [US2] Implement the NPC behavior classifier and mood model training hooks in `backend/ml/train.py`
- [X] T020 [P] [US2] Implement the behavior state transitions and movement rules in `backend/systems/behavior.py`
- [X] T021 [P] [US2] Implement weather state changes and day/night timing in `backend/systems/weather.py`
- [X] T022 [US2] Advance daily ticks and apply behavior and weather updates in `backend/main.py`
- [X] T023 [US2] Render the tilemap, moving NPCs, day/night cycle, and HUD state in `frontend/src/GameCanvas.jsx`, `frontend/src/HUD.jsx`, and `frontend/src/App.jsx`
- [X] T024 [US2] Surface behavior and weather summaries in the render payload assembly in `backend/main.py`

**Checkpoint**: The game looks and behaves alive, even before conversation, rumor, or antagonist systems are added.

---

## Phase 5: User Story 3 - Talk and Remember (Priority: P2)

**Goal**: NPC conversations persist memory across repeated interactions and reflect prior player history.

**Independent Test**: Talk to the same Tier 1 NPC twice and confirm the second response references the earlier conversation or memory buffer.

### Implementation for User Story 3

- [X] T025 [P] [US3] Implement the Ollama conversation client and single-call queue in `backend/systems/conversation.py`
- [X] T026 [P] [US3] Implement Tier 1 NPC card generation prompts and card-delta parsing in `backend/systems/conversation.py` and `backend/ml/train.py`
- [X] T027 [US3] Add the conversation endpoint, card-delta application, and memory-buffer updates in `backend/main.py` and `backend/database.py` (database.py needed no new helpers — get_npc/save_npc/log_event already cover the locked read-modify-write)
- [X] T028 [US3] Wire NPC click-to-talk and dialogue rendering in `frontend/src/GameCanvas.jsx` and `frontend/src/DialogueBox.jsx`
- [X] T029 [US3] Surface persistent NPC memory and prior interaction context in `backend/main.py` (GET /api/conversation/{npc_id})

**Checkpoint**: Tier 1 NPCs can converse in character and retain remembered context across multiple interactions.

---

## Phase 6: User Story 4 - See the Rumor Network Spread (Priority: P2)

**Goal**: Rumors move through NPC relationships over time and become visible as social knowledge changes.

**Independent Test**: Seed or trigger a rumor, advance the world, and confirm that additional NPCs learn it through the social graph.

### Implementation for User Story 4

- [X] T030 [P] [US4] Implement rumor propagation logic and decay in `backend/systems/rumors.py`
- [X] T031 [P] [US4] Add rumor persistence helpers and known-by tracking in `backend/database.py` (done on Day 4: rumor structures persist with known-by tracking; propagation itself is T030/T032)
- [X] T032 [US4] Run rumor propagation on daily ticks and update NPC rumor knowledge in `backend/main.py` and `backend/systems/rumors.py`
- [X] T033 [US4] Display rumor-aware dialogue and rumor summaries in `backend/main.py` and `frontend/src/HUD.jsx` (conversation prompts now carry the actual rumor texts the NPC knows)

**Checkpoint**: Rumors can spread through the world and affect what NPCs know and say.

---

## Phase 7: User Story 5 - Watch Major Antagonistic Intent (Priority: P2)

**Goal**: The Demon Lord makes visible daily strategic decisions that affect the world and faction mood.

**Independent Test**: Advance several days and confirm that the Demon Lord produces distinct daily decisions and that faction reputations change as a result.

### Implementation for User Story 5

- [X] T034 [P] [US5] Implement the Demon Lord strategy profile and dawn decision generation in `backend/systems/demon_lord.py`
- [X] T035 [P] [US5] Implement faction reputation scoring and decision effects in `backend/systems/demon_lord.py` and `backend/database.py`
- [X] T036 [US5] Execute Demon Lord decisions on the daily tick in `backend/main.py` and `backend/systems/demon_lord.py` (injected into the existing live world; decision runs on a daemon thread, LLM outside `_sim_lock`)
- [X] T037 [US5] Surface Demon Lord decisions and faction reputation changes in `backend/main.py` and `frontend/src/HUD.jsx`

**Checkpoint**: The antagonist is visible, active, and influencing the simulation every in-game day.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Integration, persistence, and presentation hardening for demo day

- [X] T038 [P] Implement fog-of-war tiers and visibility map output in `backend/main.py` and `frontend/src/GameCanvas.jsx` (Day 7: persisted exploration set on WorldState; three tiers computed backend-side from the host NPC each /api/state build; reveal-all debug toggle on 'R'; NE-corner lair starts unexplored)
- [X] T039 [P] Implement full world save/load serialization in `backend/database.py` and `backend/main.py` (Day 7: split the immutable tile grid into region_static so the hourly save stays lean; verified full round-trip of all Day 5/6/7 fields)
- [X] T040 [P] Add backend startup and shutdown persistence flow in `backend/main.py` and `backend/database.py` (Day 7: startup load via world_is_generated gate already existed; added a clean shutdown flush under _sim_lock so an in-flight tick can't lose the last state)
- [X] T041 [P] Document the demo flow and architecture diagram in `README.md` (Day 7: created `chronicle/README.md` with a Mermaid architecture diagram, the ML registry, the LLM provider model, and a 10-minute demo flow)
- [X] T042 Finalize the quickstart validation notes in `specs/001-living-world-rpg/quickstart.md` (Day 7: real run steps — uv venv, Ollama model, optional Azure .env — plus a validation checklist covering fog/continent/conversation/save-load/ML-on-cue)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - blocks all user stories
- **User Story 1 (Phase 3)**: Can start after Foundational - establishes the world entry slice
- **User Story 2 (Phase 4)**: Can start after Foundational and can overlap with User Story 1 implementation once shared infrastructure is ready
- **User Story 3 (Phase 5)**: Depends on the backend state model and frontend shell from Phases 1-4
- **User Story 4 (Phase 6)**: Depends on relationship-aware NPC state from earlier phases
- **User Story 5 (Phase 7)**: Depends on world, faction, and daily tick infrastructure from earlier phases
- **Polish (Phase 8)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can be delivered first as the MVP slice
- **User Story 2 (P1)**: Builds on the same world foundation and rendering shell
- **User Story 3 (P2)**: Needs host NPC state and the frontend interaction loop
- **User Story 4 (P2)**: Needs persistent NPC relationships and daily tick behavior
- **User Story 5 (P2)**: Needs faction state, daily ticks, and world persistence

### Within Each User Story

- Shared backend primitives before story-specific logic
- Story-specific backend logic before frontend wiring where applicable
- Core implementation before final presentation polish
- Story complete before moving to the next priority when possible

### Parallel Opportunities

- Setup tasks T001-T003 can proceed with minimal coupling
- Foundational model tasks T004-T008 can run in parallel
- Backend service tasks for different stories can run in parallel once the shared data layer exists
- Frontend render tasks can progress alongside backend story logic after the app shell is in place

---

## Parallel Example: User Story 1

```text
Task: "Implement the single-region world generator and host NPC selection flow in backend/systems/world_gen.py"
Task: "Train or stub the biome and civilization seed hooks in backend/ml/train.py"
```

## Parallel Example: User Story 2

```text
Task: "Implement the NPC behavior classifier and mood model training hooks in backend/ml/train.py"
Task: "Implement the weather state changes and day/night timing in backend/systems/weather.py"
```

## Parallel Example: User Story 3

```text
Task: "Implement the Ollama conversation client and single-call queue in backend/systems/conversation.py"
Task: "Implement Tier 1 NPC card generation prompts and card-delta parsing in backend/systems/conversation.py and backend/ml/train.py"
```

---

## Implementation Strategy

### MVP First

1. Complete Setup and Foundational phases.
2. Complete User Story 1 so the player can enter an already-existing world.
3. Validate the MVP slice before expanding to behavior, conversation, rumor, and antagonist systems.

### Incremental Delivery

1. Build the world entry and persistence slice first.
2. Add visible autonomous behavior and rendering next.
3. Layer in LLM conversation and memory.
4. Add rumor propagation.
5. Add Demon Lord decisions and faction pressure.
6. Finish with fog-of-war, save/load, and demo polish.

### Solo Build Strategy

1. Keep each task narrowly scoped to the listed files.
2. Favor backend changes first, then wire the frontend to the completed payload.
3. Avoid cross-story refactors unless they unblock the current phase.
4. Use Phase 8 only for stabilization and presentation readiness.
