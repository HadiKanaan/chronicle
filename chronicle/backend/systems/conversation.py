"""LLM conversation system (Day 5 / User Story 3; Day 8 speedup).

Talks to a locally running Ollama instance for two jobs:

1. Tier 1 NPC conversations: by default (Day 8) the model writes ONLY the
   in-character reply as plain text - smaller input, smaller output - and the
   backend computes the side-channel (sentiment delta from the player's message
   via systems.sentiment, the post-exchange mood by drifting along
   behavior.MOOD_VALENCE, and a significance-gated memory line) for free. The
   old single-call JSON envelope ({reply, mood, sentiment_delta, memory}) is
   retained behind the ``LLM_STRUCTURED_OUTPUT`` flag for A/B comparison.
2. Tier 1 card enrichment: a one-off generation pass that gives each Tier 1
   NPC a sharper appearance, dark trait, redeeming quality, trauma, and
   conversation style than the seeded placeholders.

All Ollama calls go through a single-call queue (a module lock): qwen3:4b on a
CPU-only laptop takes seconds per reply, so concurrent calls would only slow
each other down. ``think=False`` is mandatory on every call - qwen3 is a
reasoning model and will otherwise burn minutes emitting <think> blocks.

This module is pure LLM client + prompt + parsing. It never touches the
database and never applies deltas: ``main.py`` orchestrates persistence under
its simulation lock, and the raw card-delta JSON is parsed and repaired here so
nothing model-shaped ever reaches the frontend. Tier 2/3 NPCs (and any tier
when Ollama is unreachable) get rule-based stub replies in the same shape, so
the endpoint never depends on the LLM being up.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import random
import re
import threading
import time
from typing import Any, Optional

from ml import train as ml
from models.npc import MoodType
from systems import behavior, recall, sentiment

try:  # pragma: no cover - exercised by environment, not unit tests
    import ollama

    _OLLAMA_IMPORTED = True
except Exception:  # noqa: BLE001 - missing client just means stub replies
    ollama = None  # type: ignore[assignment]
    _OLLAMA_IMPORTED = False

try:  # pragma: no cover - optional; only used when the Azure provider is on
    from openai import AzureOpenAI

    _OPENAI_IMPORTED = True
except Exception:  # noqa: BLE001 - missing lib just means the azure toggle stays off
    AzureOpenAI = None  # type: ignore[assignment]
    _OPENAI_IMPORTED = False


# The one swappable model decision (see specs research.md decision 4).
# Demo config: qwen2.5:1.5b-instruct for max responsiveness (~8-12s warm on this
# CPU vs ~20s for 3b, ~45s for 4b). The schema constraint keeps its output
# well-formed; the occupation-anchored prompt curbs the small-model quirks. Swap
# to "qwen2.5:3b-instruct" for quality or "qwen3:4b" for top quality.
MODEL = "qwen2.5:1.5b-instruct"
OLLAMA_HOST = "http://localhost:11434"
# Keep the model resident permanently (~3.5 GB RAM): an idle unload costs ~18s
# of cold reload on the next conversation, the worst possible first impression.
KEEP_ALIVE = -1
LLM_TIMEOUT_SECONDS = 120.0

# Day 8: by default the model emits ONLY the reply, so split the work between
# the LLM (reply text) and cheap backend ML/heuristics (mood/sentiment/memory).
# Set True to restore the Day 5-7 single-call JSON envelope (richer model-authored
# memories, A/B latency comparison) - build_character_prompt and converse_tier1
# both switch paths on this flag.
LLM_STRUCTURED_OUTPUT = False

# Conversation replies stay short (1-3 sentences) so num_predict can be tight.
# Plain-text path (default): ~80 tokens is plenty for 1-2 sentences and a fraction
# of the old envelope's output cost. Structured path keeps the wider 260 cap: a
# 220-token cap was observed live truncating the JSON envelope mid-string when the
# model wrote a long reply plus a long memory.
CONVERSE_REPLY_NUM_PREDICT = 80
CONVERSE_NUM_PREDICT = 260
CARD_GEN_NUM_PREDICT = 300

# A reply this similar to the NPC's previous line counts as parroting and
# triggers the anti-repeat retry (qwen3:4b habitually copies its own last
# assistant turn verbatim).
REPEAT_SIMILARITY = 0.9

# Rolling per-NPC conversation transcript kept on the card for prompt context.
# Day 8: 4, not 6 - fewer replayed turns means less prompt prefill on every turn,
# and with relevance recall the deep memory store carries the long-term context.
HISTORY_CAP = 4
SENTIMENT_DELTA_LIMIT = 10
MEMORY_MAX_CHARS = 200
REPLY_MAX_CHARS = 600

# Day 8 memory gating: only a significant exchange seeds the deep memory store
# (the Witness Memory Tagger's substrate), so trivial chatter never bloats it.
# Significant = |sentiment_delta| >= this, OR the message names a charged topic.
MEMORY_SIGNIFICANCE_THRESHOLD = 4

# Moods reserved for scripted story beats - the conversation mood drift below
# never emits them (an NPC does not start grieving because the player was rude).
RESERVED_MOODS = {"grieving", "fearful"}

# How far a maximal sentiment swing (+-SENTIMENT_DELTA_LIMIT) drifts an NPC along
# the valence ladder - ~0.30 is about two mood rungs, so a clear insult can move
# content -> suspicious while idle chatter holds the current mood.
MOOD_DRIFT_SPAN = 0.30

VALID_MOODS = {mood.value for mood in MoodType}

# JSON Schema for the Tier 1 card delta. Passed to Ollama's schema-constrained
# decoding so the four fields are always present and well-typed - "reply" can no
# longer be dropped, and "mood" can no longer be an invented label. The salvage/
# retry net downstream stays as defense in depth (small models still slip).
CARD_DELTA_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "minLength": 1},
        "mood": {"type": "string", "enum": sorted(VALID_MOODS)},
        "sentiment_delta": {
            "type": "integer",
            "minimum": -SENTIMENT_DELTA_LIMIT,
            "maximum": SENTIMENT_DELTA_LIMIT,
        },
        "memory": {"type": "string"},
    },
    "required": ["reply", "mood", "sentiment_delta", "memory"],
}

# Single-call queue: every Ollama request in the process serializes here.
_llm_lock = threading.Lock()
_client: Optional[Any] = None

logger = logging.getLogger("chronicle.llm")

_stub_rng = random.Random()


def _get_client() -> Optional[Any]:
    global _client
    if not _OLLAMA_IMPORTED:
        return None
    if _client is None:
        _client = ollama.Client(host=OLLAMA_HOST, timeout=LLM_TIMEOUT_SECONDS)
    return _client


def llm_available() -> bool:
    """True when the Ollama server answers; never raises."""
    client = _get_client()
    if client is None:
        return False
    try:
        client.list()
        return True
    except Exception:  # noqa: BLE001 - server down means stub replies
        return False


# --------------------------------------------------------------------------- #
# Provider selection (demo): local Ollama vs Azure OpenAI, toggled live. Azure
# is configured purely from environment variables (the key never lives in code
# or logs), and the toggle only engages it when those are present - otherwise it
# stays on local. Lets the demo show the local 1.5B is almost as fast as cloud.
# --------------------------------------------------------------------------- #
_provider = "local"  # "local" | "azure"
_last_call_seconds = 0.0
_last_provider = "local"
_azure_client: Optional[Any] = None


def _azure_config() -> tuple[Optional[str], Optional[str], Optional[str], str]:
    """Read Azure creds from the environment at call time (not import time) so a
    .env loaded after import - or changed between runs - is always picked up."""
    return (
        os.environ.get("AZURE_OPENAI_ENDPOINT"),
        os.environ.get("AZURE_OPENAI_API_KEY"),
        os.environ.get("AZURE_OPENAI_DEPLOYMENT"),
        os.environ.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
    )


def azure_available() -> bool:
    """True when the openai lib is importable and Azure creds are all present."""
    endpoint, api_key, deployment, _ = _azure_config()
    return bool(_OPENAI_IMPORTED and endpoint and api_key and deployment)


def current_provider() -> str:
    return _provider


def last_call_seconds() -> float:
    return round(_last_call_seconds, 2)


def toggle_provider() -> str:
    """Flip local<->azure. Engages azure only when configured; otherwise stays
    local so the demo toggle never lands on a dead provider."""
    global _provider
    if _provider == "local":
        _provider = "azure" if azure_available() else "local"
    else:
        _provider = "local"
    return _provider


def _get_azure_client() -> Optional[Any]:
    global _azure_client
    if not azure_available():
        return None
    if _azure_client is None:
        endpoint, api_key, _, api_version = _azure_config()
        _azure_client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
    return _azure_client


def prewarm() -> bool:
    """Load the model into memory so the first real conversation is warm."""
    reply = _call_llm(
        system="You answer with a single word.",
        user="Say ready.",
        json_format=False,
        num_predict=8,
    )
    return reply is not None


def _call_llm(
    system: str,
    user: str,
    json_format: bool = True,
    num_predict: int = CONVERSE_NUM_PREDICT,
    temperature: float = 0.8,
    history: Optional[list[dict[str, str]]] = None,
    schema: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """One serialized Ollama chat call. Returns the raw text or None on failure.

    history (optional prior chat turns) sits between the system prompt and the
    user message. Keeping system + history byte-identical across turns lets
    Ollama's prefix cache skip re-evaluating them - on this CPU-only laptop
    that is the difference between ~8s and ~70s per call.

    schema (optional JSON Schema) switches Ollama from "valid JSON" to
    schema-constrained decoding: the grammar forces every required field to be
    present and well-typed at sampling time, which is what kills qwen3:4b's
    habit of dropping "reply" or inventing an out-of-enum mood. It constrains
    sampling only, so the prompt prefix cache is untouched. Falls back to
    format="json" (syntax only) or None when no schema is given.
    """
    global _last_call_seconds, _last_provider
    # Only engage azure when it is actually configured; otherwise stay local.
    provider = _provider if (_provider == "local" or azure_available()) else "local"
    start = time.monotonic()
    text: Optional[str] = None
    try:
        with _llm_lock:
            if provider == "azure":
                text = _call_azure(system, user, json_format, num_predict, temperature, history)
            else:
                text = _call_ollama(system, user, json_format, num_predict, temperature, history, schema)
    except Exception as exc:  # noqa: BLE001 - any transport/model failure -> stub path
        # Surfaced on the uvicorn console so silent stub replies are explainable.
        logger.warning("LLM call failed (provider=%s): %r", provider, exc)
        text = None
    finally:
        _last_call_seconds = time.monotonic() - start
        _last_provider = provider
    return text


def _call_ollama(
    system: str,
    user: str,
    json_format: bool,
    num_predict: int,
    temperature: float,
    history: Optional[list[dict[str, str]]],
    schema: Optional[dict[str, Any]],
) -> Optional[str]:
    """Local Ollama chat call (caller holds _llm_lock)."""
    client = _get_client()
    if client is None:
        return None
    response_format = schema if schema is not None else ("json" if json_format else None)
    response = client.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            *(history or []),
            {"role": "user", "content": user},
        ],
        think=False,
        format=response_format,
        keep_alive=KEEP_ALIVE,
        options={"temperature": temperature, "num_predict": num_predict},
    )
    logger.info(
        "Ollama call (schema=%s): prompt_eval=%s tok / %.1fs, gen=%s tok / %.1fs",
        schema is not None,
        getattr(response, "prompt_eval_count", None),
        (getattr(response, "prompt_eval_duration", 0) or 0) / 1e9,
        getattr(response, "eval_count", None),
        (getattr(response, "eval_duration", 0) or 0) / 1e9,
    )
    return response["message"]["content"]


def _call_azure(
    system: str,
    user: str,
    json_format: bool,
    num_predict: int,
    temperature: float,
    history: Optional[list[dict[str, str]]],
) -> Optional[str]:
    """Azure OpenAI chat call (caller holds _llm_lock). JSON mode stands in for
    Ollama's schema-constrained decoding; the parse/repair net handles the rest."""
    client = _get_azure_client()
    if client is None:
        return None
    _, _, deployment, _ = _azure_config()
    messages = [
        {"role": "system", "content": system},
        *(history or []),
        {"role": "user", "content": user},
    ]
    kwargs: dict[str, Any] = {
        "model": deployment,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": num_predict,
    }
    if json_format:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    logger.info("Azure call (deployment=%s) ok", deployment)
    return response.choices[0].message.content


