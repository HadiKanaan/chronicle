<!--
Sync Impact Report
- Version change: template -> 1.0.0
- Modified principles: template placeholders -> five project principles tailored to the solo capstone build
- Added sections: Implementation Constraints, Working Rules
- Removed sections: none
- Templates requiring updates: ✅ none required; the existing plan/spec/tasks templates remain compatible
- Follow-up TODOs: none
-->

# Chronicle of the Velvet Lies Constitution

## Core Principles

### I. Backend Is the Source of Truth
The backend owns every authoritative game decision, state transition, and
persisted value. NPC state, world state, faction state, rumors, logs, and
time progression live in the backend and are written to SQLite. The frontend
may request state and send inputs, but it never decides game outcomes.

### II. The Frontend Is a Dumb Renderer
The frontend renders only the payload returned by the backend. It holds no
authoritative gameplay state, no simulation logic, no AI logic, and no hidden
rules. Client state is limited to temporary UI concerns such as the last render
payload, the active dialogue panel, and a short notification history.

### III. SQLite Stores All Durable State
SQLite is the only durable persistence layer for the capstone build. All game
data is stored as JSON blobs behind simple tables so the project stays fast to
build and easy to inspect. Every database function opens and closes its own
connection, and no shared ORM session or long-lived connection is allowed.

### IV. Scope Is Locked to the Agreed Build
Only the explicitly defined capstone scope is in play. No feature creep, no
bonus systems, no premature optimization, and no architectural detours that do
not move the build toward a working demo. If a change is not needed for the
defined roadmap, it stays out.

### V. Complexity Belongs in AI Systems, Not UI
Complexity budget is reserved for backend systems that generate behavior,
state, and future AI-driven features. The UI stays simple, readable, and
mostly static. Each system should live in one file where practical, and any
extra file split must be justified by a real technical constraint rather than
taste or abstraction preference.

## Implementation Constraints

These constraints are non-negotiable for the solo 8-day build:

- The backend is the only place where game logic may exist.
- The render payload is the only contract between backend and frontend.
- The frontend may fetch, display, and emit inputs, but it may not simulate.
- Day 1 work is foundation only: data shapes, database initialization, API
	stubs, and the minimal renderer shell.
- Prefer raw, explicit code over abstractions that do not earn their keep.

## Working Rules

- Use Pydantic models for game data shapes and keep them explicit.
- Keep public contracts small and stable so Day 1 scaffolding can survive later
	feature work.
- Validate each layer in isolation: database, API, and frontend rendering.
- When uncertain, choose the simplest implementation that preserves the
	backend-authoritative design.
- If a proposed change would move state or logic into the frontend, reject it.

## Governance

This constitution supersedes ad hoc preferences and lower-level guidance when
they conflict. Any amendment must preserve the backend-authoritative model,
the dumb-renderer frontend, SQLite-only durability, and the no-creep scope
boundary.

Versioning follows semantic rules:

- MAJOR: a principle is removed or redefined in a backward-incompatible way.
- MINOR: a principle or section is added or materially expanded.
- PATCH: wording changes, clarifications, or other non-behavioral edits.

Every amendment must update the version, ratification date, and last amended
date. Any future update should also check the spec-kit templates for alignment
with these rules before implementation begins.

**Version**: 1.0.0 | **Ratified**: 2026-06-10 | **Last Amended**: 2026-06-10
