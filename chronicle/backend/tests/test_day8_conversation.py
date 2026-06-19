"""Day 8 conversation speedup: the model writes only the reply; the backend
computes mood, sentiment, and memory.

Covers the new split-of-work pieces:
- systems.sentiment: kind -> positive delta, hostile -> negative, neutral ~0,
  and the no-sklearn lexicon fallback.
- conversation.derive_post_exchange_mood: a negative delta pushes toward a more
  negative mood; the reserved (story-only) moods are never emitted.
- conversation.build_conversation_memory: a significant exchange records a
  keyworded line, trivial chatter records nothing, and the line carries no day
  stamp (the caller adds it).
- conversation.converse_tier1 (default plain path): a stubbed plain-text LLM
  yields a reply + a backend-computed delta, and never raises on non-JSON output.

No real Ollama server or database: the LLM boundary is monkeypatched.
"""

from __future__ import annotations

from systems import behavior, conversation, sentiment


# --------------------------------------------------------------------------- #
# Sentiment scoring (ML classifier + lexicon fallback)
# --------------------------------------------------------------------------- #
def test_sentiment_kind_is_positive():
    assert sentiment.score_sentiment("Thank you so much, you are very kind") > 0


def test_sentiment_hostile_is_negative():
    assert sentiment.score_sentiment("You are a vile lying thief, I will kill you") < 0


def test_sentiment_neutral_is_near_zero():
    delta = sentiment.score_sentiment("Where is the market from here?")
    assert abs(delta) <= 2


def test_sentiment_is_clamped_and_deterministic():
    msg = "I hate you, you murdering traitor, I curse your filthy blood"
    first = sentiment.score_sentiment(msg)
    assert first == sentiment.score_sentiment(msg)  # deterministic
    assert -sentiment.SENTIMENT_DELTA_LIMIT <= first <= sentiment.SENTIMENT_DELTA_LIMIT


def test_sentiment_empty_is_zero():
    assert sentiment.score_sentiment("") == 0
    assert sentiment.score_sentiment("   ") == 0


def test_sentiment_lexicon_fallback_without_sklearn(monkeypatch):
    # Force the graceful-degradation path: no scikit-learn, hand-rolled lexicon.
    monkeypatch.setattr(sentiment, "_SENTIMENT_AVAILABLE", False)
    monkeypatch.setattr(sentiment, "_pipeline", None)
    monkeypatch.setattr(sentiment, "_pipeline_trained", False)
    assert sentiment.score_sentiment("thank you friend, you are very kind") > 0
    assert sentiment.score_sentiment("I will kill you, you wretched thief") < 0
    assert sentiment.score_sentiment("where is the road east") == 0
    # Negation flips polarity: "not kind" is not a compliment.
    assert sentiment.score_sentiment("you are not kind at all") < 0


# --------------------------------------------------------------------------- #
# Mood derivation (reuse behavior.MOOD_VALENCE, no new model)
# --------------------------------------------------------------------------- #
def test_negative_delta_drifts_content_toward_a_more_negative_mood():
    new_mood = conversation.derive_post_exchange_mood("content", -8)
    assert behavior.MOOD_VALENCE[new_mood] < behavior.MOOD_VALENCE["content"]


def test_positive_delta_drifts_neutral_toward_a_more_positive_mood():
    new_mood = conversation.derive_post_exchange_mood("neutral", 9)
    assert behavior.MOOD_VALENCE[new_mood] > behavior.MOOD_VALENCE["neutral"]


def test_near_zero_delta_holds_current_mood():
    assert conversation.derive_post_exchange_mood("content", 0) == "content"
    assert conversation.derive_post_exchange_mood("suspicious", 1) == "suspicious"


def test_reserved_moods_are_never_emitted():
    # Across every starting mood and the full delta range, grieving/fearful
    # (reserved for scripted story beats) must never be produced.
    for start in behavior.MOOD_VALENCE:
        for delta in range(-conversation.SENTIMENT_DELTA_LIMIT, conversation.SENTIMENT_DELTA_LIMIT + 1):
            assert conversation.derive_post_exchange_mood(start, delta) not in conversation.RESERVED_MOODS


