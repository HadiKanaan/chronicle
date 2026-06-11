"""Shared test setup: import path + isolated SQLite database per test."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the database module at a throwaway file so tests never touch the
    real world state in backend/data/chronicle.db."""
    import database

    monkeypatch.setattr(database, "DB_DIR", tmp_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "chronicle_test.db")
    database.init_db()
    return database
