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

import hashlib
import logging
import os
import xml.sax.saxutils as saxutils
from pathlib import Path
from typing import Any, Optional

try:  # pragma: no cover - missing lib just means voice stays unavailable
    import requests

    _REQUESTS_IMPORTED = True
except Exception:  # noqa: BLE001
    requests = None  # type: ignore[assignment]
    _REQUESTS_IMPORTED = False


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


def voice_available() -> bool:
    """True only when the requests lib is importable and both creds are present.

    Never raises and never touches the network - it just gates the feature, so
    the render payload and the endpoint can report availability cheaply.
    """
    endpoint, key = _tts_config()
    return bool(_REQUESTS_IMPORTED and endpoint and key)


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
    """Return mp3 bytes for an NPC line, or None on any failure (never raises).

    Order of operations:
      1. Bail to None if voice is unavailable or the text is empty.
      2. Serve from the disk cache when this exact (voice, prosody, text) was
         synthesized before - no second HTTP hit, no second charge.
      3. Otherwise POST the SSML to Azure Speech with the documented headers,
         cache the bytes, and return them.

    The subscription key is sent in the request header only; it is never logged.
    Any transport/HTTP/parse failure is logged by class via the chronicle.voice
    logger and swallowed into a None return so the caller falls back silently.
    """
    if not voice_available():
        return None
    text = str(text or "").strip()
    if not text:
        return None

    voice = select_voice(npc)
    prosody = select_prosody(npc)
    cache_path = _cache_path(voice, prosody, text)
    cached = _read_cache(cache_path)
    if cached is not None:
        return cached

    endpoint, key = _tts_config()
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
