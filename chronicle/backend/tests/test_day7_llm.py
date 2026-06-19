"""LLM schema routing + Tier-1 card enrichment.

Verifies that _call_llm routes a JSON Schema to Ollama's format= (and falls back
correctly without one), and that the one remaining JSON consumer - the card
enrichment pass (generate_card_details) - forwards its schema. Conversation turns
are plain text since Day 8; their output cleanup lives in test_day8_conversation.
No real Ollama server: the client / _call_llm boundary is faked.
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
# Card enrichment forwards its schema
# --------------------------------------------------------------------------- #
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
