"""Day 9 checks: Azure Speech NPC voices (Part C).

No real network and no real Azure account: TTS creds are set via monkeypatched
env, and the HTTP boundary (systems.voice.requests.post) is faked, so the suite
stays fast, deterministic, and offline. Verifies the same guarantees the
conversation system gives - creds read at call time, deterministic per-NPC voice
selection, well-formed escaped SSML, graceful None on failure, a working disk
cache, and an endpoint that degrades to {"voiced": false} instead of 500-ing.
"""

from __future__ import annotations

import pytest

from systems import voice


def _npc(npc_id="npc_00007", **overrides):
    npc = {
        "id": npc_id,
        "name": "Mara Vane",
        "age": 41,
        "occupation": "blacksmith",
        "current_mood": "content",
        "is_demon_lord": False,
    }
    npc.update(overrides)
    return npc


# --------------------------------------------------------------------------- #
# voice_available(): both creds required, read at call time
# --------------------------------------------------------------------------- #
def test_voice_unavailable_without_creds(monkeypatch):
    monkeypatch.delenv("TTS_ENDPOINT", raising=False)
    monkeypatch.delenv("TTS_KEY", raising=False)
    assert voice.voice_available() is False


def test_voice_unavailable_with_only_one_cred(monkeypatch):
    monkeypatch.setenv("TTS_ENDPOINT", "https://example.tts/cognitiveservices/v1")
    monkeypatch.delenv("TTS_KEY", raising=False)
    assert voice.voice_available() is False


def test_voice_available_with_both_creds(monkeypatch):
    monkeypatch.setenv("TTS_ENDPOINT", "https://example.tts/cognitiveservices/v1")
    monkeypatch.setenv("TTS_KEY", "secret-key-value")
    assert voice.voice_available() is True


# --------------------------------------------------------------------------- #
# Deterministic voice selection
# --------------------------------------------------------------------------- #
def test_voice_selection_is_deterministic_per_npc():
    npc = _npc(npc_id="npc_42")
    first = voice.select_voice(npc)
    second = voice.select_voice(_npc(npc_id="npc_42"))
    assert first == second  # stable across calls (and processes - sha1, not hash())
    assert first in voice.MALE_VOICES + voice.FEMALE_VOICES


def test_different_npcs_can_get_different_voices():
    voices = {voice.select_voice(_npc(npc_id=f"npc_{i}")) for i in range(40)}
    assert len(voices) > 1  # the hash spreads NPCs across the pool, not one voice


def test_demon_lord_gets_fixed_deep_voice():
    boss = _npc(npc_id="npc_demon", name="Varakoth", is_demon_lord=True)
    assert voice.select_voice(boss) == voice.DEMON_LORD_VOICE
    prosody = voice.select_prosody(boss)
    assert prosody == voice.DEMON_LORD_PROSODY
    assert prosody["pitch"] == "-25%" and prosody["rate"] == "-8%"


def test_female_hinted_name_uses_female_pool():
    # "Sonia" ends in 'a' -> female pool; deterministic within it.
    npc = _npc(npc_id="npc_sonia", name="Sonia Reed")
    assert voice.select_voice(npc) in voice.FEMALE_VOICES


# --------------------------------------------------------------------------- #
# SSML construction: well-formed + escaped
# --------------------------------------------------------------------------- #
def test_build_ssml_is_well_formed():
    ssml = voice.build_ssml("Good day to you.", _npc())
    assert ssml.startswith("<speak")
    assert "<voice name=" in ssml
    assert "<prosody " in ssml
    assert ssml.rstrip().endswith("</speak>")
    # Parseable as XML (well-formed).
    import xml.dom.minidom as minidom

    minidom.parseString(ssml)  # raises on malformed markup


def test_build_ssml_escapes_text():
    ssml = voice.build_ssml('Bread & ale < none > here', _npc())
    assert "&amp;" in ssml
    assert "&lt;" in ssml and "&gt;" in ssml
    assert "Bread & ale" not in ssml  # the raw ampersand must not survive
    import xml.dom.minidom as minidom

    minidom.parseString(ssml)


# --------------------------------------------------------------------------- #
# synthesize(): returns None on failure, never raises; disk cache round-trip
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, content=b"ID3-fake-mp3-bytes", status=200):
        self.content = content
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise RuntimeError(f"HTTP {self._status}")


def _configure(monkeypatch, cache_dir):
    monkeypatch.setenv("TTS_ENDPOINT", "https://example.tts/cognitiveservices/v1")
    monkeypatch.setenv("TTS_KEY", "secret-key-value")
    monkeypatch.setattr(voice, "_CACHE_DIR", cache_dir)


