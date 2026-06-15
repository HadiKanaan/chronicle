"""Day 7 — LLM structured-output hardening (schema-constrained card deltas).

Verifies that _call_llm routes a JSON Schema to Ollama's format= (and falls
back correctly without one), and that converse_tier1 / generate_card_details
forward their schemas. No real Ollama server: the client / _call_llm boundary is
faked. parse_card_delta's existing salvage behavior is re-checked here too,
since the schema only makes malformed output rarer, never impossible.
"""

from __future__ import annotations

from systems import conversation


def _tier1_npc(**overrides):
    npc = {
        "id": "npc_00001",
        "tier": 1,
        "name": "Mara Vane",
        "age": 41,
        "occupation": "blacksmith",
        "personality_traits": ["proud", "loyal"],
        "current_mood": "content",
        "player_sentiment": 60,
        "memory_buffer": [],
        "conversation_history": [],
        "rumor_knowledge": [],
        "x": 5.0,
        "y": 5.0,
    }
    npc.update(overrides)
    return npc


class _FakeClient:
    """Captures the kwargs passed to chat() and returns a minimal response."""

    def __init__(self, content="{}"):
        self.captured = {}
        self._content = content

    def chat(self, **kwargs):
        self.captured = kwargs
        return {"message": {"content": self._content}}


# --------------------------------------------------------------------------- #
# _call_llm -> Ollama format= routing
# --------------------------------------------------------------------------- #
def test_call_llm_forwards_schema_to_format(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(conversation, "_get_client", lambda: client)
    schema = {"type": "object", "required": ["reply"]}
    conversation._call_llm(system="s", user="u", schema=schema)
    assert client.captured["format"] == schema  # schema-constrained decoding


def test_call_llm_falls_back_to_json_then_none(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(conversation, "_get_client", lambda: client)
    conversation._call_llm(system="s", user="u", json_format=True)
    assert client.captured["format"] == "json"
    conversation._call_llm(system="s", user="u", json_format=False)
    assert client.captured["format"] is None


# --------------------------------------------------------------------------- #
# The schemas themselves + caller forwarding
# --------------------------------------------------------------------------- #
def test_card_delta_schema_requires_all_fields_and_enumerates_moods():
    schema = conversation.CARD_DELTA_SCHEMA
    assert schema["required"] == ["reply", "mood", "sentiment_delta", "memory"]
    assert schema["properties"]["reply"]["minLength"] == 1
    assert set(schema["properties"]["mood"]["enum"]) == conversation.VALID_MOODS
    assert schema["properties"]["sentiment_delta"]["maximum"] == conversation.SENTIMENT_DELTA_LIMIT


def test_converse_tier1_passes_card_delta_schema(monkeypatch):
    captured = {}

    def fake_call(**kwargs):
        captured.update(kwargs)
        return '{"reply": "Aye.", "mood": "content", "sentiment_delta": 0, "memory": ""}'

    monkeypatch.setattr(conversation, "_call_llm", fake_call)
    conversation.converse_tier1(_tier1_npc(), "Aldric", "Fine blade.")
    assert captured["schema"] is conversation.CARD_DELTA_SCHEMA


def test_generate_card_details_passes_schema(monkeypatch):
    captured = {}

    def fake_call(**kwargs):
        captured.update(kwargs)
        return (
            '{"appearance": "a", "dark_trait": "b", "redeeming_quality": "c",'
            '"trauma": "d", "conversation_style": "e"}'
        )

    monkeypatch.setattr(conversation, "_call_llm", fake_call)
    conversation.generate_card_details(_tier1_npc())
    assert set(captured["schema"]["required"]) == set(conversation.CARD_FIELDS)


# --------------------------------------------------------------------------- #
# Salvage net still stands (schema makes these rarer, not impossible)
# --------------------------------------------------------------------------- #
def test_parse_card_delta_still_salvages_when_schema_is_bypassed():
    # If a malformed payload ever slips through (older model, transport quirk),
    # the existing repair path must still produce a display-safe reply.
    raw = '{"mood": "content", "sentiment_delta": 0, "memory": "answer hid here"}'
    delta = conversation.parse_card_delta(raw, "content")
    assert delta["reply"] == "answer hid here"
    assert delta["reply_was_genuine"] is False
    garbage = conversation.parse_card_delta("not json at all", "angry")
    assert garbage["reply"] and garbage["mood"] == "angry"
