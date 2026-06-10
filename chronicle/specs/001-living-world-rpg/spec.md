# Feature Specification: Living World RPG Simulation

**Feature Branch**: `001-living-world-rpg`

**Created**: 2026-06-10

**Status**: Draft

**Input**: User description: "A living world RPG simulation where an AI-driven world runs independently of the player. NPCs have personalities and memories stored in character cards. A Demon Lord antagonist makes daily strategic decisions via LLM. Information spreads through a rumor propagation system. NPCs behave according to ML behavior models on daily ticks. The player spawns into an existing NPC's body and inherits their relationships. The demo needs to show: LLM-driven NPC conversation with persistent memory, visible ML behavior changes, rumor spreading through social network, and Demon Lord making observable decisions."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Enter a living world (Priority: P1)

A player can begin in an existing world state by inhabiting an NPC body and immediately see that they have inherited the social context of that character.

**Why this priority**: The demo needs a clear starting point that establishes the core fantasy of becoming part of an already-active world.

**Independent Test**: A tester can start the demo, observe the player occupying a pre-existing NPC identity, and confirm that nearby characters and relationships are already in place without any manual world setup.

**Acceptance Scenarios**:

1. **Given** an initialized world, **When** the player enters the game, **Then** the player appears as an existing NPC rather than a blank avatar.
2. **Given** the player has taken over an NPC body, **When** the world is shown, **Then** the player inherits that NPC's visible relationships and social context.

---

### User Story 2 - Observe autonomous world behavior (Priority: P1)

NPCs and factions continue to act even when the player does nothing, so the world feels alive and independent.

**Why this priority**: The central promise of the simulation is that the world continues moving without player input.

**Independent Test**: A tester can wait through multiple daily ticks and observe NPC behavior changes, rumor spread, and major decisions without interacting with the world.

**Acceptance Scenarios**:

1. **Given** the simulation is running, **When** time advances by a day, **Then** NPCs may change behavior based on their modeled tendencies.
2. **Given** social connections exist in the world, **When** time advances, **Then** rumors can spread from one character to another.
3. **Given** the Demon Lord is active, **When** a new day begins, **Then** the Demon Lord makes an observable strategic decision.

---

### User Story 3 - Talk and remember (Priority: P2)

Players can converse with NPCs and see that conversations reflect persistent memory rather than resetting each time.

**Why this priority**: The demo must prove that characters feel continuous across interactions, not stateless.

**Independent Test**: A tester can speak with the same NPC more than once and verify that later dialogue reflects prior interaction history.

**Acceptance Scenarios**:

1. **Given** the player has spoken to an NPC before, **When** they speak again later, **Then** the NPC can reference the prior interaction.
2. **Given** an NPC has a stored memory of important events, **When** they converse with the player, **Then** the dialogue reflects that memory.

---

### User Story 4 - See the rumor network spread (Priority: P2)

Rumors move through the world through social relationships and can be observed as they become known by different characters.

**Why this priority**: Rumors are a key source of emergent world drama and support the simulation's social structure.

**Independent Test**: A tester can trigger or observe a rumor and confirm that it reaches new NPCs over time through connected relationships.

**Acceptance Scenarios**:

1. **Given** a rumor begins with one character, **When** daily ticks occur, **Then** other linked characters may learn it.
2. **Given** a rumor has spread, **When** the world is inspected later, **Then** the rumor's visibility has expanded beyond its original source.

---

### User Story 5 - Watch major antagonistic intent (Priority: P2)

The Demon Lord must visibly influence the world through daily strategic decisions so the player can perceive an active antagonist.

**Why this priority**: The demo needs a clear opposing force whose decisions create pressure and direction in the world.

**Independent Test**: A tester can inspect the world across multiple days and see distinct decisions attributed to the Demon Lord.

**Acceptance Scenarios**:

1. **Given** the Demon Lord is active, **When** a daily update occurs, **Then** a new strategic decision is recorded or surfaced.
2. **Given** several days pass, **When** the player reviews world changes, **Then** the Demon Lord's decisions can be seen affecting the simulation.

### Edge Cases

- What happens when a player body has no useful social context to inherit?
- How does the game present contradictory memories or rumors about the same event?
- What happens if no new rumors or decisions occur on a given day?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST allow the player to begin as an existing NPC identity within the world.
- **FR-002**: The system MUST preserve and surface inherited relationships tied to the player's host character.
- **FR-003**: The system MUST support NPCs with persistent character cards that retain personality and memory across time.
- **FR-004**: The system MUST allow repeated conversations with NPCs to reflect prior interaction history.
- **FR-005**: The system MUST advance the world in daily ticks even when the player does not act.
- **FR-006**: The system MUST produce visible changes in NPC behavior over time.
- **FR-007**: The system MUST allow rumors to spread across character relationships over time.
- **FR-008**: The system MUST make the Demon Lord's daily strategic decisions visible to the player.
- **FR-009**: The system MUST present world changes in a way that lets a tester distinguish autonomous simulation from player-triggered events.
- **FR-010**: The demo MUST show a coherent living world without requiring manual reset between core interactions.

### Key Entities *(include if feature involves data)*

- **Player Host NPC**: The NPC body the player inhabits, including identity, relationships, and context.
- **Character Card**: The persistent profile for an NPC, including personality, memory, and social information.
- **Rumor**: A piece of information that can spread across the social network and evolve over time.
- **Demon Lord Decision**: A daily strategic choice that represents antagonistic intent and world pressure.
- **World Tick**: A daily simulation step that advances behavior, memory, rumor spread, and major decisions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A tester can start the demo and identify the player as an existing NPC within 30 seconds.
- **SC-002**: After at least three daily ticks, the world shows at least one visible NPC behavior change.
- **SC-003**: At least one rumor can be observed reaching more than one character during a demo session.
- **SC-004**: A repeated conversation with the same NPC can demonstrate remembered context from a prior interaction.
- **SC-005**: The Demon Lord produces one observable strategic decision per in-game day during the demo.
- **SC-006**: The demo presents enough persistent world activity that a tester can describe at least three independent simulation changes without interacting every step.

## Assumptions

- The demo focuses on a small, readable slice of the world rather than a fully populated simulation.
- The player's host NPC is chosen before the demo begins.
- Conversations, rumors, and decisions are presented in a way that a human tester can observe directly.
- The first demo version prioritizes clarity of world dynamics over breadth of content.
