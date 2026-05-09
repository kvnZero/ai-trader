from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS watchlist_stocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        monitoring_enabled INTEGER NOT NULL DEFAULT 1,
        use_default_schedule INTEGER NOT NULL DEFAULT 1,
        schedule_label TEXT NOT NULL DEFAULT '工作日 09:30-11:30 / 13:00-15:00',
        status TEXT NOT NULL DEFAULT 'paused',
        status_label TEXT NOT NULL DEFAULT '等待开市',
        latest_recommendation TEXT NOT NULL DEFAULT 'watch',
        latest_confidence REAL NOT NULL DEFAULT 0.0,
        latest_reason TEXT NOT NULL DEFAULT '',
        last_analysis_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        level TEXT NOT NULL DEFAULT 'medium',
        unread INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        read_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        previous_action TEXT,
        current_action TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.0,
        summary TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        status TEXT NOT NULL,
        stale INTEGER NOT NULL DEFAULT 0,
        detail TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
)


class Database:
    def __init__(self, path: str):
        self.path = Path(path)

    def ensure_initialized(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            conn.commit()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def init_database(path: str) -> Database:
    database = Database(path)
    database.ensure_initialized()
    return database
