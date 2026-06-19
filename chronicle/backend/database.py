from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "data"
DB_PATH = DB_DIR / "chronicle.db"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    # WAL lets the background world clock write while polls read concurrently;
    # busy_timeout makes brief lock contention wait instead of raising.
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _loads(data: str) -> dict[str, Any]:
    return json.loads(data)


def init_db() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS world_state (
                id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            )
            """
        )
        # Day 7: the immutable tile grid + buildings live here, written once at
        # generation, so the hourly world-state save stops rewriting the 48x48
        # blob every game hour (tiles never change post-gen).
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS region_static (
                id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            )
            """
        )
        # Day 7: the visual-only continent map, generated once and cached.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS continent (
                id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS npcs (
                id TEXT PRIMARY KEY,
                tier INTEGER NOT NULL,
                data TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS factions (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS faction_relationships (
                faction_a_id TEXT,
                faction_b_id TEXT,
                data TEXT NOT NULL,
                PRIMARY KEY (faction_a_id, faction_b_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rumors (
                id TEXT PRIMARY KEY,
                active INTEGER NOT NULL DEFAULT 1,
                data TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS game_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day INTEGER NOT NULL,
                hour INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )


# Region fields that never change after generation. Persisted once in
# region_static and merged back on read, so the hot world-state blob stays lean.
_STATIC_REGION_FIELDS = ("tiles", "buildings")


def get_region_static() -> Optional[dict[str, Any]]:
    with _connect() as connection:
        row = connection.execute(
            "SELECT data FROM region_static WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        return _loads(row["data"])


def save_region_static(region: dict[str, Any]) -> None:
    """Persist the immutable region grid (tiles + buildings) exactly once."""
    static = {field: region.get(field) for field in _STATIC_REGION_FIELDS}
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO region_static (id, data) VALUES (1, ?)",
            (_dumps(static),),
        )


def get_region_decorations() -> list[dict[str, Any]]:
    """The persisted static decoration scatter (Day 8), or [] if not generated.

    Decorations are visual-only and stored inside the region_static blob so they
    share the tiles' write-once lifecycle and are never rewritten by the hourly
    world tick."""
    static = get_region_static()
    if not static:
        return []
    return static.get("decorations") or []


def save_region_decorations(decorations: list[dict[str, Any]]) -> None:
    """Fold the decoration layer into region_static without rewriting the tile
    grid or buildings already stored there. Idempotent: callers generate once
    and persist, then read back via get_region_decorations."""
    static = get_region_static() or {}
    static["decorations"] = decorations
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO region_static (id, data) VALUES (1, ?)",
            (_dumps(static),),
        )


def get_region_paths() -> list[dict[str, Any]]:
    """The persisted static road network (Day 8), or [] if not generated. Like
    decorations these live in region_static (write-once, visual-only)."""
    static = get_region_static()
    if not static:
        return []
    return static.get("paths") or []


def save_region_paths(paths: list[dict[str, Any]]) -> None:
    """Fold the path network into region_static without rewriting the tile grid,
    buildings, or decorations already stored there."""
    static = get_region_static() or {}
    static["paths"] = paths
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO region_static (id, data) VALUES (1, ?)",
            (_dumps(static),),
        )


def get_region_props() -> list[dict[str, Any]]:
    """The persisted static town-prop layer (Day 8), or [] if not generated."""
    static = get_region_static()
    if not static:
        return []
    return static.get("props") or []


def save_region_props(props: list[dict[str, Any]]) -> None:
    """Fold the prop layer into region_static without rewriting the tile grid,
    buildings, decorations, or paths already stored there."""
    static = get_region_static() or {}
    static["props"] = props
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO region_static (id, data) VALUES (1, ?)",
            (_dumps(static),),
        )


def get_world_state() -> Optional[dict[str, Any]]:
    with _connect() as connection:
        row = connection.execute(
            "SELECT data FROM world_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        state = _loads(row["data"])
    # Merge the immutable tile grid back onto the region so every caller still
    # sees a fully-populated state["region"]["tiles"].
    region = state.get("region")
    if isinstance(region, dict):
        static = get_region_static()
        if static:
            for field in _STATIC_REGION_FIELDS:
                if static.get(field) is not None:
                    region[field] = static[field]
    return state


def save_world_state(world_state: dict[str, Any]) -> None:
    region = world_state.get("region")
    blob = world_state
    if isinstance(region, dict):
        # First save (or a legacy world with tiles embedded): persist the static
        # grid once. Thereafter the hourly save writes only the mutable fields.
        if get_region_static() is None and any(region.get(f) for f in _STATIC_REGION_FIELDS):
            save_region_static(region)
        lean_region = {k: v for k, v in region.items() if k not in _STATIC_REGION_FIELDS}
        blob = {**world_state, "region": lean_region}
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO world_state (id, data) VALUES (1, ?)",
            (_dumps(blob),),
        )


def world_is_generated() -> bool:
    state = get_world_state()
    return bool(state and state.get("game_started"))


def clear_world() -> None:
    """Remove all generated world data so a fresh world can be written."""
    with _connect() as connection:
        for table in (
            "world_state", "region_static", "npcs", "factions",
            "faction_relationships", "rumors",
        ):
            connection.execute(f"DELETE FROM {table}")


def save_world(
    world_state: dict[str, Any],
    npcs: list[dict[str, Any]],
    factions: list[dict[str, Any]],
    faction_relationships: list[dict[str, Any]],
) -> None:
    """Persist a freshly generated world, replacing any existing world data."""
    clear_world()
    save_world_state(world_state)
    for npc in npcs:
        save_npc(npc)
    for faction in factions:
        save_faction(faction)
    for relationship in faction_relationships:
        save_faction_relationship(relationship)


def get_npc(npc_id: str) -> Optional[dict[str, Any]]:
    with _connect() as connection:
        row = connection.execute("SELECT data FROM npcs WHERE id = ?", (npc_id,)).fetchone()
        if row is None:
            return None
        return _loads(row["data"])


def save_npc(npc: dict[str, Any]) -> None:
    npc_id = str(npc["id"])
    tier = int(npc.get("tier", 1))
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO npcs (id, tier, data) VALUES (?, ?, ?)",
            (npc_id, tier, _dumps(npc)),
        )


