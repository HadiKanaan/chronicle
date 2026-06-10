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


def get_world_state() -> Optional[dict[str, Any]]:
    with _connect() as connection:
        row = connection.execute(
            "SELECT data FROM world_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        return _loads(row["data"])


def save_world_state(world_state: dict[str, Any]) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO world_state (id, data) VALUES (1, ?)",
            (_dumps(world_state),),
        )


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


def get_all_factions() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute("SELECT data FROM factions ORDER BY id ASC").fetchall()
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