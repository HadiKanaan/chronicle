# Day 7 Remainder — three `/speckit.implement` commands + design decisions

Authored 2026-06-15. Captures everything planned for Day 7 but not yet built,
plus the design decisions reached in conversation. Run the **three command
blocks below, in order, as separate `/speckit.implement` invocations** — they
were split out of one combined command specifically so each ships and is
reviewed on its own.

Day 7 already shipped (commit `e8c0e68`): fog of war (T038), the static/mutable
save-load split + shutdown flush (T039/T040), and the visual-only continent
overlay + Country Property Generator. This document covers the **remainder**.

**Run order:** Command 1 (LLM hardening) is independent — run anytime. Command 2
(faction decoupling) must run **before** Command 3 (the ML batch), which depends
on the faction fields Command 2 adds. Recommended: run 1 and 2, look at the
results, then decide on 3.

---

## Design decisions (new — reached 2026-06-14/15, not previously recorded)

### 1. Faction reputation was conflated and one-directional (bug → redesign)

`Faction.player_reputation` (0–100, starts 50) is the only mutable faction
signal, and its only writer is the Demon Lord (`demon_lord.apply_decision` →
`database.adjust_faction_reputation`, always negative). With no recovery and no
player input it ratchets monotonically to 0 over a long game (observed live
~day 196). It is also **semantically wrong**: the Demon Lord ravaging the town
should not lower the town's regard *for the player*. The genuine
"how-they-feel-about-me" signal is per-NPC `player_sentiment` (moved by
conversation deltas), which is completely disconnected from `player_reputation`.

**Decision (Tier A):** split the one conflated number into distinct per-faction
state, each with a **restoring force** toward a baseline so nothing ratchets:
- `player_reputation` → purely player-driven (ML batch Model 3 aggregates member
  `player_sentiment` × loyalty; a neutral player pulls it back toward ~50).
- new `morale` field → faction cohesion/wellbeing; **this** is where the Demon
  Lord's pressure now lands (not player_reputation).
- new `history` buffer → rolling `{day, text}` per faction (mirrors the NPC
  `memory_buffer` pattern) so each faction becomes a narrative entity.
- inter-faction `relationship_score` (frozen since Day 2) → unfrozen by Model 4.

This is the "factions as cleanly-separated stateful agents, each with a history"
direction. **Deferred (Tier B):** factions *reacting* from their own state
(morale gating how hard the DL lands, history biasing reactions, common-enemy
coalitions, a dedicated faction HUD panel).

Open knob: the command currently has the Demon Lord stop touching
`player_reputation` entirely. Alternative considered: keep a *small* DL nudge on
reputation (town blames the player a little). Chose full decoupling as the more
honest data model.

### 2. LLM structured-output failure (qwen3:4b dropping/misplacing fields)

`format="json"` guarantees syntax, not schema/semantics, so qwen3:4b sometimes
omits `reply` or puts the spoken line in `memory`. Current code already does
defense-in-depth recovery (salvage/retry/`_safe_line`/ML mood arbitration) —
keep all of it.

**Decision:** add **schema-constrained decoding** — pass a JSON Schema to
Ollama's `format=` (required fields present + typed at sampling time; does not
break the prefix cache). Cheap, high-value. **Deferred:** the fuller *decompose*
refactor (LLM returns plain-text prose only; derive mood/sentiment/memory from
local ML so there are no sibling fields to misplace) — bigger, its own command;
also avoids a second LLM call that would thrash the single Ollama KV slot.

See also: [[ml-registry-plan]] (the 4-model batch origin),
[[faction-model-redesign]], [[llm-structured-output-hardening]],
[[chronicle-build-state]].

---

## Shared constraints (apply to all three commands)

