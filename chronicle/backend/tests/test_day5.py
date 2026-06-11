"""Day 5 (User Story 3) checks: conversation parsing, deltas, and endpoints.

No test here talks to a real Ollama server: the LLM boundary is monkeypatched
so the suite stays fast and deterministic. Live conversation quality is
verified manually against the running backend.
"""

from __future__ import annotations

import pytest

from ml import train as ml
from systems import conversation


# --------------------------------------------------------------------------- #
# Card-delta parsing and repair
# --------------------------------------------------------------------------- #
def test_parse_card_delta_valid_json():
    raw = '{"reply": "Aye, fine day.", "mood": "content", "sentiment_delta": 3, "memory": "met a stranger"}'
    delta = conversation.parse_card_delta(raw, "neutral")
    assert delta == {
        "reply": "Aye, fine day.",
        "mood": "content",
        "sentiment_delta": 3,
        "memory": "met a stranger",
    }


def test_parse_card_delta_repairs_think_tags_and_trailing_comma():
    raw = '<think>reasoning leak</think>{"reply": "Hm.", "mood": "anxious", "sentiment_delta": -2,}'
    delta = conversation.parse_card_delta(raw, "neutral")
    assert delta["reply"] == "Hm."
    assert delta["mood"] == "anxious"
    assert delta["sentiment_delta"] == -2
    assert "reasoning leak" not in delta["reply"]


def test_parse_card_delta_invalid_mood_falls_back_to_ml_model():
    raw = '{"reply": "Bah.", "mood": "bemused", "sentiment_delta": 50}'
    delta = conversation.parse_card_delta(raw, "neutral")
    assert delta["mood"] in conversation.VALID_MOODS
    # Out-of-range delta is clamped, never trusted raw.
    assert delta["sentiment_delta"] == conversation.SENTIMENT_DELTA_LIMIT


def test_parse_card_delta_garbage_is_a_safe_noop():
    delta = conversation.parse_card_delta("not json at all", "angry")
    assert delta["reply"]  # something speakable survives
    assert delta["mood"] == "angry"  # mood untouched
    assert delta["sentiment_delta"] == 0
    assert delta["memory"] == ""


def test_parse_card_delta_salvages_reply_from_broken_envelope():
    raw = '{"reply": "The river took my brother.", "mood": "grie'  # truncated output
    delta = conversation.parse_card_delta(raw, "neutral")
    assert delta["reply"] == "The river took my brother."


def test_parse_card_delta_never_leaks_json_when_reply_field_missing():
    # Observed live with qwen3:4b: the model sometimes drops "reply" entirely.
    raw = '{"mood": "content", "sentiment_delta": 0, "memory": "Fyra showed me a dagger."}'
    delta = conversation.parse_card_delta(raw, "content")
    assert '"mood"' not in delta["reply"]
    assert '"sentiment_delta"' not in delta["reply"]
    assert delta["reply"]  # a safe in-character line instead
    assert delta["memory"] == "Fyra showed me a dagger."


def test_parse_card_delta_never_leaks_json_from_unparseable_fragments():
    raw = '"mood": "content",\n  "sentiment_delta": 0,\n  "memory": "broken"'
    delta = conversation.parse_card_delta(raw, "neutral")
    assert '"sentiment_delta"' not in delta["reply"]
    assert delta["reply"]


def test_predict_conversation_mood_returns_known_label():
    for event_valence in (0.0, 0.5, 1.0):
        mood = ml.predict_conversation_mood(0.5, event_valence)
        assert mood in ml.MOOD_LABELS


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
def _tier1_npc(**overrides):
    npc = {
        "id": "npc_00001",
        "tier": 1,
        "name": "Mara Vane",
        "age": 41,
        "occupation": "blacksmith",
        "personality_traits": ["proud", "loyal"],
        "dark_trait": "resentful of the magistrate",
        "redeeming_quality": "fiercely protects apprentices",
        "trauma": "lost family to the eastern plague",
        "conversation_style": "short, blunt sentences",
        "current_mood": "content",
        "mood_reason": "after an ordinary day",
        "player_sentiment": 62,
        "memory_buffer": ["Day 2: a storm broke over Aldenmoor."],
        "conversation_history": [
            {"day": 3, "hour": 10, "player_text": "Hello.", "npc_response": "Hm. You again."}
        ],
        "rumor_knowledge": [],
        "x": 5.0,
        "y": 5.0,
    }
    npc.update(overrides)
    return npc


def test_conversation_prompt_carries_card_and_memory_context():
    prompt = conversation.build_conversation_prompt(_tier1_npc(), "Aldric Snow")
    assert "Mara Vane" in prompt
    assert "blacksmith" in prompt
    assert "resentful of the magistrate" in prompt
    assert "a storm broke over Aldenmoor" in prompt  # memory buffer surfaced
    assert "Hm. You again." in prompt  # prior exchange surfaced
    assert "Aldric Snow" in prompt
    assert '"sentiment_delta"' in prompt  # card-delta JSON contract requested


