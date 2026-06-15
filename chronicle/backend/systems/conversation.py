"""LLM conversation system (Day 5 / User Story 3).

Talks to a locally running Ollama instance (qwen3:4b) for two jobs:

1. Tier 1 NPC conversations: one chat call returns both the in-character reply
   and a card delta (mood, sentiment shift, a remembered sentence) as JSON.
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
import random
import re
import threading
from typing import Any, Optional

from ml import train as ml
from models.npc import MoodType

try:  # pragma: no cover - exercised by environment, not unit tests
    import ollama

    _OLLAMA_IMPORTED = True
except Exception:  # noqa: BLE001 - missing client just means stub replies
    ollama = None  # type: ignore[assignment]
    _OLLAMA_IMPORTED = False


# The one swappable model decision (see specs research.md decision 4).
MODEL = "qwen3:4b"
OLLAMA_HOST = "http://localhost:11434"
# Keep the model resident permanently (~3.5 GB RAM): an idle unload costs ~18s
# of cold reload on the next conversation, the worst possible first impression.
KEEP_ALIVE = -1
LLM_TIMEOUT_SECONDS = 120.0

# Conversation replies stay short (1-3 sentences) so num_predict can be tight.
# 260, not 220: a 220-token cap was observed live truncating the JSON envelope
# mid-string when the model wrote a long reply plus a long memory.
CONVERSE_NUM_PREDICT = 260
CARD_GEN_NUM_PREDICT = 300

# A reply this similar to the NPC's previous line counts as parroting and
# triggers the anti-repeat retry (qwen3:4b habitually copies its own last
# assistant turn verbatim).
REPEAT_SIMILARITY = 0.9

# Rolling per-NPC conversation transcript kept on the card for prompt context.
HISTORY_CAP = 6
SENTIMENT_DELTA_LIMIT = 10
MEMORY_MAX_CHARS = 200
REPLY_MAX_CHARS = 600

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
    client = _get_client()
    if client is None:
        return None
    response_format = schema if schema is not None else ("json" if json_format else None)
    try:
        with _llm_lock:
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
            "LLM call (schema=%s): prompt_eval=%s tok / %.1fs, gen=%s tok / %.1fs",
            schema is not None,
            getattr(response, "prompt_eval_count", None),
            (getattr(response, "prompt_eval_duration", 0) or 0) / 1e9,
            getattr(response, "eval_count", None),
            (getattr(response, "eval_duration", 0) or 0) / 1e9,
        )
        return response["message"]["content"]
    except Exception as exc:  # noqa: BLE001 - any transport/model failure -> stub path
        # Surfaced on the uvicorn console so silent stub replies are explainable.
        logger.warning("LLM call failed (%s): %r", MODEL, exc)
        return None


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
        "Aldenmoor, a small medieval river town.",
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

    moods = ", ".join(sorted(VALID_MOODS))
    lines.append(
        "Stay in character: speak plainly in a medieval tone, 1-3 short "
        "sentences, and never mention being an AI or a game. "
        "Answer the player's latest words directly; never repeat your earlier "
        "lines word-for-word. "
        "Respond ONLY with one JSON object exactly like this: "
        '{"reply": "<what you say out loud>", '
        f'"mood": "<your mood now, one of: {moods}>", '
        '"sentiment_delta": <integer -10..10, how this exchange shifted your '
        "feeling toward the player>, "
        '"memory": "<one short sentence you will remember, or empty>"} '
        'Always include all four fields. "reply" comes FIRST and must never be '
        "empty or missing - an answer without \"reply\" is thrown away unheard."
    )
    return "\n".join(lines)


def build_situation_block(
    npc: dict[str, Any],
    player_name: str,
    rumor_texts: Optional[list[str]] = None,
) -> str:
    """The volatile half of the prompt: mood, disposition, memories, rumors.

    Rides inside the final user message, AFTER the cached system prompt and
    history, so a mood shift or a fresh memory never invalidates the prefix
    cache. rumor_texts are the actual texts of rumors the NPC knows, resolved
    by the caller - this module never touches the database (Day 6 / US4).
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
    memories = npc.get("memory_buffer", [])[-5:]
    if memories:
        lines.append("Things you remember:")
        lines.extend(f"- {memory}" for memory in memories)
    if rumor_texts:
        lines.append("Rumors you have heard around town (you may bring them up):")
        lines.extend(f"- {text}" for text in rumor_texts)
    return "\n".join(lines)


def _history_messages(npc: dict[str, Any]) -> list[dict[str, str]]:
    """Prior exchanges replayed as native chat turns for the prompt prefix.

    Assistant turns are wrapped back into the {"reply": ...} envelope the
    model must produce - free in-context schooling against its habit of
    dropping the field. The full stored history is used (append-only until
    HISTORY_CAP) rather than a sliding window: a window that slides every
    turn would shift every message and break the prefix cache each time.
    """
    messages: list[dict[str, str]] = []
    for entry in npc.get("conversation_history", [])[-HISTORY_CAP:]:
        player_text = entry.get("player_text", "")
        npc_response = entry.get("npc_response", "")
        if not player_text or not npc_response:
            continue
        messages.append({"role": "user", "content": player_text})
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps({"reply": npc_response}, ensure_ascii=False),
            }
        )
    return messages


def converse_tier1(
    npc: dict[str, Any],
    player_name: str,
    player_text: str,
    rumor_texts: Optional[list[str]] = None,
) -> dict[str, Any]:
    """One LLM conversation turn. Falls back to a stub if Ollama is down.

    Returns {"reply", "mood", "sentiment_delta", "memory", "used_llm"} with
    every field already validated and display-safe. The call is retried once
    (cheap - the prompt prefix is warm in the cache) when the model either
    drops the "reply" field or parrots its previous line verbatim; the retry
    carries an explicit anti-repeat nudge and a higher temperature. If the
    retry misbehaves too, the first attempt's delta is used - a repeated or
    salvaged line still beats a canned stub.

    Prompt shape serves the prefix cache: the static card (system) and stored
    history (chat turns) are byte-identical between turns, so only the small
    situation block and the player's new words cost prompt evaluation.
    """
    system = build_character_prompt(npc)
    history = _history_messages(npc)
    base_user = (
        build_situation_block(npc, player_name, rumor_texts)
        + f"\n{player_name} says: {player_text}\n"
        + 'Answer now with the JSON object - "reply" first.'
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
        nudge = (
            "\nIMPORTANT: do NOT reuse the wording of your previous replies - "
            "say something new that answers these exact words."
        )
    if fallback is not None:
        fallback["used_llm"] = True
        return fallback
    result = stub_converse(npc)
    result["used_llm"] = False
    return result


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
