"""NPC voice system (Day 9): Azure Speech text-to-speech, backend-mediated.

One job: turn an NPC's spoken reply into mp3 audio the frontend can play. It
mirrors the Azure-LLM pattern in ``systems.conversation`` exactly:

* Credentials (TTS_ENDPOINT + TTS_KEY) are read from the environment AT CALL
  TIME, never at import time, so a ``.env`` loaded late (as ``main.lifespan``
  does) is always picked up. ``voice_available()`` is True only when both are
  present.
* The key never leaves the server: this module POSTs to Azure, returns raw mp3
  bytes, and ``main.py`` base64-wraps them for the frontend. The key is never
  logged (a dedicated ``chronicle.voice`` logger records failures by class, not
  content) and never appears on the render payload.
* Graceful degradation everywhere: no creds, a failed HTTP call, an import-less
  environment - every path returns ``None`` and logs a warning. ``synthesize``
  NEVER raises, so a TTS outage can never crash or block a conversation.

VOICE SELECTION is deterministic per NPC: a stable hash of ``npc_id`` picks a
voice from a curated en-GB neural pool (so the same villager always sounds the
same across a session/restart), gendered by a light name/occupation heuristic,
then nudged by age and current mood via SSML ``<prosody>``. The Demon Lord gets
a fixed deep voice regardless of hash.

Results are DISK-CACHED by (voice, prosody, sha1(text)) under
``backend/data/tts_cache/`` so replays and demos never re-pay or re-wait on a
line that was already synthesized. The cache dir is gitignored.

This module is a pure TTS client + voice policy + cache. It never touches the
database and never blocks the event loop: ``main.py`` calls ``synthesize`` via
``asyncio.to_thread`` exactly like the conversation endpoint.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import struct
import xml.sax.saxutils as saxutils
from pathlib import Path
from typing import Any, Optional

try:  # pragma: no cover - missing lib just means the Speech REST path is off
    import requests

    _REQUESTS_IMPORTED = True
except Exception:  # noqa: BLE001
    requests = None  # type: ignore[assignment]
    _REQUESTS_IMPORTED = False

try:  # pragma: no cover - missing lib just means the realtime path is off
    import websockets

    _WEBSOCKETS_IMPORTED = True
except Exception:  # noqa: BLE001
    websockets = None  # type: ignore[assignment]
    _WEBSOCKETS_IMPORTED = False


logger = logging.getLogger("chronicle.voice")

# Azure Speech mp3 profile + request framing. The output format header asks for
# a compact mono mp3 that streams quickly to the browser; the user-agent is
# required by some Azure Speech regions.
_OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
_USER_AGENT = "ChronicleOfTheVelvetLies/1.0"
_HTTP_TIMEOUT_SECONDS = 20.0

# Disk cache: backend/data/tts_cache/ (sibling of the sqlite db). Gitignored.
_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "tts_cache"

# Curated en-GB neural voice pools. Kept small and hand-picked so every NPC
# sounds like a plausible townsperson; the deterministic hash spreads NPCs
# across the pool so a crowd does not all share one voice.
MALE_VOICES = [
    "en-GB-RyanNeural",
    "en-GB-ThomasNeural",
    "en-GB-AlfieNeural",
    "en-GB-ElliotNeural",
    "en-GB-NoahNeural",
]
FEMALE_VOICES = [
    "en-GB-SoniaNeural",
    "en-GB-LibbyNeural",
    "en-GB-MaisieNeural",
    "en-GB-AbbiNeural",
    "en-GB-BellaNeural",
]

# The Demon Lord always speaks with this fixed deep voice, regardless of hash.
DEMON_LORD_VOICE = "en-GB-RyanNeural"
DEMON_LORD_PROSODY = {"pitch": "-25%", "rate": "-8%"}

# Light gender heuristic for voice-pool selection. The cards carry no explicit
# gender field, so a few common female-coded name endings and occupations tip an
# NPC toward the female pool; everyone else uses the male pool. This only steers
# which curated pool the deterministic hash indexes into - it is flavour, not
# identity, and never blocks synthesis.
_FEMALE_NAME_HINTS = ("a", "e", "ia", "ina", "elle", "wyn", "lyn")
_FEMALE_OCCUPATION_HINTS = {"herbalist", "midwife", "seamstress", "washerwoman"}


def _tts_config() -> tuple[Optional[str], Optional[str]]:
    """Read TTS creds from the environment at CALL time (not import time), so a
    .env loaded after import - or changed between runs - is always picked up."""
    return (
        os.environ.get("TTS_ENDPOINT"),
        os.environ.get("TTS_KEY"),
    )


def _is_realtime_endpoint(endpoint: Optional[str]) -> bool:
    """True for an Azure OpenAI *Realtime* endpoint (e.g.
    .../openai/v1/realtime?model=gpt-realtime-2) as opposed to an Azure Speech
    TTS REST endpoint (.../cognitiveservices/v1). They use entirely different
    transports - a WebSocket vs an SSML HTTP POST - so synthesize() dispatches
    on this."""
    if not endpoint:
        return False
    return "/realtime" in endpoint.split("?", 1)[0]


def voice_available() -> bool:
    """True only when both creds are present AND the transport the configured
    endpoint needs is importable: ``websockets`` for a Realtime endpoint,
    ``requests`` for a Speech REST endpoint.

    Never raises and never touches the network - it just gates the feature, so
    the render payload and the endpoint can report availability cheaply.
    """
    endpoint, key = _tts_config()
    if not (endpoint and key):
        return False
    if _is_realtime_endpoint(endpoint):
        return _WEBSOCKETS_IMPORTED
    return _REQUESTS_IMPORTED


def audio_format() -> str:
    """The container the configured endpoint produces: Realtime streams raw PCM
    we wrap as ``wav``; Azure Speech returns ``mp3``. main.py stamps this onto
    the /api/voice response so the frontend decodes with the right format."""
    endpoint, _ = _tts_config()
    return "wav" if _is_realtime_endpoint(endpoint) else "mp3"


def _stable_hash(value: str) -> int:
    """Deterministic, cross-run-stable hash (Python's hash() is salted per
    process, which would make a villager's voice change every restart)."""
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _looks_female(npc: dict[str, Any]) -> bool:
    name = str(npc.get("name", "")).strip().lower()
    first = name.split()[0] if name else ""
    if str(npc.get("occupation", "")).lower() in _FEMALE_OCCUPATION_HINTS:
        return True
    return first.endswith(_FEMALE_NAME_HINTS)


def select_voice(npc: dict[str, Any]) -> str:
    """Deterministically map an NPC to a curated en-GB neural voice.

    The Demon Lord is fixed. Everyone else is hashed by id into the gendered
    pool, so the same NPC always gets the same voice within and across runs.
    """
    if npc.get("is_demon_lord"):
        return DEMON_LORD_VOICE
    npc_id = str(npc.get("id", npc.get("name", "")))
    pool = FEMALE_VOICES if _looks_female(npc) else MALE_VOICES
    return pool[_stable_hash(npc_id) % len(pool)]


def select_prosody(npc: dict[str, Any]) -> dict[str, str]:
    """Pitch/rate nudges from age and current mood (SSML <prosody> values).

    The Demon Lord uses a fixed deep, slow profile. For everyone else, elders
    speak lower and slower, and the current mood tilts pitch/rate a little
    (angry = a touch higher/faster, grieving = lower/slower, and so on) so the
    voice tracks how they feel without ever sounding cartoonish.
    """
    if npc.get("is_demon_lord"):
        return dict(DEMON_LORD_PROSODY)

    pitch = 0  # percent
    rate = 0  # percent

    age = int(npc.get("age", 30) or 30)
    if age >= 60:
        pitch -= 8
        rate -= 6
    elif age >= 45:
        pitch -= 4
        rate -= 3
    elif age <= 16:
        pitch += 8
        rate += 3

    mood = str(npc.get("current_mood", "neutral")).lower()
    mood_shift = {
        "angry": (4, 4),
        "happy": (3, 2),
        "anxious": (3, 5),
        "fearful": (5, 6),
        "suspicious": (-2, -2),
        "grieving": (-6, -6),
        "content": (0, 0),
        "neutral": (0, 0),
    }.get(mood, (0, 0))
    pitch += mood_shift[0]
    rate += mood_shift[1]

    return {"pitch": f"{pitch:+d}%", "rate": f"{rate:+d}%"}


def build_ssml(text: str, npc: dict[str, Any]) -> str:
    """Build a well-formed SSML document for one NPC line.

    The spoken text is XML-escaped (a stray ``&`` or ``<`` in an NPC reply would
    otherwise produce invalid SSML and a failed call). Returns a single
    ``<speak>`` with a ``<voice>`` and a ``<prosody>`` wrapping the escaped text.
    """
    voice = select_voice(npc)
    prosody = select_prosody(npc)
    safe_text = saxutils.escape(str(text).strip())
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xml:lang="en-GB">'
        f'<voice name="{voice}">'
        f'<prosody pitch="{prosody["pitch"]}" rate="{prosody["rate"]}">'
        f"{safe_text}"
        "</prosody></voice></speak>"
    )