def test_converse_tier1_parses_llm_output(monkeypatch):
    raw = '{"reply": "State your business.", "mood": "suspicious", "sentiment_delta": -1, "memory": "a stranger pried"}'
    monkeypatch.setattr(conversation, "_call_llm", lambda **kwargs: raw)
    result = conversation.converse_tier1(_tier1_npc(), "Aldric Snow", "What do you forge?")
    assert result["used_llm"] is True
    assert result["reply"] == "State your business."
    assert result["mood"] == "suspicious"


def test_converse_tier1_falls_back_to_stub_when_llm_down(monkeypatch):
    monkeypatch.setattr(conversation, "_call_llm", lambda **kwargs: None)
    result = conversation.converse_tier1(_tier1_npc(), "Aldric Snow", "Hello?")
    assert result["used_llm"] is False
    assert result["reply"]
    assert result["mood"] == "content"  # stub never shifts mood
    assert result["sentiment_delta"] == 0


def test_stub_converse_shape():
    npc = {"id": "npc_2", "tier": 2, "occupation": "farmer", "current_mood": "anxious"}
    result = conversation.stub_converse(npc)
    assert result["reply"]
    assert result["mood"] == "anxious"
    assert result["sentiment_delta"] == 0
    assert result["used_llm"] is False


# --------------------------------------------------------------------------- #
# Tier 1 card generation
# --------------------------------------------------------------------------- #
def test_generate_card_details_filters_and_truncates(monkeypatch):
    raw = (
        '{"appearance": "  soot-streaked arms, one milky eye  ",'
        '"dark_trait": "' + "x" * 500 + '",'
        '"redeeming_quality": "", "trauma": 42, "conversation_style": "clipped"}'
    )
    monkeypatch.setattr(conversation, "_call_llm", lambda **kwargs: raw)
    details = conversation.generate_card_details(_tier1_npc())
    assert details["appearance"] == "soot-streaked arms, one milky eye"
    assert len(details["dark_trait"]) == conversation.CARD_FIELD_MAX_CHARS
    assert "redeeming_quality" not in details  # empty dropped
    assert "trauma" not in details  # non-string dropped
    assert details["conversation_style"] == "clipped"


def test_generate_card_details_none_when_llm_down(monkeypatch):
    monkeypatch.setattr(conversation, "_call_llm", lambda **kwargs: None)
    assert conversation.generate_card_details(_tier1_npc()) is None


# --------------------------------------------------------------------------- #
# Endpoint orchestration (delta application under the simulation lock)
# --------------------------------------------------------------------------- #
def _seed_world(database, npc):
    player = _tier1_npc(id="npc_player", name="Aldric Snow", is_player=True)
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


def test_apply_conversation_delta_persists_card_changes(temp_db):
    import main

    npc = _tier1_npc()
    _seed_world(temp_db, npc)
    delta = {"reply": "Aye.", "mood": "happy", "sentiment_delta": 8, "memory": "a kind word"}

    updated = main._apply_conversation_delta(npc["id"], "Aldric Snow", "Good work!", delta, 4, 11)

    stored = temp_db.get_npc(npc["id"])
    assert updated["current_mood"] == "happy"
    assert stored["current_mood"] == "happy"
    assert stored["player_sentiment"] == 70  # 62 + 8
    assert stored["mood_reason"] == "after speaking with Aldric Snow"
    assert any("a kind word" in memory for memory in stored["memory_buffer"])
    assert stored["conversation_history"][-1]["player_text"] == "Good work!"
    assert stored["conversation_history"][-1]["npc_response"] == "Aye."


def test_apply_conversation_delta_clamps_sentiment_and_caps_history(temp_db):
    import main

    npc = _tier1_npc(player_sentiment=97, conversation_history=[])
    _seed_world(temp_db, npc)
    for turn in range(conversation.HISTORY_CAP + 3):
        delta = {"reply": f"r{turn}", "mood": "content", "sentiment_delta": 10, "memory": ""}
        main._apply_conversation_delta(npc["id"], "Aldric Snow", f"t{turn}", delta, 4, 11)

    stored = temp_db.get_npc(npc["id"])
    assert stored["player_sentiment"] == 100  # clamped, never above
    assert len(stored["conversation_history"]) == conversation.HISTORY_CAP
    assert stored["conversation_history"][-1]["npc_response"] == f"r{conversation.HISTORY_CAP + 2}"


def test_run_conversation_tier2_uses_stub_and_returns_display_shape(temp_db):
    import main

    npc = _tier1_npc(id="npc_t2", tier=2, current_mood="neutral")
    _seed_world(temp_db, npc)
    result = main._run_conversation("npc_t2", "Any news?")
    # Display-ready contract only: no raw card-delta fields leak out.
    assert set(result) == {"npc_response", "mood"}
    assert result["npc_response"]
    assert result["mood"] == "neutral"
    stored = temp_db.get_npc("npc_t2")
    assert stored["conversation_history"][-1]["player_text"] == "Any news?"


def test_run_conversation_rejects_unknown_and_self(temp_db):
    import main
    from fastapi import HTTPException

    npc = _tier1_npc()
    _seed_world(temp_db, npc)
    with pytest.raises(HTTPException) as missing:
        main._run_conversation("npc_nope", "Hello?")
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as own:
        main._run_conversation("npc_player", "Hello me")
    assert own.value.status_code == 400