# --------------------------------------------------------------------------- #
# Memory gating (significance-gated, keyworded, unstamped)
# --------------------------------------------------------------------------- #
def test_significant_exchange_records_a_keyworded_memory():
    memory = conversation.build_conversation_memory("Aldric", "Did you murder the magistrate?", -7)
    assert memory  # something was recorded
    assert "murder" in memory and "magistrate" in memory  # real keywords for recall
    assert "Aldric" in memory
    assert not memory.startswith("Day ")  # caller stamps the day, not this


def test_topic_trigger_records_even_when_tone_is_level():
    # Calm question, near-zero sentiment, but a charged topic -> still recorded.
    memory = conversation.build_conversation_memory("Aldric", "Tell me about the flood", 0)
    assert memory and "flood" in memory


def test_trivial_chatter_records_nothing():
    assert conversation.build_conversation_memory("Aldric", "Where is the market?", 0) == ""
    assert conversation.build_conversation_memory("Aldric", "Nice weather today", 2) == ""


# --------------------------------------------------------------------------- #
# converse_tier1 default plain path
# --------------------------------------------------------------------------- #
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


def test_plain_path_returns_reply_and_computed_delta(monkeypatch):
    # The model speaks plain prose; mood/sentiment/memory are computed backend-side.
    monkeypatch.setattr(conversation, "_call_llm", lambda **kwargs: "Aye, the forge runs hot today.")
    result = conversation.converse_tier1(_tier1_npc(), "Aldric", "You are very kind, thank you.")

    assert set(result) == {"reply", "mood", "sentiment_delta", "memory", "used_llm"}
    assert result["used_llm"] is True
    assert result["reply"] == "Aye, the forge runs hot today."
    assert result["sentiment_delta"] > 0  # a warm line lifts sentiment
    assert result["mood"] in conversation.VALID_MOODS
    assert "reply_was_genuine" not in result  # internal flag never leaks


def test_plain_path_never_raises_on_non_json_output(monkeypatch):
    # Stray JSON / quotes / think-blocks must be cleaned, never crash or leak.
    for raw in (
        '{"reply": "State your business."}',  # model ignored the plain instruction
        '"Just a quoted line."',
        "<think>hmm</think>The river is quiet tonight.",
        '{"mood": "angry", "sentiment_delta": -3}',  # no reply field at all
        "",
    ):
        monkeypatch.setattr(conversation, "_call_llm", lambda **kwargs: raw)
        result = conversation.converse_tier1(_tier1_npc(), "Aldric", "What news?")
        assert result["reply"]  # always something speakable
        assert '"reply"' not in result["reply"]  # raw JSON never reaches the player
        assert "mood" in result and "sentiment_delta" in result


def test_plain_path_falls_back_to_stub_when_llm_down(monkeypatch):
    monkeypatch.setattr(conversation, "_call_llm", lambda **kwargs: None)
    result = conversation.converse_tier1(_tier1_npc(), "Aldric", "Hello?")
    assert result["used_llm"] is False
    assert result["reply"]
    assert result["mood"] == "content"  # stub never shifts mood
    assert result["sentiment_delta"] == 0


