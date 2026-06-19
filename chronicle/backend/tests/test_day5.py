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
        "reply_was_genuine": True,
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


def test_parse_card_delta_salvages_memory_as_reply_when_reply_dropped():
    # Observed live with qwen3:4b (measured ~30-60% of calls on Day 6): the
    # model drops "reply" and the spoken answer lands in "memory" instead.
    raw = '{"mood": "content", "sentiment_delta": 0, "memory": "Fyra showed me a dagger."}'
    delta = conversation.parse_card_delta(raw, "content")
    assert delta["reply"] == "Fyra showed me a dagger."  # memory-field rescue
    assert delta["memory"] == "Fyra showed me a dagger."
    assert delta["reply_was_genuine"] is False  # signals converse_tier1 to retry


def test_parse_card_delta_safe_line_when_reply_and_memory_both_unusable():
    raw = '{"mood": "content", "sentiment_delta": 0, "memory": ""}'
    delta = conversation.parse_card_delta(raw, "content")
    assert delta["reply"]  # a safe in-character line
    assert '"mood"' not in delta["reply"]
    assert delta["reply_was_genuine"] is False


def test_parse_card_delta_never_leaks_json_from_unparseable_fragments():
    raw = '"mood": "content",\n  "sentiment_delta": 0,\n  "memory": "broken"'
    delta = conversation.parse_card_delta(raw, "neutral")
    assert '"sentiment_delta"' not in delta["reply"]
    assert delta["reply"]


def test_remember_refreshes_duplicate_memories_instead_of_stacking():
    from systems import behavior

    npc = {"id": "npc_x", "memory_buffer": []}
    behavior.remember(npc, "Day 12: Fyra showed me a strange dagger.")
    behavior.remember(npc, "Day 13: a storm broke over Aldenmoor.")
    behavior.remember(npc, "Day 14: Fyra showed me a strange dagger.")
    # The repeat replaced the day-12 entry and moved it to most-recent.
    assert npc["memory_buffer"] == [
        "Day 13: a storm broke over Aldenmoor.",
        "Day 14: Fyra showed me a strange dagger.",
    ]


def test_world_gen_npc_names_are_unique():
    from systems import world_gen

    world = world_gen.build_world(seed=99)
    names = [npc.name for npc in world["npcs"]]
    assert len(names) == len(set(names))


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


def test_character_prompt_is_static_and_carries_the_card(monkeypatch):
    # The JSON contract only appears on the legacy structured path (Day 8 made
    # plain text the default); exercise it here.
    monkeypatch.setattr(conversation, "LLM_STRUCTURED_OUTPUT", True)
    prompt = conversation.build_character_prompt(_tier1_npc())
    assert "Mara Vane" in prompt
    assert "blacksmith" in prompt
    assert "resentful of the magistrate" in prompt
    assert '"sentiment_delta"' in prompt  # card-delta JSON contract requested
    # Volatile state must stay OUT of the system prompt: it has to remain
    # byte-identical between turns or the Ollama prefix cache is useless.
    assert "Current mood" not in prompt
    assert "a storm broke over Aldenmoor" not in prompt
    assert "Hm. You again." not in prompt
    assert "Aldric Snow" not in prompt


def test_situation_block_carries_volatile_context():
    block = conversation.build_situation_block(
        _tier1_npc(), "Aldric Snow", ["Cultists struck the market."]
    )
    assert "Current mood: content" in block
    assert "Aldric Snow" in block  # disposition toward the player
    assert "a storm broke over Aldenmoor" in block  # memory buffer surfaced
    assert "Cultists struck the market." in block  # rumor texts surfaced


def test_history_replays_as_chat_turns_with_reply_envelope(monkeypatch):
    import json

    # The {"reply": ...} envelope is the structured path's in-context schooling;
    # the Day 8 default replays the bare spoken line instead.
    monkeypatch.setattr(conversation, "LLM_STRUCTURED_OUTPUT", True)
    messages = conversation._history_messages(_tier1_npc())
    assert messages[0] == {"role": "user", "content": "Hello."}
    assert messages[1]["role"] == "assistant"
    # Replayed in the required envelope: in-context schooling for the model's
    # habit of dropping the "reply" field.
    assert json.loads(messages[1]["content"]) == {"reply": "Hm. You again."}


def test_converse_tier1_splits_static_prefix_from_volatile_user_block(monkeypatch):
    captured = {}

    def fake_call(**kwargs):
        captured.update(kwargs)
        return '{"reply": "Aye.", "mood": "content", "sentiment_delta": 0, "memory": ""}'

    monkeypatch.setattr(conversation, "_call_llm", fake_call)
    conversation.converse_tier1(_tier1_npc(), "Aldric Snow", "Fine blade.", ["a rumor"])
    assert captured["history"][0] == {"role": "user", "content": "Hello."}
    assert "Current mood" in captured["user"]  # volatile block rides the user message
    assert "a rumor" in captured["user"]
    assert "Fine blade." in captured["user"]
    assert "Current mood" not in captured["system"]  # system stays cacheable


