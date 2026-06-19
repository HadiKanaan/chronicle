# Day 8 — four `/speckit.implement` commands (visual · ML 5–6 · tier promotion · RAG memory)

Authored 2026-06-18 (updated to add Command D — RAG memory retrieval). Day 8 is
the final capstone day. Four independent commands, each its own commit on main.

**Recommended order:** **A** (visual flavor — biggest demo win) → **D** (RAG
memory — the conversation-depth upgrade) → **B** (ML registry to 13/14) → **C**
(tier promotion). They were split so each ships and is reviewed on its own; run as
many as time allows.

> **STATUS (2026-06-19):** ✅ **A DONE** (visual flavor + 64×64 expansion). ✅ **D
> DONE** (commit 66b4494, systems/recall.py TF-IDF recall). ✅ The deferred
> "conversation decompose + situation-slim" item also SHIPPED this day — the
> conversation speedup (LLM writes only the reply; mood/sentiment/memory computed
> backend-side via systems/sentiment.py) plus prefix-warming, the de-naming fix,
> brevity/sentence-trim, and the IPv4 proxy fix. See [[chronicle-build-state]].
> ⏳ **REMAINING: run B next, then C.** (B's Witness Memory Tagger should gate
> EVENT/rumor seeding — storm memories, rumor witnesses — NOT the conversation
> memories, which build_conversation_memory already handles, so the two paths
> don't fight.)

Shipped through Day 7: fog/save/continent, LLM schema-hardening + provider toggle,
faction decoupling, the live ML batch (11 models), debug controls, conversation
tuning + current-turn prompt anchor. See [[chronicle-build-state]],
[[ml-registry-plan]].

## Shared constraints (all commands)
> NEVER regenerate the live world (NPC memories, history, rumors, faction state,
> Demon-Lord decisions must survive — augment in place). Backend is the single
> source of truth; the frontend is a dumb renderer that paints what the payload
> says. PRESERVE the ml/train.py pattern: a ground-truth rule fn → synthetic
> samples labelled by it → a scikit-learn model → predict-with-fallback. _sim_lock
> for every read-modify-write the tick also touches. One system per file. Full
> pytest suite green before each commit; commit on main. Assets (sprite PNGs) are
> gitignored — copy what you need into frontend/public/assets/ as the existing
> terrain/character assets already are.

---

## Command A of 4 — Visual flavor pass (the headline demo win)

```
day 8 — visual flavor pass. Make the town read as a real game, not a tile grid.
Frontend-heavy; small backend payload additions only. SHARED CONSTRAINTS: backend
authoritative, frontend dumb renderer; never regenerate the world; assets are
gitignored - copy needed sprites into frontend/public/assets/; full pytest suite
green before commit; commit on main.

1) BUILDING SPRITES (biggest win). Today buildings are bare wall/floor tile rects.
The kenney_medieval-rts pack sits at the CHRONICLE root (gitignored, unused).
Select building sprites and copy them into frontend/public/assets/buildings/.
Backend: add `buildings` to the /api/state RenderPayload as display-ready dicts
{building_type, x, y, width, height} (the data is already on region.buildings -
just surface it; do NOT send simulation-only fields). Frontend: add a
BUILDING_ATLAS in sprites.js (building_type -> sprite) and draw one sprite per
building anchored over its footprint in GameCanvas, beneath characters. Keep the
wall/floor tiles as the fallback when a sprite is missing. Walls/doors mechanics
are untouched - this is purely a draw layer.

2) DECORATION LAYER. Backend generates a decoration list ONCE at world gen
(trees/bushes/rocks on passable grass tiles, avoiding buildings, paths, and NPC
home/work tiles), persists it as static data (alongside the tile grid in
region_static so it survives and isn't rewritten hourly), and surfaces it in the
payload. Frontend draws decoration sprites (atlas in sprites.js) beneath
characters. Deterministic/seeded so it never flickers between polls.

3) NPC POSITION LERP. Purely cosmetic: GameCanvas interpolates each NPC's drawn
position from its previous to current tile across the ~500ms poll interval (and
requestAnimationFrame for smoothness) so NPCs glide instead of stepping. Backend
stays authoritative for actual positions; this only affects rendering.

4) WEATHER + WATER. A weather overlay on the canvas keyed off payload.weather
(rain streaks / fog wash / storm darken+flecks - cheap canvas effects, no assets
needed) layered with the existing day/night tint. Subtle river/water shimmer
(slow color cycle on water tiles). All frontend.

Backend changes are limited to surfacing `buildings` and the decoration list in
the payload + persisting decorations once. Tests: payload includes buildings +
decorations; decorations avoid non-grass/occupied tiles and are stable across
calls. Rebuild the frontend. Commit: "Day 8: visual flavor - building sprites,
decoration layer, NPC lerp, weather/water effects". Update chronicle-build-state.
DO NOT: change any simulation logic, regenerate the world, or alter walls/doors.
```

---

## Command B of 4 — ML Models 5 & 6 (registry to 13/14)

```
day 8 — ML registry completion: Models 5 (Tile Interaction Scorer) and 6 (Witness
Memory Tagger). SHARED CONSTRAINTS: preserve the ml/train.py rule->synthetic->
model->predict-with-fallback pattern; _sim_lock for tick read-modify-writes; one
system per file; full suite green before commit; commit on main. Each is a fast
sklearn predict with the existing hand-rolled rule as the fallback.

MODEL 5 - TILE INTERACTION SCORER (hourly, per NPC): replace the if/else in
behavior._behavior_target with a trained model that scores candidate destinations
(home, work, tavern, market, plaza) given the NPC's behavior state, hour, mood
valence, sociability, and occupation, and picks the best. The current
_behavior_target logic IS the ground-truth rule - sample it with noise to train.
ml/train.py: train_tile_interaction_model + predict_destination (rule fallback).
Wire into behavior.update_hourly. Keep movement/pathing unchanged - this only
chooses the target tile. Verify NPCs still converge sensibly (no thrashing).

MODEL 6 - WITNESS MEMORY TAGGER (per event): a threshold model using each NPC's
skills.perception (present on every card, currently unused) plus proximity to
decide whether an NPC actually witnesses and remembers a nearby event - so memory
and rumor seeding become selective instead of blanket. ml/train.py:
train_witness_model + predict_witnessed(perception, distance, drama) (rule
fallback: high perception + close + dramatic -> witnessed). Apply where events are
seeded today: rumor witness selection (rumors/demon_lord seeding) and storm/event
memories in behavior.update_daily - gate `remember`/known_by on predict_witnessed
instead of fixed slices. Keep a floor so at least one witness always exists. This
also tags WHAT enters the memory store that Command D retrieves over.

Tests (per model: rule directions + clamps + fallback; integration that witness
tagging varies with perception). Commit: "Day 8 ML: Tile Interaction Scorer +
Witness Memory Tagger (registry 13/14)". Update ml-registry-plan (13 built) and
chronicle-build-state. The two nation-scale models (Political Stability, Economic
Flow) stay an honest roadmap item - the continent is visual-only.
```

---

## Command C of 4 — Dynamic tier promotion / demotion ("watch a farmer become real")

```
day 8 - dynamic NPC tier promotion/demotion (LRU of personhood). SHARED
CONSTRAINTS: never regenerate the world; _sim_lock for the read-modify-writes;
one system per file; full suite green before commit; commit on main.

When the player converses repeatedly with a Tier-2/3 NPC (track a per-NPC
player-conversation count; threshold ~2-3), PROMOTE it to Tier 1: seed dark_trait
/ redeeming_quality / trauma from names.json pools, flip tier to 1, link 2-3
relationships into the Tier-1 social graph, and mark it for LLM enrichment (reuse
the startup _warm_llm_and_enrich_tier1 path, or kick a daemon-thread enrichment at
promotion - single-call queue + _sim_lock discipline; it stubs until enrichment
lands). To keep ~10 Tier-1s, DEMOTE the least-recently-conversed-with Tier-1 (LRU;
track a last-talked stamp) to Tier 2 - demotion is just tier=2, the card keeps its
memories/history/enrichment so re-promotion remembers everything. Exclude
is_player and is_demon_lord from both.

New systems/tiers.py (pure where possible) for the promote/demote logic + LRU;
wire the conversation flow (main._run_conversation / delta application) to bump
the count + last-talked stamp and trigger promotion under _sim_lock. Tests:
promotion seeds traits + flips tier + links relationships; demotion is LRU and
preserves the card; player/demon-lord excluded; ~10 Tier-1 cap holds. Commit:
"Day 8: dynamic NPC tier promotion/demotion (LRU of personhood)". Update
chronicle-build-state. Demos as "talk to a random farmer a few times and watch
them become a real, remembered character."
```

---

## Command D of 4 — RAG memory retrieval (NPCs recall the RELEVANT memory)

```
day 8 - RAG memory retrieval for NPC conversations. Today the prompt injects an
NPC's most RECENT few memories (recency), so old-but-important memories fall off
the cap and the injected ones often don't relate to what the player just asked.
Replace recency selection with RELEVANCE retrieval: hold a larger memory store but
inject only the handful semantically relevant to the current message - the prompt
stays small AND on-point as an NPC accumulates a life. SHARED CONSTRAINTS: backend
authoritative; never regenerate the world; preserve graceful fallback; one system
per file; full suite green before commit; commit on main.

SCOPE: apply RAG to the NPC memory_buffer (facts/events), NOT conversation_history
(the verbatim history is replayed as contiguous chat turns to keep Ollama's prefix
cache warm; pulling non-adjacent past turns would shatter that - leave it a small
recency window).

1) ENLARGE THE STORE: raise behavior.MEMORY_BUFFER_CAP (10 -> ~50) so memories
accumulate instead of FIFO-ing away; keep the day-stamp dedup.

2) RETRIEVER: new systems/recall.py (pure, DB-free). A scikit-learn TF-IDF
retriever - fit a TfidfVectorizer over the NPC's memory_buffer at query time
(cheap for ~50 short strings), score each memory against the player's current
message (sklearn cosine_similarity), return the top-k (k=3). GRACEFUL FALLBACK
(house pattern): if scikit-learn is unavailable or there are too few memories,
fall back to recency (last 3). This IS the RAG/ML - retrieval ranking via TF-IDF
cosine; note local embeddings (Ollama nomic-embed-text) as the higher-quality
upgrade path but DO NOT add that dependency now.

3) WIRE INTO THE PROMPT: give build_situation_block an optional recalled_memories
param; when provided, inject those instead of memory_buffer[-3:] (keep the last-3
default so existing callers/tests are unchanged). converse_tier1 retrieves the
top-3 relevant memories for the player_text via recall.py and passes them in.

4) OPTIONAL (only if cheap): importance-weighted ranking - blend cosine with a
memory's drama/importance if available (ties to Command B's Witness Memory
Tagger, which decides what enters the store). Otherwise pure similarity.

Tests (systems/recall.py): given memories like ["bought bread at market", "my
brother drowned in the flood", "mended a fence"] and the query "tell me about your
family", retrieval surfaces the brother memory over the more-recent fence memory;
empty/tiny stores and a no-sklearn path fall back to recency; build_situation_block
uses recalled_memories when given. Commit: "Day 8: RAG memory retrieval - NPCs
recall the relevant memory, not just the most recent". Update chronicle-build-state.
Demo line: "the NPC pulls up the memory that matters to what you said, from a deep
past - not just the last thing that happened."
```

---

## Deferred (NOT Day 8 unless time is abundant)
- **Continent visual richness** (hillshading from the existing elevation field,
  more biome bands — beach/mountain/snow — higher grid resolution, parchment
  styling). Cheap, frontend-mostly; a nice extra if Command A lands early.
- ~~**Conversation decompose + situation-slim** (LLM prose-only, ML-derived
  mood/sentiment) to cut warm latency~~ — ✅ DONE 2026-06-19 (the conversation
  speedup + prefix-warming work; see [[chronicle-build-state]]).
- **Embedding-based RAG** (Ollama nomic-embed-text + a per-memory vector store) —
  the quality upgrade over Command D's TF-IDF.
- **Nation-scale models** (Political Stability, Economic Flow) — honest roadmap;
  the continent is not simulated.
```