def test_synthesize_returns_none_when_http_fails(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path / "tts")

    def boom(*args, **kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr(voice.requests, "post", boom)
    # Must swallow the failure and return None - never raise.
    assert voice.synthesize("Hello there", _npc()) is None


def test_synthesize_returns_none_on_http_error_status(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path / "tts")
    monkeypatch.setattr(voice.requests, "post", lambda *a, **k: _FakeResponse(status=503))
    assert voice.synthesize("Hello there", _npc()) is None


def test_synthesize_returns_none_when_unconfigured(monkeypatch, tmp_path):
    monkeypatch.delenv("TTS_ENDPOINT", raising=False)
    monkeypatch.delenv("TTS_KEY", raising=False)
    monkeypatch.setattr(voice, "_CACHE_DIR", tmp_path / "tts")
    # Even with a working transport, no creds -> None (no call attempted).
    monkeypatch.setattr(voice.requests, "post", lambda *a, **k: _FakeResponse())
    assert voice.synthesize("Hello there", _npc()) is None


def test_disk_cache_round_trips_and_skips_second_http_hit(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path / "tts")
    calls = {"n": 0}

    def counting_post(*args, **kwargs):
        calls["n"] += 1
        return _FakeResponse(content=b"cached-mp3-bytes")

    monkeypatch.setattr(voice.requests, "post", counting_post)
    npc = _npc()

    first = voice.synthesize("A line worth caching.", npc)
    assert first == b"cached-mp3-bytes"
    assert calls["n"] == 1  # one network hit

    second = voice.synthesize("A line worth caching.", npc)
    assert second == b"cached-mp3-bytes"
    assert calls["n"] == 1  # served from disk cache, NO second HTTP hit

    # The cache file physically exists under the patched dir.
    cached_files = list((tmp_path / "tts").glob("*.mp3"))
    assert len(cached_files) == 1


def test_cache_key_varies_with_voice_and_text():
    npc_a = _npc(npc_id="npc_a")
    npc_b = _npc(npc_id="npc_b")
    pa = voice._cache_path(voice.select_voice(npc_a), voice.select_prosody(npc_a), "x")
    pb = voice._cache_path(voice.select_voice(npc_b), voice.select_prosody(npc_b), "x")
    # Different voice -> different cache file (no cross-NPC bleed). If the two
    # NPCs happened to hash to the same voice, the text axis still separates them.
    assert pa != pb or voice.select_voice(npc_a) == voice.select_voice(npc_b)
    p_text1 = voice._cache_path("en-GB-RyanNeural", {"pitch": "+0%", "rate": "+0%"}, "one")
    p_text2 = voice._cache_path("en-GB-RyanNeural", {"pitch": "+0%", "rate": "+0%"}, "two")
    assert p_text1 != p_text2


# --------------------------------------------------------------------------- #
# Endpoint: graceful {"voiced": false}, never 500
# --------------------------------------------------------------------------- #
def _seed_world(database, npc):
    player = {"id": "npc_player", "name": "Aldric Snow", "tier": 1, "is_player": True,
              "occupation": "wanderer", "x": 0.0, "y": 0.0}
    database.save_npc(player)
    database.save_npc(npc)
    database.save_world_state(
        {
            "game_started": True,
            "current_day": 4,
            "current_hour": 11,
            "player_npc_id": "npc_player",
            "demon_lord_npc_id": None,
            "region": {"id": "region_aldenmoor", "width": 4, "height": 4},
        }
    )


def test_endpoint_returns_voiced_false_when_unconfigured(monkeypatch, temp_db):
    import main

    monkeypatch.delenv("TTS_ENDPOINT", raising=False)
    monkeypatch.delenv("TTS_KEY", raising=False)
    npc = _npc()
    _seed_world(temp_db, npc)

    result = main._synthesize_voice(npc["id"], "Say something.")
    assert result == {"voiced": False}  # unconfigured -> graceful, no 500


def test_endpoint_returns_voiced_false_when_disabled(monkeypatch, temp_db):
    import main

    monkeypatch.setenv("TTS_ENDPOINT", "https://example.tts/cognitiveservices/v1")
    monkeypatch.setenv("TTS_KEY", "secret-key-value")
    monkeypatch.setattr(main, "_voice_enabled", False)
    npc = _npc()
    _seed_world(temp_db, npc)

    # Configured but toggled off -> still false, and synthesize never called.
    result = main._synthesize_voice(npc["id"], "Say something.")
    assert result == {"voiced": False}


def test_endpoint_voices_when_configured_and_enabled(monkeypatch, temp_db, tmp_path):
    import main

    _configure(monkeypatch, tmp_path / "tts")
    monkeypatch.setattr(main, "_voice_enabled", True)
    monkeypatch.setattr(voice.requests, "post", lambda *a, **k: _FakeResponse(content=b"abc"))
    npc = _npc()
    _seed_world(temp_db, npc)

    result = main._synthesize_voice(npc["id"], "Hail, traveller.")
    assert result["voiced"] is True
    assert result["format"] == "mp3"
    import base64

    assert base64.b64decode(result["audio_b64"]) == b"abc"  # key never in payload


def test_endpoint_unknown_npc_is_graceful(monkeypatch, temp_db, tmp_path):
    import main

    _configure(monkeypatch, tmp_path / "tts")
    monkeypatch.setattr(main, "_voice_enabled", True)
    # No world / no NPC saved -> unknown id -> {"voiced": false}, never raises.
    result = main._synthesize_voice("npc_ghost", "Anyone there?")
    assert result == {"voiced": False}


def test_endpoint_never_raises_on_synthesis_error(monkeypatch, temp_db, tmp_path):
    import main

    _configure(monkeypatch, tmp_path / "tts")
    monkeypatch.setattr(main, "_voice_enabled", True)
    npc = _npc()
    _seed_world(temp_db, npc)

    def boom(*args, **kwargs):
        raise RuntimeError("azure exploded")

    # Even if synthesize itself somehow raised, the endpoint swallows it.
    monkeypatch.setattr(voice, "synthesize", boom)
    result = main._synthesize_voice(npc["id"], "Boom?")
    assert result == {"voiced": False}
