"""Day 7 — faction model decoupling (player standing vs morale vs history).

The Demon Lord now erodes faction MORALE, not the town's regard for the player;
morale drifts from member moods back toward a baseline (the restoring force that
fixes the old reputation-to-0 ratchet); each faction keeps a capped history.
"""

from __future__ import annotations

from systems import factions


def _member(faction_id, mood="neutral", npc_id="n"):
    return {"id": npc_id, "current_mood": mood, "faction_affiliations": [{"faction_id": faction_id}]}


# --------------------------------------------------------------------------- #
# Morale drift (restoring force) — pure function, no DB
# --------------------------------------------------------------------------- #
def test_morale_drifts_toward_baseline_from_both_directions():
    low = {"id": "f1", "morale": 20}
    high = {"id": "f2", "morale": 90}
    npcs = [_member("f1", "neutral", "a"), _member("f2", "neutral", "b")]

    changed = factions.update_morale_daily([low, high], npcs)

    # baseline 55, step 0.2: 20 + (55-20)*.2 = 27 ; 90 + (55-90)*.2 = 83
    assert low["morale"] == 27
    assert high["morale"] == 83
    assert {f["id"] for f in changed} == {"f1", "f2"}  # both moved


def test_morale_target_follows_member_moods():
    frightened = {"id": "f1", "morale": 60}
    content = {"id": "f2", "morale": 60}
    npcs = [
        _member("f1", "fearful", "a"), _member("f1", "fearful", "b"),
        _member("f2", "happy", "c"), _member("f2", "content", "d"),
    ]

    factions.update_morale_daily([frightened, content], npcs)

    assert frightened["morale"] < 60  # frightened members drag morale down
    assert content["morale"] > 60     # high-spirited members lift it


def test_morale_with_no_members_eases_to_baseline():
    fac = {"id": "f1", "morale": 30}
    factions.update_morale_daily([fac], [])
    assert 30 < fac["morale"] <= 55  # pulled toward the 55 baseline, not snapped


# --------------------------------------------------------------------------- #
# DB helpers: morale adjust (clamp) + history (append/cap)
# --------------------------------------------------------------------------- #
def _seed_faction(database, faction_id="faction_watch"):
    database.save_faction(
        {"id": faction_id, "name": "Watch", "faction_type": "civic",
         "description": "", "color": "#fff", "player_reputation": 50}
    )


def test_adjust_faction_morale_clamps_and_rejects_unknown(temp_db):
    _seed_faction(temp_db)
    # No morale key yet -> defaults to 60 before the delta.
    assert temp_db.adjust_faction_morale("faction_watch", -200) == 0
    assert temp_db.adjust_faction_morale("faction_watch", +500) == 100
    assert temp_db.adjust_faction_morale("faction_void", -5) is None
    # player_reputation is never touched by the morale path.
    assert temp_db.get_faction("faction_watch")["player_reputation"] == 50


def test_append_faction_history_appends_and_caps(temp_db):
    _seed_faction(temp_db, "f")
    for day in range(temp_db.FACTION_HISTORY_CAP + 3):
        temp_db.append_faction_history("f", day, f"event {day}")
    history = temp_db.get_faction("f")["history"]
    assert len(history) == temp_db.FACTION_HISTORY_CAP
    assert history[-1] == {"day": temp_db.FACTION_HISTORY_CAP + 2,
                           "text": f"event {temp_db.FACTION_HISTORY_CAP + 2}"}
    assert history[0]["text"] == "event 3"  # oldest entries trimmed


def test_append_faction_history_unknown_faction_is_a_noop(temp_db):
    temp_db.append_faction_history("faction_void", 1, "nothing")  # must not raise
    assert temp_db.get_faction("faction_void") is None