> NEVER regenerate the live world (~200 days of NPC memories,
> conversation_history, rumor_knowledge, demon_lord_decisions, faction state
> must survive — augment in place). PRESERVE the ml/train.py pattern: a
> ground-truth rule fn → synthetic samples labelled by the rule (GDD 7.3 "sample
> the rule with noise, train on it") → a scikit-learn model → a predict()
> wrapper that falls back to the rule when _ML_AVAILABLE is False or the model is
> None. _sim_lock discipline for every read-modify-write the tick also touches.
> Backend single source of truth; frontend dumb renderer; SQLite JSON blobs; one
> system per file. Full pytest suite green before the commit. Commit on main.

---

## Command 1 of 3 — LLM structured-output hardening (independent)

```
day 7 — LLM structured-output hardening. Standalone, no dependencies, safe to
run first. SHARED CONSTRAINTS: never regenerate the live world; preserve the
ml/train.py rule->synthetic->model->predict-with-fallback pattern; _sim_lock for
every tick read-modify-write; backend authoritative, frontend dumb; one system
per file; full pytest suite green before commit; commit on main.

qwen3:4b emits syntactically-valid JSON but drops/misplaces fields (the "reply"
field goes missing or the spoken line lands in "memory") because format="json"
guarantees syntax, not schema. Upgrade systems/conversation.py:

- Change _call_llm to accept an optional `schema` (JSON Schema dict). When given,
  pass it to Ollama's `format=` instead of the string "json" (Ollama supports
  schema-constrained decoding — required fields present + typed at sampling time;
  it does NOT break the prefix cache since grammar applies at sampling, not
  prompt-eval). Keep format="json" / None as the fallback paths.
- converse_tier1 passes a card-delta schema: reply (string, minLength 1), mood
  (enum = sorted(VALID_MOODS)), sentiment_delta (integer -10..10), memory
  (string); required = all four. This makes the dropped-"reply" and invalid-mood
  cases nearly impossible while the existing salvage/retry/_safe_line net stays
  as the last resort (KEEP all of it — defense in depth; small models still
  occasionally misbehave). generate_card_details passes its own schema too.
- Measure: log a line confirming schema is in use; if grammar-constrained
  decoding measurably slows calls on this CPU, note it in the commit message.
- This guarantees field PRESENCE, not semantic placement. DO NOT do the fuller
  "decompose" refactor (LLM prose-only + ML-derived deltas) here — that is a
  separate future command.

Tests: assert _call_llm forwards a schema when supplied; parse_card_delta still
handles the (now rarer) malformed cases. Commit: "Day 7: LLM structured-output
hardening (schema-constrained card deltas)". After commit, update the
llm-structured-output-hardening memory to mark it implemented.
```

---

## Command 2 of 3 — Faction model decoupling (run BEFORE Command 3)

```
day 7 — faction model decoupling. Standalone code-wise, but RUN THIS BEFORE the
ML-batch command (Command 3 depends on the fields added here). SHARED
CONSTRAINTS: never regenerate the live world (faction state and ~200 days of NPC
memory must survive — augment in place); _sim_lock for every tick read-modify-
write; backend authoritative, frontend dumb; one system per file; full pytest
suite green before commit; commit on main.

Today Faction.player_reputation is the ONLY mutable faction signal and the ONLY
writer is the Demon Lord (demon_lord.apply_decision, the faction_reputation_
effects loop -> database.adjust_faction_reputation, always negative). With no
recovery and no player input it ratchets monotonically to 0 over a long game --
and it's semantically wrong: the Demon Lord ravaging the town should not lower
the town's regard FOR THE PLAYER. Split the one conflated number into distinct
per-faction state with restoring forces, and give each faction a history.

models/faction.py — add fields:
- morale: int = 60          # faction cohesion/wellbeing; the Demon Lord hits THIS
- history: list[dict] = []  # rolling {day, text}, capped (~8), like NPC memory_buffer
(player_reputation stays but becomes PURELY player-driven — Command 3 Model 3.)

demon_lord.py — REDIRECT the Demon Lord's effects: apply_decision must no longer
write player_reputation. Its action effects now reduce the targeted/affected
factions' MORALE (reuse ACTION_DEFAULT_EFFECTS magnitudes), and append a line to
those factions' history ("Day N: struck by <action>"). Inter-faction strain is
Command 3 Model 4's job. Keep victim moods / rumor birth unchanged.

database.py — add a morale adjuster mirroring adjust_faction_reputation (clamped
0..100) and an append_faction_history(id, day, text) that caps the buffer.

RESTORING-FORCE DISCIPLINE (critical — this is the bug class): every faction-
level scalar must drift gently toward a baseline when unpressured so nothing
ratchets to 0/100. morale pulls toward ~55. Small daily steps, not snaps. (Add a
dawn morale-update hook in main._advance_one_hour_locked under _sim_lock: nudge
each faction's morale from its members' mood valences toward baseline. The
player_reputation and relationship restoring forces arrive with Command 3.)

Display: the existing HUD "Faction Reputation" number now correctly reads as
player standing — no change needed. Surface morale cracks and history lines via
log_event so they appear in the existing notifications panel. A dedicated faction
panel is OPTIONAL; if cheap, add faction morale to the /api/state faction summary
and show it in HUD.jsx, else DEFER it. Do NOT build the "factions react from
their state" behaviors (Tier B).

Tests (temp_db): Demon Lord lowers morale not player_reputation; morale clamps
and restores toward baseline; history appends and caps. Commit: "Day 7: faction
model decoupling — player standing vs morale vs history". After commit, update
the faction-model-redesign and chronicle-build-state memories.
```

---

## Command 3 of 3 — Live ML batch (4 runtime models; PREREQUISITE: Command 2)

```
day 7 — live ML batch (4 runtime/dawn-triggered models). PREREQUISITE: the
faction-decoupling command (Command 2) must already be committed — Models 3 and 4
rely on Faction.morale, Faction.history, and player_reputation NO LONGER being
written by the Demon Lord. If those are absent, STOP and report rather than
guessing. SHARED CONSTRAINTS: never regenerate the live world; preserve the
ml/train.py rule->synthetic->model->predict-with-fallback pattern; _sim_lock for
every tick read-modify-write; backend authoritative, frontend dumb; one system
per file; full pytest suite green before commit; commit on main.

All four run at DAWN inside main._advance_one_hour_locked, under _sim_lock, in
this order (2 feeds 1; 3 and 4 are faction aggregations). Each is a fast sklearn
predict (no LLM). Collect changed NPCs/factions/rumors and persist with the
existing save_npcs/save_faction/save_faction_relationship/save_rumor helpers.
Keep each step failure-isolated.

MODEL 2 first — NPC RELATIONSHIP DRIFT: new systems/relationships.py (pure,
dict-based, DB-free like rumors.py). Each dawn, drift Tier-1 NPCRelationship.
sentiment from the two NPCs' mood valences (behavior.MOOD_VALENCE), shared/
opposed faction alignment, and rumors both know; clamp to [-100, 100]; gentle
decay toward neutral so bonds fade without reinforcement (restoring force). ml/
train.py: train_relationship_drift_model + predict_sentiment_delta (rule
fallback). Unfreezes the since-gen-static graph AND feeds Model 1. Log notable
shifts as notifications.

MODEL 1 — RUMOR PROPAGATION MODEL: replace the rumors.gossip_chance formula with
a trained probabilistic classifier (per teller->listener per dawn), trained on
the existing gossip_chance rule sampled with noise; keep gossip_chance as the
fallback. Features = current ones (propagation_rate, drama_score, teller trait/
occupation propensity) PLUS the teller<->listener relationship sentiment/type
(now live from Model 2). ALSO finally drive distortion_level (stuck at 0): on a
hop, a small distortion probability increments the listener-side distortion_level
and applies a LIGHT deterministic text-blur to current_text (NO LLM in the tick
— hedge/garble transforms, e.g. append "...or so they say", soften specifics as
distortion rises) so a rumor visibly drifts from its original_event. ml/train.py:
train_rumor_propagation_model + predict_spread_probability (+ distortion helper).

MODEL 3 — PLAYER REPUTATION SCORER: each dawn, per faction, aggregate member
NPCs' player_sentiment weighted by faction-affiliation loyalty -> a target, then
drift player_reputation GENTLY toward it (the aggregate is the equilibrium, so a
neutral player pulls reputation back toward ~50 — this stops the slide to 0). ml/
train.py: train_player_reputation_model + predict_reputation_target/delta (rule
fallback = the weighted mean). Apply via database.adjust_faction_reputation. Now
that Command 2 freed player_reputation from the Demon Lord, this is the ONLY
writer — it genuinely tracks the player. Shows for free in the existing HUD
faction numbers.

MODEL 4 — FACTION RELATIONSHIP UPDATER: daily regression on the faction_
relationships rows (frozen since Day 2; database.get_faction_relationships /
save_faction_relationship exist) from the two factions' aggregated member moods
and shared/opposed Demon-Lord pressure (read recent demon_lord_decisions / morale
hits from Command 2). Drift relationship_score with a restoring pull toward the
Day-2 seed; emit game_log lines on notable changes ("The Watch and the Merchants'
Concord grow colder") + append to both factions' history. ml/train.py:
train_faction_relationship_model + predict_relationship_delta (rule fallback).
This is the GDD's cut "Political Stability" model brought down to town scale —
present it honestly as such.

Ordering recap in the dawn branch: Model 2 -> Model 1 -> Model 3 -> Model 4, then
the existing async Demon-Lord decision (now hits morale + composes with 3/4).

Tests (backend/tests/test_day7_ml.py): per-model unit tests (pure fns need no DB;
force RNG where stochastic; assert restoring forces and clamps); an integration
test that a dawn tick moves sentiments, spreads+distorts a rumor, drifts
reputation toward the member aggregate, and shifts a faction relationship.
Commit: "Day 7 ML batch: live relationship-drift / rumor-propagation+distortion /
player-reputation / faction-relationship models". After commit, update the
ml-registry-plan (now 11 models built) and chronicle-build-state memories.

DEFERRED (do NOT do here): the conversation DECOMPOSE refactor; Model 5 Tile
Interaction Scorer and Model 6 Witness Memory Tagger (Day 8); the "factions react
from their state" Tier B behaviors and a full faction HUD panel; nation-scale
Political Stability / Economic Flow (honest roadmap, continent is visual-only).
```