def _cache_key(voice: str, prosody: dict[str, str], text: str) -> str:
    """Stable filename stem for a (voice, prosody, text) triple."""
    basis = f"{voice}|{prosody.get('pitch','')}|{prosody.get('rate','')}|{text}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _cache_path(voice: str, prosody: dict[str, str], text: str) -> Path:
    return _CACHE_DIR / f"{_cache_key(voice, prosody, text)}.mp3"


def _read_cache(path: Path) -> Optional[bytes]:
    try:
        if path.is_file():
            return path.read_bytes()
    except OSError:  # noqa: BLE001 - a cache miss must never fail a synth
        return None
    return None


def _write_cache(path: Path, audio: bytes) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
    except OSError as exc:  # noqa: BLE001 - cache write best-effort only
        logger.warning("TTS cache write failed: %r", exc)


def synthesize(text: str, npc: dict[str, Any]) -> Optional[bytes]:
    """Return audio bytes for an NPC line, or None on any failure (never raises).

    Dispatches on the configured endpoint: a Realtime endpoint drives the
    gpt-realtime model as a TTS engine over a WebSocket (returns WAV); a Speech
    endpoint POSTs SSML (returns mp3). Either way the result is disk-cached, the
    key is never logged, and any failure is swallowed into None so the caller
    falls back silently.
    """
    if not voice_available():
        return None
    text = str(text or "").strip()
    if not text:
        return None

    endpoint, key = _tts_config()
    if _is_realtime_endpoint(endpoint):
        return _synthesize_realtime(endpoint, key, text, npc)
    return _synthesize_speech(endpoint, key, text, npc)