def test_converse_tier1_parses_llm_output(monkeypatch):
    raw = '{"reply": "State your business.", "mood": "suspicious", "sentiment_delta": -1, "memory": "a stranger pried"}'
    # Reply + model-authored mood come from one JSON call on the structured path.
    monkeypatch.setattr(conversation, "LLM_STRUCTURED_OUTPUT", True)
    monkeypatch.setattr(conversation, "_call_llm", lambda **kwargs: raw)
    result = conversation.converse_tier1(_tier1_npc(), "Aldric Snow", "What do you forge?")
    assert result["used_llm"] is True
    assert result["reply"] == "State your business."
    assert result["mood"] == "suspicious"


def test_converse_tier1_retries_once_when_reply_dropped(monkeypatch):
    responses = iter(
        [
            '{"mood": "content", "sentiment_delta": 0, "memory": "answer hid in memory"}',
            '{"reply": "Aye, the forge burns hot.", "mood": "content", "sentiment_delta": 1, "memory": ""}',
        ]
    )
    calls = []
    # Reply-field salvage + retry is structured-path behavior (the JSON envelope
    # is what can drop "reply"); plain text has no field to drop.
    monkeypatch.setattr(conversation, "LLM_STRUCTURED_OUTPUT", True)
    monkeypatch.setattr(
        conversation, "_call_llm", lambda **kwargs: calls.append(1) or next(responses)
    )
    result = conversation.converse_tier1(_tier1_npc(), "Aldric Snow", "How's the forge?")
    assert len(calls) == 2  # dropped reply triggered exactly one retry
    assert result["reply"] == "Aye, the forge burns hot."
    assert result["used_llm"] is True
    assert "reply_was_genuine" not in result  # internal flag never leaves


def test_converse_tier1_uses_first_salvage_when_retry_also_drops_reply(monkeypatch):
    raw = '{"mood": "content", "sentiment_delta": 0, "memory": "The river keeps its secrets."}'
    calls = []
    monkeypatch.setattr(conversation, "LLM_STRUCTURED_OUTPUT", True)
    monkeypatch.setattr(
        conversation, "_call_llm", lambda **kwargs: calls.append(1) or raw
    )
    result = conversation.converse_tier1(_tier1_npc(), "Aldric Snow", "Any secrets?")
    assert len(calls) == 2  # exactly one retry, never more
    assert result["reply"] == "The river keeps its secrets."  # memory-field rescue
    assert result["used_llm"] is True


def test_is_parrot_matches_near_identical_lines():
    assert conversation._is_parrot(
        "The shadows hunger tonight, Fyra.", "the shadows hunger tonight fyra"
    ) is True
    assert conversation._is_parrot("Fine day, friend.", "The shadows hunger tonight.") is False
    assert conversation._is_parrot("anything", "") is False
    assert conversation._is_parrot("", "anything") is False


def test_converse_tier1_retries_when_model_parrots_its_previous_line(monkeypatch):
    npc = _tier1_npc(
        conversation_history=[
            {"day": 3, "hour": 10, "player_text": "Hello.",
             "npc_response": "The shadows hunger tonight, Fyra."}
        ]
    )
    responses = iter(
        [
            # Observed live: identical line for a different question.
            '{"reply": "The shadows hunger tonight, Fyra.", "mood": "suspicious", "sentiment_delta": 0, "memory": ""}',
            '{"reply": "Ask the ferryman, not me.", "mood": "suspicious", "sentiment_delta": 0, "memory": ""}',
        ]
    )
    calls = []
    monkeypatch.setattr(
        conversation, "_call_llm", lambda **kwargs: calls.append(kwargs) or next(responses)
    )
    result = conversation.converse_tier1(npc, "Fyra", "Why so wary?")
    assert len(calls) == 2
    assert result["reply"] == "Ask the ferryman, not me."
    assert "do NOT reuse the wording" in calls[1]["user"]  # anti-repeat nudge rode the retry
    assert calls[1]["temperature"] > calls[0]["temperature"]


def test_converse_tier1_accepts_repeat_if_retry_parrots_too(monkeypatch):
    npc = _tier1_npc(
        conversation_history=[
            {"day": 3, "hour": 10, "player_text": "Hello.",
             "npc_response": "The shadows hunger tonight, Fyra."}
        ]
    )
    raw = '{"reply": "The shadows hunger tonight, Fyra.", "mood": "suspicious", "sentiment_delta": 0, "memory": ""}'
    calls = []
    monkeypatch.setattr(
        conversation, "_call_llm", lambda **kwargs: calls.append(1) or raw
    )
    result = conversation.converse_tier1(npc, "Fyra", "Why so wary?")
    assert len(calls) == 2  # exactly one retry, never more
    # A repeated in-character line still beats a canned stub.
    assert result["reply"] == "The shadows hunger tonight, Fyra."
    assert result["used_llm"] is True


def test_converse_tier1_single_call_when_reply_is_genuine(monkeypatch):
    raw = '{"reply": "Well met.", "mood": "content", "sentiment_delta": 0, "memory": ""}'
    calls = []
    monkeypatch.setattr(
        conversation, "_call_llm", lambda **kwargs: calls.append(1) or raw
    )
    result = conversation.converse_tier1(_tier1_npc(), "Aldric Snow", "Hello.")
    assert len(calls) == 1  # no needless retry cost
    assert result["reply"] == "Well met."


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