# --------------------------------------------------------------------------- #
# Card-delta parsing and repair
# --------------------------------------------------------------------------- #
def _extract_json(raw: str) -> Optional[dict[str, Any]]:
    """Pull one JSON object out of model output, repairing common defects."""
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
            try:
                data = json.loads(attempt)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, dict):
                return data
    return None


def _fallback_reply(raw: str) -> str:
    """Salvage something speakable when the JSON envelope is broken."""
    match = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    if match:
        try:
            return json.loads(f'"{match.group(1)}"')
        except (json.JSONDecodeError, ValueError):
            return match.group(1)
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    text = text.strip().strip("{}").strip()
    return text[:REPLY_MAX_CHARS] if text else "..."


def _looks_like_json_guts(text: str) -> bool:
    """True when salvaged text is still card-delta JSON, not speakable prose."""
    return bool(re.search(r'"\s*(reply|mood|sentiment_delta|memory)\s*"\s*:', text))


def _safe_line(current_mood: str) -> str:
    """A guaranteed-speakable in-character line for when salvage fails.

    Observed live: qwen3:4b sometimes drops the "reply" field entirely, leaving
    only delta fields - the player must never see those.
    """
    return _stub_rng.choice(_STUB_BY_MOOD.get(current_mood, _STUB_BY_MOOD["neutral"]))


