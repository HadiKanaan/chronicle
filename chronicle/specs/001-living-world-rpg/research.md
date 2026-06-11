# Research: Living World RPG Simulation

## Decision 1: Backend-authoritative simulation

- Decision: Keep all game logic, state transitions, and persistence on the backend.
- Rationale: This preserves a single source of truth and makes the browser a
  pure renderer that can be refreshed or rebuilt without affecting the world.
- Alternatives considered: Splitting simulation logic between client and server
  was rejected because it introduces state divergence and extra debugging cost.

## Decision 2: SQLite JSON persistence

- Decision: Store durable world state as JSON blobs in SQLite.
- Rationale: It is fast to build, easy to inspect, and fits the capstone scope
  better than introducing a normalized schema or heavier database stack.
- Alternatives considered: SQLAlchemy models and relational normalization were
  rejected because they add overhead without helping the demo goals.

## Decision 3: Polling render contract

- Decision: The frontend polls the backend every 500ms for a render payload and
  posts player inputs back to the API.
- Rationale: This keeps the frontend state-light and makes the backend the only
  authority on what the player sees.
- Alternatives considered: WebSocket-driven client state was rejected because it
  increases complexity without being necessary for the demo.

## Decision 4: Local Ollama for strategic and conversational AI

- Decision: Use locally running Ollama with qwen3:4b for NPC conversation and
  Demon Lord decision generation. Every call must disable thinking
  (`think: false`) — qwen3 is a reasoning model and otherwise burns minutes on
  `<think>` blocks — and send `keep_alive` so the model stays resident between
  calls (~8s warm vs ~18s cold on the target CPU-only laptop).
- Rationale: It keeps the demo self-contained and avoids cloud dependency risk
  during the solo build. 4B balances laptop speed with reliable JSON
  instruction-following for card deltas.
- Alternatives considered: Hosted LLM APIs were rejected because they add setup
  friction and dependency risk. Gemma 3 1B (the original pick) was rejected
  after testing as too weak for reliable JSON card-deltas; qwen2.5-coder:7b was
  rejected as coder-tuned, weaker at roleplay, and slow on the target laptop.

## Decision 5: scikit-learn for visible behavior models

- Decision: Use scikit-learn-based models for NPC behavior changes surfaced on
  daily ticks.
- Rationale: The project needs visible, explainable behavior shifts without
  building a custom ML stack from scratch.
- Alternatives considered: Hard-coded behavior rules were rejected because the
  demo explicitly needs ML-driven changes.

## Decision 6: One region, roughly 80 NPCs

- Decision: Scope the world to one region with about 80 NPCs across three tiers.
- Rationale: This is large enough to show emergent behavior while staying within
  the 8-day solo build window.
- Alternatives considered: Multi-region or larger-NPC simulations were rejected
  as too risky for the demo timeline.