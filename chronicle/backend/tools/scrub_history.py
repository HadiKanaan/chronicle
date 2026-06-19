"""One-time DB cleanup (Day 8 follow-up): scrub pre-fix conversation artifacts.

Two classes of stale data predate the Day-8 conversation fixes and otherwise keep
biting because they REPLAY into new prompts:

1. The player's proper name baked into stored NPC replies (conversation_history)
   and memories (memory_buffer). Before the de-naming fix the prompt named the
   player, so NPCs echoed it / spoke about the player in the third person; those
   lines replay for ~HISTORY_CAP turns and re-trigger the bug. We replace the
   player's name with "the traveller" everywhere it was stored.
2. Doubled "Day N: Day N:" memory stamps (a Demon-Lord announcement that already
   carried a stamp, re-stamped by remember()). We collapse them.

Idempotent and safe to re-run (a no-op once clean). Run with the backend STOPPED
so it can't race the world tick's NPC writes:

    cd backend && .venv/Scripts/python.exe tools/scrub_history.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Allow running as a plain script from backend/ (mirror conftest's path setup).
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import database as db  # noqa: E402

_DOUBLE_DAY_STAMP = re.compile(r"^(Day \d+:\s*)(?:Day \d+:\s*)+")


def _clean(text: str, player_name: str) -> str:
    out = _DOUBLE_DAY_STAMP.sub(r"\1", text)
    if player_name:
        out = out.replace(player_name, "the traveller")
    return out


def scrub() -> int:
    db.init_db()
    state = db.get_world_state() or {}
    player_id = state.get("player_npc_id") or ""
    player = db.get_npc(player_id) if player_id else None
    player_name = (player or {}).get("name", "").strip()

    changed = 0
    for npc in db.get_all_npcs():
        dirty = False

        memories = npc.get("memory_buffer") or []
        new_memories = [_clean(m, player_name) for m in memories]
        if new_memories != memories:
            npc["memory_buffer"] = new_memories
            dirty = True

        for entry in npc.get("conversation_history") or []:
            response = entry.get("npc_response", "")
            cleaned = _clean(response, player_name)
            if cleaned != response:
                entry["npc_response"] = cleaned
                dirty = True

        if dirty:
            db.save_npc(npc)
            changed += 1
    return changed


if __name__ == "__main__":
    db.init_db()
    state = db.get_world_state() or {}
    pid = state.get("player_npc_id") or ""
    name = (db.get_npc(pid) or {}).get("name") if pid else None
    n = scrub()
    print(f"scrubbed {n} NPC card(s); player referred to generically (was {name!r}).")