def _valence_of(mood: str) -> float:
    # Mirrors behavior.MOOD_VALENCE without importing the behavior system.
    return {
        "happy": 0.90, "content": 0.70, "neutral": 0.50, "suspicious": 0.40,
        "anxious": 0.35, "angry": 0.25, "grieving": 0.20, "fearful": 0.15,
    }.get(mood, 0.5)


def parse_card_delta(raw: str, current_mood: str) -> dict[str, Any]:
    """Turn raw model output into a display-safe reply plus a clamped card delta.

    Always returns the full shape, no matter how mangled the input: an invalid
    mood falls back to the ML mood model (LLM proposes, ML validates), a missing
    delta becomes a no-op, and strings are truncated. The raw JSON never leaves
    the backend.

    The extra "reply_was_genuine" flag is internal plumbing for converse_tier1's
    retry: False means the model never spoke a usable reply and the returned
    line is salvage (memory-field rescue or a canned safe line).
    """
    data = _extract_json(raw)
    if data is None:
        reply = _fallback_reply(raw)
        if _looks_like_json_guts(reply):
            reply = _safe_line(current_mood)
        return {
            "reply": reply,
            "mood": current_mood,
            "sentiment_delta": 0,
            "memory": "",
            "reply_was_genuine": False,
        }

    raw_reply = ""
    for key in ("reply", "response", "text", "say", "speech", "dialogue", "answer"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            raw_reply = value.strip()
            break
    reply_was_genuine = bool(raw_reply) and not _looks_like_json_guts(raw_reply)
    reply = raw_reply if reply_was_genuine else ""
    if not reply:
        # Measured live (Day 6): when qwen3:4b drops "reply" - roughly a third
        # to half of calls - the spoken answer usually lands in "memory"
        # instead. Salvage it as the line before resorting to a canned one.
        memory_candidate = str(data.get("memory", "")).strip()
        if memory_candidate and not _looks_like_json_guts(memory_candidate):
            reply = memory_candidate
    if not reply:
        reply = _safe_line(current_mood)
    # A spoken line should never carry a "Day N:" stamp - that only appears when
    # the model imitates the stamped memories in its prompt (often via the
    # memory-field salvage). Strip it so it never reaches the player.
    reply = re.sub(r"^\s*Day\s+\d+:\s*", "", reply)
    reply = reply[:REPLY_MAX_CHARS]

    try:
        sentiment_delta = int(data.get("sentiment_delta", 0))
    except (TypeError, ValueError):
        sentiment_delta = 0
    sentiment_delta = max(-SENTIMENT_DELTA_LIMIT, min(SENTIMENT_DELTA_LIMIT, sentiment_delta))

    mood = str(data.get("mood", "")).strip().lower()
    if mood not in VALID_MOODS:
        # Map the exchange's tone onto an event valence and let the mood model
        # arbitrate instead of trusting an invented label.
        event_valence = 0.5 + sentiment_delta / (2 * SENTIMENT_DELTA_LIMIT)
        mood = ml.predict_conversation_mood(_valence_of(current_mood), event_valence)

    memory = str(data.get("memory", "")).strip()[:MEMORY_MAX_CHARS]

    return {
        "reply": reply,
        "mood": mood,
        "sentiment_delta": sentiment_delta,
        "memory": memory,
        "reply_was_genuine": reply_was_genuine,
    }


# --------------------------------------------------------------------------- #
# Tier 1 conversation
# --------------------------------------------------------------------------- #
def _normalize_speech(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", text.lower())).strip()


def _is_parrot(reply: str, previous_reply: str) -> bool:
    """True when the model recited its previous line instead of answering.

    Observed live (Isolde Vane, day 173-174): qwen3:4b answered three
    different questions with one identical sentence - real LLM output that
    reads exactly like a canned fallback to the player.
    """
    if not reply or not previous_reply:
        return False
    a, b = _normalize_speech(reply), _normalize_speech(previous_reply)
    if not a or not b:
        return False
    if a == b:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= REPEAT_SIMILARITY


def sentiment_phrase(sentiment: int) -> str:
    if sentiment >= 75:
        return "warm and trusting"
    if sentiment >= 55:
        return "friendly"
    if sentiment >= 40:
        return "neutral, reserving judgement"
    if sentiment >= 25:
        return "wary and distrustful"
    return "hostile"


def build_character_prompt(npc: dict[str, Any]) -> str:
    """Static system prompt: the card's identity, flavor, and the JSON contract.

    Deliberately excludes everything that changes between exchanges (mood,
    sentiment, memories, rumors, history) - those travel in
    build_situation_block - so this prompt stays byte-identical across turns
    and Ollama's prefix cache can skip re-evaluating it. On this CPU-only
    laptop that cache is the difference between ~8s and ~70s per call.
    """
    traits = ", ".join(npc.get("personality_traits", [])) or "unremarkable"
    lines = [
        f"You are roleplaying {npc.get('name', 'a villager')}, a "
        f"{npc.get('age', 30)}-year-old {npc.get('occupation', 'villager')} in "
        "Aldenmoor, a small medieval town.",
        f"Personality: {traits}.",
    ]
    if npc.get("appearance"):
        lines.append(f"Appearance: {npc['appearance']}.")
    if npc.get("dark_trait"):
        lines.append(
            f"Hidden flaw: {npc['dark_trait']} - let it color your words subtly; never announce it."
        )
    if npc.get("redeeming_quality"):
        lines.append(f"Redeeming quality: {npc['redeeming_quality']}.")
    if npc.get("trauma"):
        lines.append(f"Old wound: {npc['trauma']}.")
    if npc.get("conversation_style"):
        lines.append(f"How you speak: {npc['conversation_style']}.")

    occupation = npc.get("occupation", "villager")
    # Shared persona guidance for either output mode.
    guidance = (
        "Speak plainly and concretely, like a real townsperson in conversation - "
        "1 to 2 short, direct sentences in a light medieval tone. Do NOT use "
        "flowery metaphors, riddles, or grand cosmic imagery, and do NOT keep "
        "returning to the same image (e.g. do not mention the river in every "
        f"reply). Ground what you say in your own life as a {occupation}: your "
        "trade and tools, the folk you deal with, your neighbours, and recent "
        "happenings. Answer the player's actual words directly. Never mention "
        "being an AI or a game, and never repeat your earlier lines word-for-word. "
    )
    if LLM_STRUCTURED_OUTPUT:
        moods = ", ".join(sorted(VALID_MOODS))
        guidance += (
            "Respond ONLY with one JSON object exactly like this: "
            '{"reply": "<what you say out loud>", '
            f'"mood": "<your mood now, one of: {moods}>", '
            '"sentiment_delta": <integer -10..10, how this exchange shifted your '
            "feeling toward the player>, "
            '"memory": "<one short sentence you will remember, or empty>"} '
            'Always include all four fields. "reply" comes FIRST and must never be '
            "empty or missing - an answer without \"reply\" is thrown away unheard."
        )
    else:
        # Day 8: the model writes only the spoken line; the backend computes the
        # mood/sentiment/memory side-channel. No JSON, no schema grammar.
        guidance += "Answer in 1-2 short, plain sentences, in character - nothing else."
    lines.append(guidance)
    return "\n".join(lines)


def build_situation_block(
    npc: dict[str, Any],
    player_name: str,
    rumor_texts: Optional[list[str]] = None,
    recalled_memories: Optional[list[str]] = None,
    include_memories: bool = True,
) -> str:
    """The volatile half of the prompt: mood, disposition, rumors, memories.

    Rides inside the final user message, AFTER the cached system prompt and
    history, so a mood shift or a fresh memory never invalidates the prefix
    cache. rumor_texts are the actual texts of rumors the NPC knows, resolved
    by the caller - this module never touches the database (Day 6 / US4).

    Day 8 (RAG): when ``recalled_memories`` is given, those relevance-retrieved
    memories are injected instead of the recency default - so the NPC pulls up
    the memory that matters to what the player said, not just the latest. The
    default (None -> most recent 3) keeps existing callers/tests unchanged.

    ORDER matters for prefix warming (Day 8 speedup): the memories section is
    appended LAST and gated by ``include_memories``. Everything before it
    (mood/disposition/rumors) is stable while a dialogue window is open and
    frozen, so prewarm_npc can pre-evaluate it (include_memories=False) as a true
    prefix of the real turn's user message - the only varying tails are the
    query-relevant memories and the player's line, which Ollama re-evaluates
    cheaply on top of the warmed prefix.
    """
    mood = npc.get("current_mood", "neutral")
    mood_reason = npc.get("mood_reason", "")
    sentiment = int(npc.get("player_sentiment", 50))
    lines = [
        "[What you know right now]",
        f"Current mood: {mood}" + (f" ({mood_reason})." if mood_reason else "."),
        f"You feel {sentiment_phrase(sentiment)} toward {player_name} "
        f"(sentiment {sentiment}/100).",
    ]
    if rumor_texts:
        lines.append("Rumors you have heard around town (you may bring them up):")
        lines.extend(f"- {text}" for text in rumor_texts)
    # Memories LAST so the block above stays a warm-able stable prefix. Inject the
    # relevance-retrieved memories when the caller supplies them; otherwise the
    # recency default. Either way a small handful - a long list buries the actual
    # question lower in the prompt, where a small model under-attends to it.
    if include_memories:
        if recalled_memories is not None:
            memories = recalled_memories
        else:
            memories = npc.get("memory_buffer", [])[-3:]
        if memories:
            lines.append("Things you remember:")
            lines.extend(f"- {memory}" for memory in memories)
    return "\n".join(lines)


def _history_messages(npc: dict[str, Any]) -> list[dict[str, str]]:
    """Prior exchanges replayed as native chat turns for the prompt prefix.

    Day 8 default (plain mode): assistant turns replay as the bare spoken line,
    matching what the model is now asked to produce. Under LLM_STRUCTURED_OUTPUT
    they are wrapped back into the {"reply": ...} envelope - free in-context
    schooling against the old habit of dropping the field. The full stored
    history is used (append-only until HISTORY_CAP) rather than a sliding window:
    a window that slides every turn would shift every message and break the
    prefix cache each time.
    """
    messages: list[dict[str, str]] = []
    for entry in npc.get("conversation_history", [])[-HISTORY_CAP:]:
        player_text = entry.get("player_text", "")
        npc_response = entry.get("npc_response", "")
        if not player_text or not npc_response:
            continue
        messages.append({"role": "user", "content": player_text})
        content = (
            json.dumps({"reply": npc_response}, ensure_ascii=False)
            if LLM_STRUCTURED_OUTPUT
            else npc_response
        )
        messages.append({"role": "assistant", "content": content})
    return messages


# Anti-repeat nudge appended to the retry's user message (both paths).
_ANTI_REPEAT_NUDGE = (
    "\nIMPORTANT: do NOT reuse the wording of your previous replies - "
    "say something new that answers these exact words."
)


def converse_tier1(
    npc: dict[str, Any],
    player_name: str,
    player_text: str,
    rumor_texts: Optional[list[str]] = None,
) -> dict[str, Any]:
    """One Tier 1 conversation turn. Falls back to a stub if Ollama is down.

    Always returns {"reply", "mood", "sentiment_delta", "memory", "used_llm"}
    with every field validated and display-safe, so main._apply_conversation_delta
    is path-agnostic.

    Day 8 default: the LLM writes ONLY the reply (plain text); the backend
    computes the mood/sentiment/memory side-channel (cheaper input, cheaper
    output, none of the JSON-envelope bugs). Set LLM_STRUCTURED_OUTPUT to run the
    legacy single-call JSON path instead (model-authored memories, A/B latency).
    """
    if LLM_STRUCTURED_OUTPUT:
        return _converse_tier1_structured(npc, player_name, player_text, rumor_texts)
    return _converse_tier1_plain(npc, player_name, player_text, rumor_texts)


def _warm_user_block(
    npc: dict[str, Any],
    player_name: str,
    rumor_texts: Optional[list[str]] = None,
) -> str:
    """The exact stable prefix of converse_tier1's user message (no memories,
    no player line) - what prewarm_npc warms and the real turn extends."""
    return build_situation_block(npc, player_name, rumor_texts, include_memories=False)


def prewarm_npc(
    npc: dict[str, Any],
    player_name: str = "a traveler",
    rumor_texts: Optional[list[str]] = None,
) -> bool:
    """Pre-evaluate an NPC's prompt PREFIX so the first real turn is warm.

    Called when the player OPENS an NPC's dialogue window, before they have
    typed anything. It issues a tiny (num_predict=1) chat call carrying the exact
    system prompt + replayed history + STABLE situation prefix (mood/disposition/
    rumors, no memories, no player line) that converse_tier1 will reuse. Ollama's
    single-slot cache then holds that prefix, and the real turn re-evaluates only
    the short varying tail (the query-relevant memories + the player's line) on
    top of it - measured ~3.4s of prompt-eval shifted off the player's wait.

    The win depends on the warmed user block being a true STRING PREFIX of the
    real turn's user message; build_situation_block(include_memories=False) and
    converse_tier1 share _warm_user_block to guarantee that. The world is frozen
    while a dialogue window is open, so mood/disposition/rumors do not drift
    between the warm and the send. Serializes on the same _llm_lock as every
    other call. Returns True if the call reached the model.
    """
    raw = _call_llm(
        system=build_character_prompt(npc),
        user=_warm_user_block(npc, player_name, rumor_texts),
        json_format=False,
        num_predict=1,
        temperature=0.0,
        history=_history_messages(npc),
        schema=None,
    )
    return raw is not None


def _converse_tier1_plain(
    npc: dict[str, Any],
    player_name: str,
    player_text: str,
    rumor_texts: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Day 8 plain-text path: the model speaks, the backend computes the rest.

    The call is retried once (cheap - the prompt prefix is warm) when the model
    parrots its previous line; the retry carries an anti-repeat nudge and a
    higher temperature. If the retry parrots too, the first line is kept - a
    repeated in-character line still beats a canned stub. The sentiment delta is
    scored from the PLAYER's message, the mood drifts from it, and a memory is
    recorded only when the exchange is significant.
    """
    system = build_character_prompt(npc)
    history = _history_messages(npc)
    # Day 8 (RAG): retrieve the few memories relevant to what the player just
    # said, out of the now-deep store, instead of injecting the latest few.
    recalled = recall.recall_relevant(npc.get("memory_buffer", []), player_text, k=3)
    # Restate the player's CURRENT message as the very last thing the model
    # reads, and tell it not to answer an earlier turn - small models otherwise
    # carry conversational momentum and reply to the previous question.
    base_user = (
        build_situation_block(npc, player_name, rumor_texts, recalled_memories=recalled)
        + f'\n{player_name} just said to you: "{player_text}"\n'
        + f'Reply directly to that latest message ("{player_text}"), NOT to '
        + "anything said earlier. Answer now in 1-2 short, plain sentences."
    )
    current_mood = npc.get("current_mood", "neutral")
    stored_history = npc.get("conversation_history") or []
    previous_reply = stored_history[-1].get("npc_response", "") if stored_history else ""

    reply: Optional[str] = None
    nudge = ""
    for attempt in range(2):
        raw = _call_llm(
            system=system,
            user=base_user + nudge,
            json_format=False,
            num_predict=CONVERSE_REPLY_NUM_PREDICT,
            temperature=0.8 if attempt == 0 else 0.95,
            history=history,
            schema=None,
        )
        if raw is None:
            break
        candidate = _clean_plain_reply(raw, current_mood)
        if not _is_parrot(candidate, previous_reply):
            reply = candidate
            break
        if reply is None:
            reply = candidate  # first line, kept in case the retry parrots too
        nudge = _ANTI_REPEAT_NUDGE
    if reply is None:
        result = stub_converse(npc)
        result["used_llm"] = False
        return result

    sentiment_delta = sentiment.score_sentiment(player_text)
    mood = derive_post_exchange_mood(current_mood, sentiment_delta)
    memory = build_conversation_memory(player_name, player_text, sentiment_delta)
    return {
        "reply": reply,
        "mood": mood,
        "sentiment_delta": sentiment_delta,
        "memory": memory,
        "used_llm": True,
    }


def _converse_tier1_structured(
    npc: dict[str, Any],
    player_name: str,
    player_text: str,
    rumor_texts: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Legacy Day 5-7 path: one schema-constrained JSON call carries the reply
    plus the card delta. Retried once when the model drops "reply" or parrots;
    the first attempt's delta is reused if the retry misbehaves too.
    """
    system = build_character_prompt(npc)
    history = _history_messages(npc)
    recalled = recall.recall_relevant(npc.get("memory_buffer", []), player_text, k=3)
    base_user = (
        build_situation_block(npc, player_name, rumor_texts, recalled_memories=recalled)
        + f'\n{player_name} just said to you: "{player_text}"\n'
        + f'Reply directly to that latest message ("{player_text}"), NOT to '
        + 'anything said earlier. Respond now with the JSON object, "reply" first.'
    )
    current_mood = npc.get("current_mood", "neutral")
    stored_history = npc.get("conversation_history") or []
    previous_reply = stored_history[-1].get("npc_response", "") if stored_history else ""

    fallback: Optional[dict[str, Any]] = None
    nudge = ""
    for attempt in range(2):
        raw = _call_llm(
            system=system,
            user=base_user + nudge,
            json_format=True,
            num_predict=CONVERSE_NUM_PREDICT,
            temperature=0.8 if attempt == 0 else 0.95,
            history=history,
            schema=CARD_DELTA_SCHEMA,
        )
        if raw is None:
            break
        delta = parse_card_delta(raw, current_mood)
        genuine = delta.pop("reply_was_genuine", True)
        if genuine and not _is_parrot(delta["reply"], previous_reply):
            delta["used_llm"] = True
            return delta
        if fallback is None:
            fallback = delta
        nudge = _ANTI_REPEAT_NUDGE
    if fallback is not None:
        fallback["used_llm"] = True
        return fallback
    result = stub_converse(npc)
    result["used_llm"] = False
    return result


# --------------------------------------------------------------------------- #
# Day 8 plain-text reply cleanup + computed side-channel (mood / memory)
# --------------------------------------------------------------------------- #
def _clean_plain_reply(raw: str, current_mood: str) -> str:
    """Reduce raw model output to a bare spoken line.

    The model is asked for plain prose, but a small model sometimes still wraps
    it in a JSON envelope or quotes. Strip <think> blocks, any stray JSON,
    wrapping quotes, and a leading "Day N:" stamp. Falls back to a safe
    in-character line if nothing speakable survives (never returns empty).
    """
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if text.startswith("{") or text.startswith("["):
        data = _extract_json(text)
        extracted = ""
        if isinstance(data, dict):
            for key in ("reply", "response", "text", "say", "speech", "dialogue", "answer"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    extracted = value.strip()
                    break
        text = extracted or _fallback_reply(raw)
    text = text.strip().strip('"').strip("'").strip()
    text = re.sub(r"^\s*Day\s+\d+:\s*", "", text)
    if not text or _looks_like_json_guts(text):
        text = _safe_line(current_mood)
    return text[:REPLY_MAX_CHARS].strip()


def derive_post_exchange_mood(current_mood: str, sentiment_delta: int) -> str:
    """Drift the NPC's mood from the exchange's sentiment - no model needed.

    Shifts the current mood's valence along behavior.MOOD_VALENCE by the
    sentiment delta, then snaps to the nearest EMITTABLE mood: a strong negative
    delta drifts toward suspicious/angry, a positive one toward content/happy,
    a near-zero delta holds. RESERVED_MOODS (grieving, fearful) are kept for
    scripted story beats and are never emitted here.
    """
    emittable = {m: v for m, v in behavior.MOOD_VALENCE.items() if m not in RESERVED_MOODS}
    current_v = behavior.MOOD_VALENCE.get(current_mood, 0.5)
    target = current_v + (sentiment_delta / SENTIMENT_DELTA_LIMIT) * MOOD_DRIFT_SPAN
    target = max(0.0, min(1.0, target))
    # Nearest emittable mood by valence; ties hold the current mood (when itself
    # emittable) so a near-zero drift never flips between equally close moods.
    return min(
        emittable,
        key=lambda m: (abs(emittable[m] - target), 0 if m == current_mood else 1),
    )


# Common words stripped before building a memory's topic, so the keyworded line
# carries the salient nouns the player actually raised (what TF-IDF recall matches).
_MEMORY_STOPWORDS = {
    "about", "after", "again", "could", "does", "doing", "have", "just", "know",
    "like", "more", "much", "some", "tell", "than", "that", "them", "then",
    "there", "they", "this", "want", "were", "what", "when", "where", "which",
    "will", "with", "would", "your", "youre", "from", "into", "over", "very",
    "been", "here", "need", "make", "made", "said", "should", "because",
    "really", "still", "going", "thing", "things", "around", "yourself",
}

# Charged topics that make an exchange worth remembering even when the player's
# tone stayed level (a calm question about a murder is still significant).
_TOPIC_TRIGGERS = {
    "murder", "murdered", "death", "dead", "kill", "killed", "demon", "cult",
    "cultist", "blood", "plague", "flood", "fire", "war", "raid", "ghost",
    "curse", "betray", "betrayal", "magistrate", "ashen", "treasure", "secret",
    "witch", "poison", "stolen", "theft", "missing",
}


def build_conversation_memory(player_name: str, player_text: str, sentiment_delta: int) -> str:
    """A significance-gated, keyworded memory line - or "" for trivial chatter.

    Records only when the exchange matters: |sentiment_delta| crosses
    MEMORY_SIGNIFICANCE_THRESHOLD, or the player named a charged topic. Templates
    a line from the message's salient words so Day 8's TF-IDF recall has real
    keywords to match later. The returned line carries NO "Day N:" stamp - the
    caller (main._apply_conversation_delta) adds it. Seeds the Witness Memory
    Tagger; trivial small-talk records nothing, keeping the deep buffer clean.
    """
    tokens = re.findall(r"[a-z']+", player_text.lower())
    salient: list[str] = []
    for token in tokens:
        word = token.strip("'")
        if len(word) >= 4 and word not in _MEMORY_STOPWORDS and word not in salient:
            salient.append(word)
    triggered = any(token in _TOPIC_TRIGGERS for token in tokens)
    significant = abs(sentiment_delta) >= MEMORY_SIGNIFICANCE_THRESHOLD or triggered
    if not significant or not salient:
        return ""
    topic = " ".join(salient[:3])
    if sentiment_delta <= -MEMORY_SIGNIFICANCE_THRESHOLD:
        verb = "pressed me about"
    elif sentiment_delta >= MEMORY_SIGNIFICANCE_THRESHOLD:
        verb = "spoke warmly with me about"
    else:
        verb = "asked me about"
    return f"{player_name} {verb} {topic}"


# --------------------------------------------------------------------------- #
# Tier 2/3 stub replies (and Tier 1 outage fallback)
# --------------------------------------------------------------------------- #
_STUB_BY_MOOD = {
    "happy": ["Fine day, isn't it?", "Good to see a friendly face."],
    "content": ["Can't complain. The work keeps me honest.", "All's well enough here."],
    "neutral": ["Hm? Oh - good day to you.", "Aye, what is it?"],
    "anxious": ["Not now, I've much on my mind.", "Strange days. Keep your eyes open."],
    "angry": ["Leave me be.", "I've no patience for chatter today."],
    "fearful": ["Did you hear that? ...Never mind. Stay safe.", "Keep your voice down."],
    "grieving": ["Forgive me, I'm poor company of late.", "Another time, friend."],
    "suspicious": ["And why would you be asking?", "I don't know you well enough for that."],
}

_STUB_BY_OCCUPATION = {
    "merchant": "Buying or selling? Otherwise I've ledgers to balance.",
    "trader": "Roads are rough this season - drives the prices up, you know.",
    "guard": "Move along. Nothing to see here.",
    "farmer": "Crops won't tend themselves. Was there something?",
    "fisherman": "River's been generous this week, praise be.",
    "priest": "The Ashen Light keep you, traveler.",
    "beggar": "Spare a coin for an honest wretch?",
    "child": "Are you the one everyone's been whispering about?",
}


def stub_converse(npc: dict[str, Any]) -> dict[str, Any]:
    """Rule-based reply for Tier 2/3 NPCs - no LLM, no mood change."""
    mood = npc.get("current_mood", "neutral")
    options = list(_STUB_BY_MOOD.get(mood, _STUB_BY_MOOD["neutral"]))
    occupation_line = _STUB_BY_OCCUPATION.get(npc.get("occupation", ""))
    if occupation_line:
        options.append(occupation_line)
    return {
        "reply": _stub_rng.choice(options),
        "mood": mood,
        "sentiment_delta": 0,
        "memory": "",
        "used_llm": False,
    }


# --------------------------------------------------------------------------- #
# Tier 1 card generation (one-off enrichment)
# --------------------------------------------------------------------------- #
CARD_FIELDS = ("appearance", "dark_trait", "redeeming_quality", "trauma", "conversation_style")
CARD_FIELD_MAX_CHARS = 220

# Schema-constrained shape for the one-off enrichment pass: every flavor field
# present and a string (empty/short ones are still filtered/truncated below).
CARD_DETAILS_SCHEMA = {
    "type": "object",
    "properties": {field: {"type": "string"} for field in CARD_FIELDS},
    "required": list(CARD_FIELDS),
}


def build_card_prompt(npc: dict[str, Any]) -> str:
    traits = ", ".join(npc.get("personality_traits", [])) or "unremarkable"
    faction = ""
    affiliations = npc.get("faction_affiliations", [])
    if affiliations:
        faction = affiliations[0].get("faction_name", "")
    return (
        "You are inventing the inner life of a character in a grim medieval "
        "river town called Aldenmoor.\n"
        f"Name: {npc.get('name', 'Unknown')}. Age: {npc.get('age', 30)}. "
        f"Occupation: {npc.get('occupation', 'villager')}. "
        f"Personality traits: {traits}."
        + (f" Faction: {faction}." if faction else "")
        + "\nSeed ideas you may sharpen or replace: "
        f"dark trait '{npc.get('dark_trait', '')}', "
        f"redeeming quality '{npc.get('redeeming_quality', '')}', "
        f"trauma '{npc.get('trauma', '')}'.\n"
        "Write each field as one vivid, specific phrase or short sentence. "
        "Respond ONLY with one JSON object: "
        '{"appearance": "...", "dark_trait": "...", "redeeming_quality": "...", '
        '"trauma": "...", "conversation_style": "..."}'
    )


def generate_card_details(npc: dict[str, Any]) -> Optional[dict[str, str]]:
    """Ask the LLM to flesh out a Tier 1 card. Returns clean fields or None.

    Only non-empty string fields survive, truncated; the caller persists them
    under the simulation lock and marks the card enriched.
    """
    raw = _call_llm(
        system=build_card_prompt(npc),
        user="Invent this character now.",
        json_format=True,
        num_predict=CARD_GEN_NUM_PREDICT,
        temperature=0.9,
        schema=CARD_DETAILS_SCHEMA,
    )
    if raw is None:
        return None
    data = _extract_json(raw)
    if data is None:
        return None
    details = {}
    for field in CARD_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            details[field] = value.strip()[:CARD_FIELD_MAX_CHARS]
    return details or None
