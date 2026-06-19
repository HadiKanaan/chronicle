"""Day 5 (User Story 3) checks: conversation parsing, deltas, and endpoints.

No test here talks to a real Ollama server: the LLM boundary is monkeypatched
so the suite stays fast and deterministic. Live conversation quality is
verified manually against the running backend.
"""

from __future__ import annotations

import pytest

from ml import train as ml
from systems import conversation


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


def test_remember_collapses_a_doubled_day_stamp():
    from systems import behavior

    npc = {"id": "npc_z", "memory_buffer": []}
    # A caller prepended "Day N:" to text that already carried one - store it once.
    behavior.remember(npc, "Day 4: Day 4: Night fell quietly on Aldenmoor.")
    assert npc["memory_buffer"] == ["Day 4: Night fell quietly on Aldenmoor."]


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


def test_character_prompt_is_static_and_carries_the_card():
    prompt = conversation.build_character_prompt(_tier1_npc())
    assert "Mara Vane" in prompt
    assert "blacksmith" in prompt
    assert "resentful of the magistrate" in prompt
    assert "one or two short sentences" in prompt  # plain-text instruction (no JSON contract)
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
    assert "the traveller" in block  # player referred to generically, never by name
    assert "Aldric Snow" not in block  # a 1.5B model latches onto a name in-prompt
    assert "a storm broke over Aldenmoor" in block  # memory buffer surfaced
    assert "Cultists struck the market." in block  # rumor texts surfaced


def test_history_replays_as_plain_chat_turns():
    messages = conversation._history_messages(_tier1_npc())
    assert messages[0] == {"role": "user", "content": "Hello."}
    # The assistant turn replays as the bare spoken line - what the model produces.
    assert messages[1] == {"role": "assistant", "content": "Hm. You again."}


def test_converse_tier1_splits_static_prefix_from_volatile_user_block(monkeypatch):
    captured = {}

    def fake_call(**kwargs):
        captured.update(kwargs)
        return "Aye."

    monkeypatch.setattr(conversation, "_call_llm", fake_call)
    conversation.converse_tier1(_tier1_npc(), "Aldric Snow", "Fine blade.", ["a rumor"])
    assert captured["history"][0] == {"role": "user", "content": "Hello."}
    assert "Current mood" in captured["user"]  # volatile block rides the user message
    assert "a rumor" in captured["user"]
    assert "Fine blade." in captured["user"]
    assert "Current mood" not in captured["system"]  # system stays cacheable


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
            "The shadows hunger tonight, Fyra.",  # observed live: same line for a new question
            "Ask the ferryman, not me.",
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
    raw = "The shadows hunger tonight, Fyra."
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
    raw = "Well met."
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
    assert stored["mood_reason"] == "after the last conversation"
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