def save_npcs(npcs: list[dict[str, Any]]) -> None:
    """Persist many NPCs in one transaction (used by the hourly world tick)."""
    if not npcs:
        return
    with _connect() as connection:
        connection.executemany(
            "INSERT OR REPLACE INTO npcs (id, tier, data) VALUES (?, ?, ?)",
            [
                (str(npc["id"]), int(npc.get("tier", 1)), _dumps(npc))
                for npc in npcs
            ],
        )


def get_all_npcs() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute("SELECT data FROM npcs ORDER BY id ASC").fetchall()
        return [_loads(row["data"]) for row in rows]


def get_npcs_by_tier(tier: int) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT data FROM npcs WHERE tier = ? ORDER BY id ASC",
            (tier,),
        ).fetchall()
        return [_loads(row["data"]) for row in rows]


def get_faction(faction_id: str) -> Optional[dict[str, Any]]:
    with _connect() as connection:
        row = connection.execute(
            "SELECT data FROM factions WHERE id = ?",
            (faction_id,),
        ).fetchone()
        if row is None:
            return None
        return _loads(row["data"])


def save_faction(faction: dict[str, Any]) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO factions (id, data) VALUES (?, ?)",
            (str(faction["id"]), _dumps(faction)),
        )


def adjust_faction_reputation(faction_id: str, delta: int) -> Optional[int]:
    """Shift a faction's standing by delta, clamped to 0..100.

    Returns the new score, or None for an unknown faction (Day 6: Demon Lord
    decision effects land here after key validation).
    """
    faction = get_faction(faction_id)
    if faction is None:
        return None
    score = max(0, min(100, int(faction.get("player_reputation", 50)) + int(delta)))
    faction["player_reputation"] = score
    save_faction(faction)
    return score


def adjust_faction_morale(faction_id: str, delta: int) -> Optional[int]:
    """Shift a faction's morale by delta, clamped to 0..100.

    Returns the new morale, or None for an unknown faction. Day 7: the Demon
    Lord's pressure lands here (not player_reputation); a dawn drift restores it
    toward baseline so damage heals instead of ratcheting to 0.
    """
    faction = get_faction(faction_id)
    if faction is None:
        return None
    score = max(0, min(100, int(faction.get("morale", 60)) + int(delta)))
    faction["morale"] = score
    save_faction(faction)
    return score


FACTION_HISTORY_CAP = 8


def append_faction_history(faction_id: str, day: int, text: str) -> None:
    """Append a {day, text} line to a faction's rolling narrative log (capped)."""
    faction = get_faction(faction_id)
    if faction is None:
        return
    history = faction.setdefault("history", [])
    history.append({"day": int(day), "text": text})
    if len(history) > FACTION_HISTORY_CAP:
        del history[: len(history) - FACTION_HISTORY_CAP]
    save_faction(faction)


def get_all_factions() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute("SELECT data FROM factions ORDER BY id ASC").fetchall()
        return [_loads(row["data"]) for row in rows]


def save_faction_relationship(relationship: dict[str, Any]) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO faction_relationships
                (faction_a_id, faction_b_id, data)
            VALUES (?, ?, ?)
            """,
            (
                str(relationship["faction_a_id"]),
                str(relationship["faction_b_id"]),
                _dumps(relationship),
            ),
        )


def get_faction_relationships() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT data FROM faction_relationships ORDER BY faction_a_id ASC"
        ).fetchall()
        return [_loads(row["data"]) for row in rows]


def get_active_rumors() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT data FROM rumors WHERE active = 1 ORDER BY id ASC"
        ).fetchall()
        return [_loads(row["data"]) for row in rows]


def save_rumor(rumor: dict[str, Any]) -> None:
    active = 1 if rumor.get("active", True) else 0
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO rumors (id, active, data) VALUES (?, ?, ?)",
            (str(rumor["id"]), active, _dumps(rumor)),
        )


def get_rumor(rumor_id: str) -> Optional[dict[str, Any]]:
    with _connect() as connection:
        row = connection.execute(
            "SELECT data FROM rumors WHERE id = ?",
            (rumor_id,),
        ).fetchone()
        if row is None:
            return None
        return _loads(row["data"])


def add_rumor_knowledge(rumor_id: str, npc_ids: list[str]) -> None:
    """Record that the given NPCs now know a rumor (known-by tracking)."""
    rumor = get_rumor(rumor_id)
    if rumor is None:
        return
    known = rumor.setdefault("known_by_npc_ids", [])
    for npc_id in npc_ids:
        if npc_id not in known:
            known.append(npc_id)
    save_rumor(rumor)


def get_continent() -> Optional[dict[str, Any]]:
    """The cached visual-only continent map, or None if not generated yet."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT data FROM continent WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        return _loads(row["data"])


def save_continent(data: dict[str, Any]) -> None:
    """Persist the continent map once; it is independent of the playable region."""
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO continent (id, data) VALUES (1, ?)",
            (_dumps(data),),
        )


def log_event(day: int, hour: int, event_type: str, description: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO game_log (day, hour, event_type, description, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (day, hour, event_type, description, timestamp),
        )


def get_recent_log(limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT day, hour, event_type, description, timestamp
            FROM game_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]