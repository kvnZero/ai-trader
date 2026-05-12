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
    """
    CREATE TABLE IF NOT EXISTS sentiment_ingestion_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'running',
        started_at TEXT NOT NULL,
        completed_at TEXT,
        heartbeat_at TEXT,
        item_count INTEGER NOT NULL DEFAULT 0,
        source_run_count INTEGER NOT NULL DEFAULT 0,
        failure_count INTEGER NOT NULL DEFAULT 0,
        duplicate_count INTEGER NOT NULL DEFAULT 0,
        stale_count INTEGER NOT NULL DEFAULT 0,
        error_message TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sentiment_worker_state (
        worker_name TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'idle',
        last_started_at TEXT,
        last_completed_at TEXT,
        last_success_at TEXT,
        last_heartbeat_at TEXT,
        latest_item_published_at TEXT,
        last_run_id INTEGER,
        item_count INTEGER NOT NULL DEFAULT 0,
        source_run_count INTEGER NOT NULL DEFAULT 0,
        failure_count INTEGER NOT NULL DEFAULT 0,
        duplicate_count INTEGER NOT NULL DEFAULT 0,
        stale_count INTEGER NOT NULL DEFAULT 0,
        error_message TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sentiment_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dedup_key TEXT NOT NULL UNIQUE,
        run_id INTEGER NOT NULL,
        source_id TEXT NOT NULL,
        source_name TEXT NOT NULL,
        category TEXT NOT NULL,
        adapter_name TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        published_at TEXT NOT NULL,
        collected_at TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        url TEXT,
        sentiment_score REAL,
        tags_json TEXT NOT NULL DEFAULT '[]',
        raw_reference TEXT,
        source_item_id TEXT,
        age_seconds INTEGER NOT NULL DEFAULT 0,
        raw_payload_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sentiment_source_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        source_id TEXT NOT NULL,
        source_name TEXT NOT NULL,
        category TEXT NOT NULL,
        adapter_name TEXT NOT NULL,
        executed_at TEXT NOT NULL,
        fetched_count INTEGER NOT NULL DEFAULT 0,
        emitted_count INTEGER NOT NULL DEFAULT 0,
        duplicate_count INTEGER NOT NULL DEFAULT 0,
        stale_count INTEGER NOT NULL DEFAULT 0,
        max_item_age_seconds INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sentiment_source_failures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        source_id TEXT NOT NULL,
        source_name TEXT NOT NULL,
        category TEXT NOT NULL,
        adapter_name TEXT NOT NULL,
        failed_at TEXT NOT NULL,
        error_code TEXT NOT NULL,
        error_message TEXT NOT NULL,
        retryable INTEGER NOT NULL DEFAULT 0,
        details_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        source TEXT NOT NULL,
        recommendation TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.0,
        market_regime TEXT,
        market_regime_label TEXT,
        confirmation_score REAL,
        sentiment_count INTEGER NOT NULL DEFAULT 0,
        company_match_count INTEGER NOT NULL DEFAULT 0,
        turnover REAL,
        reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS issue_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        issue_type TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'medium',
        status TEXT NOT NULL DEFAULT 'open',
        symbol TEXT,
        source TEXT NOT NULL DEFAULT '',
        origin_worker TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        details_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        occurrence_count INTEGER NOT NULL DEFAULT 1,
        resolved_at TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
            self._ensure_issue_ledger_columns(conn)
            conn.commit()

    def _ensure_issue_ledger_columns(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(issue_ledger)").fetchall()
        }
        column_statements = (
            ("last_seen_at", "ALTER TABLE issue_ledger ADD COLUMN last_seen_at TEXT"),
            (
                "occurrence_count",
                "ALTER TABLE issue_ledger ADD COLUMN occurrence_count INTEGER NOT NULL DEFAULT 1",
            ),
            ("updated_at", "ALTER TABLE issue_ledger ADD COLUMN updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
        )
        for column_name, statement in column_statements:
            if column_name not in columns:
                conn.execute(statement)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
        finally:
            conn.close()


def init_database(path: str) -> Database:
    database = Database(path)
    database.ensure_initialized()
    return database
