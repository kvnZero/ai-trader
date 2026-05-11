from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from app.domain import SentimentItem
from app.modules.sentiment_ingestion.contracts import SentimentIngestionResult
from app.persistence.db import Database


DEFAULT_SENTIMENT_WORKER_NAME = "sentiment_worker"


@dataclass(frozen=True, slots=True)
class SentimentWorkerStateRow:
    worker_name: str
    status: str
    last_started_at: str | None
    last_completed_at: str | None
    last_success_at: str | None
    last_heartbeat_at: str | None
    latest_item_published_at: str | None
    last_run_id: int | None
    item_count: int
    source_run_count: int
    failure_count: int
    duplicate_count: int
    stale_count: int
    error_message: str


@dataclass(frozen=True, slots=True)
class SentimentIngestionRunRow:
    id: int
    worker_name: str
    status: str
    started_at: str
    completed_at: str | None
    heartbeat_at: str | None
    item_count: int
    source_run_count: int
    failure_count: int
    duplicate_count: int
    stale_count: int
    error_message: str


@dataclass(frozen=True, slots=True)
class SentimentItemRow:
    dedup_key: str
    run_id: int
    source_id: str
    source_name: str
    category: str
    adapter_name: str
    title: str
    content: str
    published_at: str
    collected_at: str
    ingested_at: str
    url: str | None
    sentiment_score: float | None
    tags: list[str]
    raw_reference: str | None
    source_item_id: str | None
    age_seconds: int
    raw_payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class SentimentSourceRunRow:
    source_id: str
    source_name: str
    category: str
    adapter_name: str
    executed_at: str
    fetched_count: int
    emitted_count: int
    duplicate_count: int
    stale_count: int
    max_item_age_seconds: int | None


@dataclass(frozen=True, slots=True)
class SentimentSourceFailureRow:
    source_id: str
    source_name: str
    category: str
    adapter_name: str
    failed_at: str
    error_code: str
    error_message: str
    retryable: bool
    details: dict[str, object]