def _synthesize_speech(endpoint: str, key: str, text: str, npc: dict[str, Any]) -> Optional[bytes]:
    """Azure Speech REST path: cache, else POST SSML, cache, return mp3 bytes."""
    voice = select_voice(npc)
    prosody = select_prosody(npc)
    cache_path = _cache_path(voice, prosody, text)
    cached = _read_cache(cache_path)
    if cached is not None:
        return cached

    ssml = build_ssml(text, npc)
    try:
        response = requests.post(
            endpoint,
            data=ssml.encode("utf-8"),
            headers={
                "Ocp-Apim-Subscription-Key": key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": _OUTPUT_FORMAT,
                "User-Agent": _USER_AGENT,
            },
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        audio = response.content
        if not audio:
            logger.warning("TTS returned empty audio for voice %s", voice)
            return None
    except Exception as exc:  # noqa: BLE001 - any failure -> silent fallback
        # Log the failure CLASS, never the key or full request.
        logger.warning("TTS synthesis failed (voice=%s): %r", voice, exc)
        return None

    _write_cache(cache_path, audio)
    return audio


# --------------------------------------------------------------------------- #
# Azure OpenAI Realtime path (drive gpt-realtime as a TTS engine over a WS)
# --------------------------------------------------------------------------- #
# The realtime model exposes a fixed set of voices (not the en-GB neural pool);
# SSML prosody isn't available, so age/mood are folded into the spoken
# instructions instead. Voices per the GA gpt-realtime catalogue.
REALTIME_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"]
REALTIME_DEMON_VOICE = "ash"  # the deepest/grittiest of the set
_REALTIME_SAMPLE_RATE = 24000  # gpt-realtime streams 24kHz mono PCM16
_REALTIME_TIMEOUT_SECONDS = 30.0


def _realtime_voice(npc: dict[str, Any]) -> str:
    """Deterministic per-NPC realtime voice (Demon Lord fixed), same sha1 scheme
    as select_voice so a villager keeps one voice across runs."""
    if npc.get("is_demon_lord"):
        return REALTIME_DEMON_VOICE
    npc_id = str(npc.get("id", npc.get("name", "")))
    return REALTIME_VOICES[_stable_hash(npc_id) % len(REALTIME_VOICES)]


def _realtime_instructions(npc: dict[str, Any]) -> str:
    """System instructions that turn the chat-native realtime model into a
    verbatim TTS reader, with age/mood folded in (no SSML available here)."""
    parts = [
        "You are the speaking voice of a single fantasy-village character.",
        "Read the user's message ALOUD, word for word, as that character's spoken line.",
        "Do NOT answer it, react to it, translate it, or add or drop any words -",
        "speak only the exact text you are given, then stop.",
    ]
    age = int(npc.get("age", 30) or 30)
    if npc.get("is_demon_lord"):
        parts.append("Voice: deep, slow, and menacing.")
    elif age >= 60:
        parts.append("Voice: an older person - lower and slower.")
    elif age <= 16:
        parts.append("Voice: a young person - lighter and a little quicker.")
    mood_tone = {
        "angry": "angry and clipped",
        "happy": "warm and cheerful",
        "anxious": "nervous and hurried",
        "fearful": "frightened and hushed",
        "suspicious": "wary and guarded",
        "grieving": "sorrowful and subdued",
    }.get(str(npc.get("current_mood", "neutral")).lower())
    if mood_tone:
        parts.append(f"Tone: {mood_tone}.")
    return " ".join(parts)


def _pcm16_to_wav(pcm: bytes, sample_rate: int = _REALTIME_SAMPLE_RATE, channels: int = 1) -> bytes:
    """Wrap raw little-endian PCM16 mono samples in a minimal 44-byte WAV header
    so the browser can play the realtime model's audio without transcoding."""
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    data_len = len(pcm)
    header = b"RIFF" + struct.pack("<I", 36 + data_len) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, 16)
    header += b"data" + struct.pack("<I", data_len)
    return header + pcm


