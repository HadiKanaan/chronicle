"""Day 10 checks: the `recent_contacts` relationships feed (Part D).

`recent_contacts` is a display-only projection over existing NPC fields - it adds
no gameplay, no persistence, no new mutation. These tests pin its derivation:
only NPCs the player has actually spoken to appear, the player and the Demon Lord
are excluded, it is capped at 5 and ordered most-recent-first (by
last_talked_stamp), and every entry is display-ready with the same
sentiment_phrase disposition the dialogue panel uses. The RenderPayload must also
still validate with the new field, defaulting to an empty list.
"""

from __future__ import annotations

import main
from models.world import RenderPayload
from systems import conversation


def _npc(npc_id, *, count=0, stamp=0.0, sentiment=50, **overrides):
    npc = {
        "id": npc_id,
        "name": f"NPC {npc_id}",
        "occupation": "merchant",
        "current_mood": "content",
        "player_conversation_count": count,
        "last_talked_stamp": stamp,
        "player_sentiment": sentiment,
        "is_player": False,
        "is_demon_lord": False,
        "sprite_id": "human_base",
    }
    npc.update(overrides)
    return npc


def test_never_talked_npc_is_absent():
    contacts = main._build_recent_contacts([_npc("a", count=0, stamp=99.0)])
    assert contacts == []


def test_player_and_demon_lord_excluded():
    npcs = [
        _npc("villager", count=3, stamp=10.0),
        _npc("hero", count=5, stamp=20.0, is_player=True),
        _npc("dl", count=5, stamp=30.0, is_demon_lord=True),
    ]
    contacts = main._build_recent_contacts(npcs)
    assert [c["npc_id"] for c in contacts] == ["villager"]


def test_ordered_most_recent_first():
    npcs = [
        _npc("old", count=1, stamp=1.0),
        _npc("newest", count=1, stamp=9.0),
        _npc("middle", count=1, stamp=5.0),
    ]
    order = [c["npc_id"] for c in main._build_recent_contacts(npcs)]
    assert order == ["newest", "middle", "old"]


def test_capped_at_five():
    npcs = [_npc(f"n{i}", count=1, stamp=float(i)) for i in range(8)]
    contacts = main._build_recent_contacts(npcs)
    assert len(contacts) == 5
    # The five most recent stamps (7..3), most-recent-first.
    assert [c["npc_id"] for c in contacts] == ["n7", "n6", "n5", "n4", "n3"]


def test_entries_are_display_ready():
    npc = _npc(
        "smith",
        count=4,
        stamp=12.0,
        sentiment=80,
        name="Mara Vane",
        occupation="blacksmith",
        current_mood="proud",
    )
    [entry] = main._build_recent_contacts([npc])
    assert entry == {
        "npc_id": "smith",
        "name": "Mara Vane",
        "occupation": "blacksmith",
        "sprite_id": "human_base",
        "mood": "proud",
        "disposition": conversation.sentiment_phrase(80),
        "times_talked": 4,
    }
    # Disposition mirrors the dialogue panel's phrasing exactly.
    assert entry["disposition"] == "warm and trusting"


def test_sprite_id_uses_occupation_mapping():
    # A guard with the default base sprite should surface its role sprite, the
    # same _display_sprite mapping the world renderer uses.
    guard = _npc("guard1", count=1, stamp=1.0, occupation="guard")
    [entry] = main._build_recent_contacts([guard])
    assert entry["sprite_id"] == "npc_knight"


def test_render_payload_validates_with_recent_contacts():
    # The field defaults to an empty list and accepts the display-ready dicts.
    empty = RenderPayload(time_of_day="dawn", weather="clear")
    assert empty.recent_contacts == []

    contacts = main._build_recent_contacts([_npc("a", count=2, stamp=3.0)])
    payload = RenderPayload(
        time_of_day="dawn", weather="clear", recent_contacts=contacts
    )
    assert payload.recent_contacts[0]["npc_id"] == "a"
