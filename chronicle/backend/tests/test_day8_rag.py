"""Day 8 (RAG): relevance retrieval over an NPC's memory buffer.

Verifies that retrieval surfaces the memory relevant to the player's message
over a more-recent-but-irrelevant one, that empty/tiny/no-sklearn cases fall
back to recency, and that build_situation_block injects the recalled memories
when given. No server or LLM is involved; recall.py is pure.
"""

from __future__ import annotations

from systems import conversation, recall


def test_relevance_beats_recency():
    # The important memory is the OLDEST; recency alone would never surface it.
    memories = [
        "my brother drowned in the great flood",  # oldest, important
        "bought bread at the market",
        "mended the garden fence",
        "swept the tavern floor",
        "fed the chickens at dawn",  # most recent
    ]
    recalled = recall.recall_relevant(memories, "what happened to your brother in the flood?", k=3)

    assert recalled[0] == "my brother drowned in the great flood", "most relevant memory should rank first"
    # Recency would have returned the last three; relevance pulls from the deep past.
    assert "my brother drowned in the great flood" not in memories[-3:]


def test_empty_store_returns_empty():
    assert recall.recall_relevant([], "anything") == []
    assert recall.recall_relevant(["", "  "], "anything") == []


def test_tiny_store_falls_back_to_recency():
    # With <= k memories there is nothing to rank: return them (recency).
    mems = ["a", "b"]
    assert recall.recall_relevant(mems, "totally unrelated query", k=3) == ["a", "b"]


def test_no_term_overlap_falls_back_to_recency():
    mems = ["chopped firewood", "salted the fish", "patched the roof", "milked the goat"]
    out = recall.recall_relevant(mems, "xyzzy plugh nothing matches", k=2)
    assert out == mems[-2:]  # no signal -> most recent k


def test_no_sklearn_falls_back_to_recency(monkeypatch):
    monkeypatch.setattr(recall, "_SKLEARN_AVAILABLE", False)
    mems = ["my brother drowned in the flood", "bought bread", "mended a fence", "fed the hens"]
    # Even with an overlapping query, the no-sklearn path is pure recency.
    assert recall.recall_relevant(mems, "tell me about the flood", k=3) == mems[-3:]


def test_situation_block_uses_recalled_memories_when_given():
    npc = {
        "current_mood": "wary",
        "player_sentiment": 50,
        "memory_buffer": ["recent and dull", "also recent", "newest thing"],
    }
    block = conversation.build_situation_block(
        npc, "Aldric", recalled_memories=["my brother drowned in the flood"]
    )
    assert "my brother drowned in the flood" in block
    assert "newest thing" not in block  # recency default was overridden


def test_situation_block_defaults_to_recency_without_recalled():
    npc = {
        "current_mood": "content",
        "player_sentiment": 60,
        "memory_buffer": ["old one", "middle one", "newest one", "newest of all"],
    }
    block = conversation.build_situation_block(npc, "Aldric")
    assert "newest of all" in block and "old one" not in block  # last 3 only