def _realtime_cache_path(voice: str, instructions: str, text: str) -> Path:
    """Cache realtime audio by (voice, instructions, text) - instructions carry
    the age/mood flavour, so two moods of the same line cache separately."""
    return _cache_path(voice, {"pitch": "rt", "rate": str(_stable_hash(instructions))}, text)


def _synthesize_realtime(endpoint: str, key: str, text: str, npc: dict[str, Any]) -> Optional[bytes]:
    """Realtime TTS path: cache, else run the WS synthesis, cache, return WAV."""
    voice = _realtime_voice(npc)
    instructions = _realtime_instructions(npc)
    cache_path = _realtime_cache_path(voice, instructions, text)
    cached = _read_cache(cache_path)
    if cached is not None:
        return cached
    try:
        audio = asyncio.run(
            asyncio.wait_for(
                _realtime_collect(endpoint, key, text, voice, instructions),
                timeout=_REALTIME_TIMEOUT_SECONDS,
            )
        )
    except Exception as exc:  # noqa: BLE001 - any failure -> silent fallback
        logger.warning("Realtime TTS failed (voice=%s): %r", voice, exc)
        return None
    if not audio:
        return None
    _write_cache(cache_path, audio)
    return audio


async def _realtime_collect(
    endpoint: str, key: str, text: str, voice: str, instructions: str
) -> Optional[bytes]:
    """Open the realtime WebSocket, ask the model to speak ``text`` in ``voice``,
    and concatenate the streamed PCM16 audio into a WAV. Returns None on no audio.

    Targets the GA gpt-realtime event schema; audio collection is tolerant of
    both the GA (`response.output_audio.delta`) and beta (`response.audio.delta`)
    delta event names. An ``error`` event from the server is logged (message
    only, never the key) and ends the stream - that message is the first thing to
    check if your endpoint's schema differs.
    """
    ws_url = "wss://" + endpoint.split("://", 1)[1]  # https->wss, keep path+query
    pcm = bytearray()
    async with websockets.connect(
        ws_url, additional_headers={"api-key": key}, max_size=None
    ) as ws:
        # Configure the session as an audio-out TTS reader (GA schema).
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": instructions,
                "output_modalities": ["audio"],
                "audio": {
                    "output": {
                        "voice": voice,
                        "format": {"type": "audio/pcm", "rate": _REALTIME_SAMPLE_RATE},
                    }
                },
            },
        }))
        # Hand it the exact line, then ask for one spoken response.
        await ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        }))
        await ws.send(json.dumps({"type": "response.create"}))

        async for raw in ws:
            try:
                evt = json.loads(raw)
            except (ValueError, TypeError):
                continue
            etype = str(evt.get("type", ""))
            if etype.endswith("audio.delta") and evt.get("delta"):
                try:
                    pcm += base64.b64decode(evt["delta"])
                except (ValueError, TypeError):
                    continue
            elif etype == "error":
                message = ""
                if isinstance(evt.get("error"), dict):
                    message = str(evt["error"].get("message", ""))
                logger.warning("Realtime TTS server error: %s", message or "(no message)")
                break
            elif etype in ("response.done", "response.completed", "response.output_audio.done"):
                break
    if not pcm:
        return None
    return _pcm16_to_wav(bytes(pcm))