class SentimentRepository:
    def __init__(self, database: Database, *, worker_name: str = DEFAULT_SENTIMENT_WORKER_NAME):
        self.database = database
        self.worker_name = worker_name

    def start_run(
        self,
        *,
        started_at: datetime,
        lease_seconds: int = 900,
    ) -> int | None:
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            state = conn.execute(
                """
                SELECT status, last_heartbeat_at
                FROM sentiment_worker_state
                WHERE worker_name = ?
                """,
                (self.worker_name,),
            ).fetchone()
            if state is not None and state["status"] == "running":
                last_heartbeat_at = self._parse_datetime(state["last_heartbeat_at"])
                if (
                    last_heartbeat_at is not None
                    and (started_at - last_heartbeat_at).total_seconds() < lease_seconds
                ):
                    conn.rollback()
                    return None

            cursor = conn.execute(
                """
                INSERT INTO sentiment_ingestion_runs (
                    worker_name, status, started_at, heartbeat_at
                ) VALUES (?, 'running', ?, ?)
                """,
                (self.worker_name, self._format_datetime(started_at), self._format_datetime(started_at)),
            )
            run_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO sentiment_worker_state (
                    worker_name, status, last_started_at, last_heartbeat_at, last_run_id, error_message
                ) VALUES (?, 'running', ?, ?, ?, '')
                ON CONFLICT(worker_name) DO UPDATE SET
                    status = excluded.status,
                    last_started_at = excluded.last_started_at,
                    last_heartbeat_at = excluded.last_heartbeat_at,
                    last_run_id = excluded.last_run_id,
                    error_message = excluded.error_message,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    self.worker_name,
                    self._format_datetime(started_at),
                    self._format_datetime(started_at),
                    run_id,
                ),
            )
            conn.commit()
        return run_id

    def record_heartbeat(self, *, run_id: int | None, heartbeat_at: datetime) -> None:
        heartbeat_value = self._format_datetime(heartbeat_at)
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if run_id is not None:
                conn.execute(
                    """
                    UPDATE sentiment_ingestion_runs
                    SET heartbeat_at = ?
                    WHERE id = ?
                    """,
                    (heartbeat_value, run_id),
                )
            conn.execute(
                """
                INSERT INTO sentiment_worker_state (
                    worker_name, status, last_heartbeat_at, last_run_id
                ) VALUES (?, 'idle', ?, ?)
                ON CONFLICT(worker_name) DO UPDATE SET
                    last_heartbeat_at = excluded.last_heartbeat_at,
                    last_run_id = COALESCE(excluded.last_run_id, sentiment_worker_state.last_run_id),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (self.worker_name, heartbeat_value, run_id),
            )
            conn.commit()

    def record_success(
        self,
        *,
        run_id: int,
        result: SentimentIngestionResult,
        completed_at: datetime,
        keep_recent_items: int = 200,
    ) -> None:
        completed_value = self._format_datetime(completed_at)
        latest_item_published_at = max(
            (record.item.published_at for record in result.records),
            default=None,
        )
        item_count = len(result.records)
        source_run_count = len(result.source_runs)
        failure_count = len(result.source_failures)
        duplicate_count = len(result.duplicate_records)
        stale_count = len(result.stale_records)
        status = "degraded" if failure_count else "succeeded"

        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._persist_items(conn, run_id=run_id, result=result, completed_at=completed_value)
            self._persist_source_runs(conn, run_id=run_id, result=result)
            self._persist_source_failures(conn, run_id=run_id, result=result)
            conn.execute(
                """
                UPDATE sentiment_ingestion_runs
                SET status = ?,
                    completed_at = ?,
                    heartbeat_at = ?,
                    item_count = ?,
                    source_run_count = ?,
                    failure_count = ?,
                    duplicate_count = ?,
                    stale_count = ?,
                    error_message = ''
                WHERE id = ?
                """,
                (
                    status,
                    completed_value,
                    completed_value,
                    item_count,
                    source_run_count,
                    failure_count,
                    duplicate_count,
                    stale_count,
                    run_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO sentiment_worker_state (
                    worker_name, status, last_completed_at, last_success_at, last_heartbeat_at,
                    latest_item_published_at, last_run_id, item_count, source_run_count,
                    failure_count, duplicate_count, stale_count, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                ON CONFLICT(worker_name) DO UPDATE SET
                    status = excluded.status,
                    last_completed_at = excluded.last_completed_at,
                    last_success_at = excluded.last_success_at,
                    last_heartbeat_at = excluded.last_heartbeat_at,
                    latest_item_published_at = excluded.latest_item_published_at,
                    last_run_id = excluded.last_run_id,
                    item_count = excluded.item_count,
                    source_run_count = excluded.source_run_count,
                    failure_count = excluded.failure_count,
                    duplicate_count = excluded.duplicate_count,
                    stale_count = excluded.stale_count,
                    error_message = excluded.error_message,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    self.worker_name,
                    status,
                    completed_value,
                    completed_value,
                    completed_value,
                    self._format_datetime(latest_item_published_at) if latest_item_published_at else None,
                    run_id,
                    item_count,
                    source_run_count,
                    failure_count,
                    duplicate_count,
                    stale_count,
                ),
            )
            self._prune_items(conn, keep_recent_items=keep_recent_items)
            conn.commit()

    def record_failure(
        self,
        *,
        run_id: int,
        failed_at: datetime,
        error_message: str,
    ) -> None:
        failed_value = self._format_datetime(failed_at)
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE sentiment_ingestion_runs
                SET status = 'failed',
                    completed_at = ?,
                    heartbeat_at = ?,
                    error_message = ?
                WHERE id = ?
                """,
                (failed_value, failed_value, error_message, run_id),
            )
            conn.execute(
                """
                INSERT INTO sentiment_worker_state (
                    worker_name, status, last_completed_at, last_heartbeat_at, last_run_id, error_message
                ) VALUES (?, 'failed', ?, ?, ?, ?)
                ON CONFLICT(worker_name) DO UPDATE SET
                    status = excluded.status,
                    last_completed_at = excluded.last_completed_at,
                    last_heartbeat_at = excluded.last_heartbeat_at,
                    last_run_id = excluded.last_run_id,
                    error_message = excluded.error_message,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (self.worker_name, failed_value, failed_value, run_id, error_message),
            )
            conn.commit()

    def list_recent_items(self, *, limit: int = 50) -> list[SentimentItemRow]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT dedup_key, run_id, source_id, source_name, category, adapter_name,
                       title, content, published_at, collected_at, ingested_at, url,
                       sentiment_score, tags_json, raw_reference, source_item_id,
                       age_seconds, raw_payload_json
                FROM sentiment_items
                ORDER BY ingested_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def list_recent_dedup_keys(self, *, limit: int = 1000) -> list[str]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT dedup_key
                FROM sentiment_items
                ORDER BY ingested_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row["dedup_key"] for row in rows]

    def get_worker_state(self) -> SentimentWorkerStateRow | None:
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT worker_name, status, last_started_at, last_completed_at,
                       last_success_at, last_heartbeat_at, latest_item_published_at,
                       last_run_id, item_count, source_run_count, failure_count,
                       duplicate_count, stale_count, error_message
                FROM sentiment_worker_state
                WHERE worker_name = ?
                LIMIT 1
                """,
                (self.worker_name,),
            ).fetchone()
        if row is None:
            return None
        return SentimentWorkerStateRow(
            worker_name=row["worker_name"],
            status=row["status"],
            last_started_at=row["last_started_at"],
            last_completed_at=row["last_completed_at"],
            last_success_at=row["last_success_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
            latest_item_published_at=row["latest_item_published_at"],
            last_run_id=row["last_run_id"],
            item_count=int(row["item_count"]),
            source_run_count=int(row["source_run_count"]),
            failure_count=int(row["failure_count"]),
            duplicate_count=int(row["duplicate_count"]),
            stale_count=int(row["stale_count"]),
            error_message=row["error_message"],
        )

    def get_latest_run(self) -> SentimentIngestionRunRow | None:
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT id, worker_name, status, started_at, completed_at, heartbeat_at,
                       item_count, source_run_count, failure_count, duplicate_count,
                       stale_count, error_message
                FROM sentiment_ingestion_runs
                WHERE worker_name = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (self.worker_name,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def list_source_runs(self, *, run_id: int) -> list[SentimentSourceRunRow]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT source_id, source_name, category, adapter_name, executed_at,
                       fetched_count, emitted_count, duplicate_count, stale_count,
                       max_item_age_seconds
                FROM sentiment_source_runs
                WHERE run_id = ?
                ORDER BY source_id ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_source_run(row) for row in rows]

    def list_source_failures(self, *, run_id: int) -> list[SentimentSourceFailureRow]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT source_id, source_name, category, adapter_name, failed_at,
                       error_code, error_message, retryable, details_json
                FROM sentiment_source_failures
                WHERE run_id = ?
                ORDER BY source_id ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_source_failure(row) for row in rows]

    def read_latest(self, *, symbols: list[str] | None = None) -> dict[str, object] | None:
        del symbols
        latest_run = self.get_latest_run()
        if latest_run is None:
            return None

        with self.database.connection() as conn:
            item_rows = conn.execute(
                """
                SELECT source_name, title, content, published_at, url,
                       sentiment_score, tags_json, raw_reference
                FROM sentiment_items
                WHERE run_id = ?
                ORDER BY ingested_at DESC, id DESC
                """,
                (latest_run.id,),
            ).fetchall()

        items = [
            SentimentItem(
                source=row["source_name"],
                title=row["title"],
                content=row["content"],
                published_at=self._parse_datetime(row["published_at"]) or datetime.now(),
                url=row["url"],
                sentiment_score=row["sentiment_score"],
                tags=list(json.loads(row["tags_json"])),
                raw_reference=row["raw_reference"],
            )
            for row in item_rows
        ]
        source_runs = self.list_source_runs(run_id=latest_run.id)
        source_failures = self.list_source_failures(run_id=latest_run.id)
        latest_update = (
            latest_run.completed_at
            or latest_run.heartbeat_at
            or latest_run.started_at
        )
        return {
            "updated_at": latest_update,
            "latest_update": latest_update,
            "created_at": latest_update,
            "captured_at": latest_update,
            "items": items,
            "source_runs": source_runs,
            "source_failures": source_failures,
            "duplicate_records": [],
            "stale_records": [],
            "latest_run": latest_run,
        }

    def _persist_items(self, conn, *, run_id: int, result: SentimentIngestionResult, completed_at: str) -> None:
        for record in result.records:
            item = record.item
            conn.execute(
                """
                INSERT INTO sentiment_items (
                    dedup_key, run_id, source_id, source_name, category, adapter_name,
                    title, content, published_at, collected_at, ingested_at, url,
                    sentiment_score, tags_json, raw_reference, source_item_id, age_seconds,
                    raw_payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedup_key) DO UPDATE SET
                    run_id = excluded.run_id,
                    source_id = excluded.source_id,
                    source_name = excluded.source_name,
                    category = excluded.category,
                    adapter_name = excluded.adapter_name,
                    title = excluded.title,
                    content = excluded.content,
                    published_at = excluded.published_at,
                    collected_at = excluded.collected_at,
                    ingested_at = excluded.ingested_at,
                    url = excluded.url,
                    sentiment_score = excluded.sentiment_score,
                    tags_json = excluded.tags_json,
                    raw_reference = excluded.raw_reference,
                    source_item_id = excluded.source_item_id,
                    age_seconds = excluded.age_seconds,
                    raw_payload_json = excluded.raw_payload_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    record.dedup_key,
                    run_id,
                    record.source_metadata.source_id,
                    record.source_metadata.source_name,
                    record.source_metadata.category.value,
                    record.adapter_name,
                    item.title,
                    item.content,
                    self._format_datetime(item.published_at),
                    self._format_datetime(record.collected_at),
                    completed_at,
                    item.url,
                    item.sentiment_score,
                    json.dumps(item.tags, ensure_ascii=False),
                    item.raw_reference,
                    record.source_item_id,
                    record.age_seconds,
                    json.dumps(record.raw_payload, ensure_ascii=False, default=str),
                ),
            )

    def _persist_source_runs(self, conn, *, run_id: int, result: SentimentIngestionResult) -> None:
        for run in result.source_runs:
            conn.execute(
                """
                INSERT INTO sentiment_source_runs (
                    run_id, source_id, source_name, category, adapter_name, executed_at,
                    fetched_count, emitted_count, duplicate_count, stale_count, max_item_age_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    run.source_metadata.source_id,
                    run.source_metadata.source_name,
                    run.source_metadata.category.value,
                    run.adapter_name,
                    self._format_datetime(run.executed_at),
                    run.fetched_count,
                    run.emitted_count,
                    run.duplicate_count,
                    run.stale_count,
                    run.max_item_age_seconds,
                ),
            )

    def _persist_source_failures(self, conn, *, run_id: int, result: SentimentIngestionResult) -> None:
        for failure in result.source_failures:
            conn.execute(
                """
                INSERT INTO sentiment_source_failures (
                    run_id, source_id, source_name, category, adapter_name, failed_at,
                    error_code, error_message, retryable, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    failure.source_metadata.source_id,
                    failure.source_metadata.source_name,
                    failure.source_metadata.category.value,
                    failure.adapter_name,
                    self._format_datetime(failure.failed_at),
                    failure.error_code,
                    failure.error_message,
                    int(failure.retryable),
                    json.dumps(failure.details, ensure_ascii=False, default=str),
                ),
            )

    def _prune_items(self, conn, *, keep_recent_items: int) -> None:
        if keep_recent_items <= 0:
            return
        conn.execute(
            """
            DELETE FROM sentiment_items
            WHERE id NOT IN (
                SELECT id
                FROM sentiment_items
                ORDER BY ingested_at DESC, id DESC
                LIMIT ?
            )
            """,
            (keep_recent_items,),
        )

    def _row_to_run(self, row) -> SentimentIngestionRunRow:
        return SentimentIngestionRunRow(
            id=int(row["id"]),
            worker_name=row["worker_name"],
            status=row["status"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            heartbeat_at=row["heartbeat_at"],
            item_count=int(row["item_count"]),
            source_run_count=int(row["source_run_count"]),
            failure_count=int(row["failure_count"]),
            duplicate_count=int(row["duplicate_count"]),
            stale_count=int(row["stale_count"]),
            error_message=row["error_message"],
        )

    def _row_to_item(self, row) -> SentimentItemRow:
        return SentimentItemRow(
            dedup_key=row["dedup_key"],
            run_id=int(row["run_id"]),
            source_id=row["source_id"],
            source_name=row["source_name"],
            category=row["category"],
            adapter_name=row["adapter_name"],
            title=row["title"],
            content=row["content"],
            published_at=row["published_at"],
            collected_at=row["collected_at"],
            ingested_at=row["ingested_at"],
            url=row["url"],
            sentiment_score=row["sentiment_score"],
            tags=list(json.loads(row["tags_json"])),
            raw_reference=row["raw_reference"],
            source_item_id=row["source_item_id"],
            age_seconds=int(row["age_seconds"]),
            raw_payload=dict(json.loads(row["raw_payload_json"])),
        )

    def _row_to_source_run(self, row) -> SentimentSourceRunRow:
        return SentimentSourceRunRow(
            source_id=row["source_id"],
            source_name=row["source_name"],
            category=row["category"],
            adapter_name=row["adapter_name"],
            executed_at=row["executed_at"],
            fetched_count=int(row["fetched_count"]),
            emitted_count=int(row["emitted_count"]),
            duplicate_count=int(row["duplicate_count"]),
            stale_count=int(row["stale_count"]),
            max_item_age_seconds=row["max_item_age_seconds"],
        )

    def _row_to_source_failure(self, row) -> SentimentSourceFailureRow:
        return SentimentSourceFailureRow(
            source_id=row["source_id"],
            source_name=row["source_name"],
            category=row["category"],
            adapter_name=row["adapter_name"],
            failed_at=row["failed_at"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            retryable=bool(row["retryable"]),
            details=dict(json.loads(row["details_json"])),
        )

    def _format_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat()

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value)