# --------------------------------------------------------------------------- #
# Prefix warming on dialogue open (latency: pay prompt-eval before the player
# sends, while they read/type, so the first turn only waits for generation)
# --------------------------------------------------------------------------- #
def test_prewarm_npc_warms_the_static_prefix_cheaply(monkeypatch):
    captured = {}

    def fake_call(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(conversation, "_call_llm", fake_call)
    npc = _tier1_npc(name="Mara Vane", occupation="blacksmith",
                     memory_buffer=["Day 2: a flood took the low road."])
    assert conversation.prewarm_npc(npc, "Aldric", ["a market rumor"]) is True
    # Warming wants only the prefill: plain call, no schema, a single token out.
    assert captured["json_format"] is False
    assert captured["schema"] is None
    assert captured["num_predict"] <= 8
    # It carries the exact static system prompt converse_tier1 will reuse...
    assert "Mara Vane" in captured["system"] and "blacksmith" in captured["system"]
    # ...the stable situation prefix (mood/disposition/rumors)...
    assert "Current mood" in captured["user"] and "a market rumor" in captured["user"]
    # ...but NOT the memories (those vary with the player's query, so they sit in
    # the re-evaluated tail, not the warmed prefix).
    assert "Things you remember" not in captured["user"]


def test_prewarm_block_is_a_true_prefix_of_the_real_turn(monkeypatch):
    # The whole optimization rests on this: the warmed user block must be a
    # byte-exact prefix of converse_tier1's user message, or Ollama re-evaluates
    # everything and the warm buys nothing.
    npc = _tier1_npc(
        memory_buffer=["Day 1: the flood drowned my brother", "Day 3: a storm broke"],
        conversation_history=[],
    )
    calls = []
    monkeypatch.setattr(conversation, "_call_llm", lambda **kw: calls.append(kw) or "Aye.")
    conversation.prewarm_npc(npc, "Aldric", ["a market rumor"])
    conversation.converse_tier1(npc, "Aldric", "tell me about the flood", ["a market rumor"])

    warm_user, turn_user = calls[0]["user"], calls[1]["user"]
    assert turn_user.startswith(warm_user), "warm block must be a prefix of the real turn"
    assert "tell me about the flood" in turn_user  # the varying tail is the new part
    assert calls[0]["system"] == calls[1]["system"]  # identical cached system prompt


def test_prewarm_npc_reports_false_when_llm_down(monkeypatch):
    monkeypatch.setattr(conversation, "_call_llm", lambda **kwargs: None)
    assert conversation.prewarm_npc(_tier1_npc(), "Aldric") is False


def _seed_npc(database, npc):
    database.save_npc(npc)
    database.save_world_state(
        {"game_started": True, "current_day": 1, "current_hour": 6,
         "player_npc_id": None, "region": {"id": "r", "width": 4, "height": 4}}
    )


def test_dialogue_open_with_npc_id_prewarms_tier1(temp_db, monkeypatch):
    import threading

    import main

    _seed_npc(temp_db, _tier1_npc(id="npc_warm"))
    fired = threading.Event()
    seen = {}

    def fake_prewarm(npc, *args, **kwargs):
        seen["id"] = npc["id"]
        fired.set()
        return True

    monkeypatch.setattr(main.conversation, "prewarm_npc", fake_prewarm)
    main.post_input(main.PlayerInput(type="dialogue_open", payload={"npc_id": "npc_warm"}))
    assert fired.wait(2.0), "tier 1 dialogue open should warm the LLM prefix"
    assert seen["id"] == "npc_warm"


def test_dialogue_open_skips_prewarm_for_tier2(temp_db, monkeypatch):
    import threading

    import main

    _seed_npc(temp_db, _tier1_npc(id="npc_t2", tier=2))
    fired = threading.Event()
    monkeypatch.setattr(main.conversation, "prewarm_npc", lambda npc, *a, **k: fired.set() or True)
    main.post_input(main.PlayerInput(type="dialogue_open", payload={"npc_id": "npc_t2"}))
    assert not fired.wait(0.5), "tier 2 NPCs use stubs - no LLM prewarm"


def test_dialogue_open_without_npc_id_does_not_prewarm(temp_db, monkeypatch):
    import threading

    import main

    fired = threading.Event()
    monkeypatch.setattr(main.conversation, "prewarm_npc", lambda npc, *a, **k: fired.set() or True)
    # The freeze heartbeat re-sends dialogue_open with an empty payload.
    main.post_input(main.PlayerInput(type="dialogue_open", payload={}))
    assert not fired.wait(0.3), "a heartbeat (no npc_id) must not re-warm"
