from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.persistence.db import Database


ALLOWED_SIGNAL_LIFECYCLE_STATUSES = (
    "created",
    "active",
    "confirmed",
    "weakened",
    "invalidated",
    "expired",
)


@dataclass(frozen=True, slots=True)
class SignalLifecycleUpsert:
    symbol: str
    status: str
    reason: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
    last_signal_at: str


@dataclass(frozen=True, slots=True)
class SignalLifecycleRow:
    symbol: str
    status: str
    reason: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
    last_signal_at: str


class SignalLifecycleRepository:
    def __init__(self, database: Database):
        self.database = database

    def upsert(
        self,
        *,
        symbol: str,
        status: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
        signal_at: str | datetime | None = None,
        updated_at: str | datetime | None = None,
        created_at: str | datetime | None = None,
    ) -> SignalLifecycleRow:
        normalized_symbol = symbol.strip()
        if not normalized_symbol:
            raise ValueError("symbol is required")

        normalized_status = status.strip().lower()
        if normalized_status not in ALLOWED_SIGNAL_LIFECYCLE_STATUSES:
            raise ValueError(f"unsupported signal lifecycle status: {status!r}")

        effective_signal_at = self._coerce_timestamp(signal_at or updated_at or created_at)
        effective_updated_at = self._coerce_timestamp(updated_at or signal_at or created_at)
        effective_created_at = self._coerce_timestamp(created_at or signal_at or updated_at)
        metadata_payload = dict(metadata or {})
        normalized_reason = reason.strip()

        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO signal_lifecycle (
                    symbol, status, reason, metadata_json, created_at, updated_at, last_signal_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    status = excluded.status,
                    reason = excluded.reason,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    last_signal_at = excluded.last_signal_at
                """,
                (
                    normalized_symbol,
                    normalized_status,
                    normalized_reason,
                    json.dumps(metadata_payload, ensure_ascii=False, sort_keys=True),
                    effective_created_at,
                    effective_updated_at,
                    effective_signal_at,
                ),
            )
            conn.commit()

        row = self.get(normalized_symbol)
        if row is None:
            raise RuntimeError("failed to read signal lifecycle after upsert")
        return row

    def get(self, symbol: str) -> SignalLifecycleRow | None:
        normalized_symbol = symbol.strip()
        if not normalized_symbol:
            return None

        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT symbol, status, reason, metadata_json, created_at, updated_at, last_signal_at
                FROM signal_lifecycle
                WHERE symbol = ?
                LIMIT 1
                """,
                (normalized_symbol,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_model(row)

    def list_rows(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[SignalLifecycleRow]:
        normalized_status = status.strip().lower() if status else None
        if normalized_status is not None and normalized_status not in ALLOWED_SIGNAL_LIFECYCLE_STATUSES:
            raise ValueError(f"unsupported signal lifecycle status: {status!r}")

        query = """
            SELECT symbol, status, reason, metadata_json, created_at, updated_at, last_signal_at
            FROM signal_lifecycle
        """
        parameters: tuple[object, ...]
        if normalized_status is not None:
            query += " WHERE status = ?"
            parameters = (normalized_status, limit)
        else:
            parameters = (limit,)
        query += " ORDER BY last_signal_at DESC, symbol ASC LIMIT ?"

        with self.database.connection() as conn:
            rows = conn.execute(query, parameters).fetchall()
        return [self._row_to_model(row) for row in rows]

    def _row_to_model(self, row) -> SignalLifecycleRow:
        return SignalLifecycleRow(
            symbol=row["symbol"],
            status=row["status"],
            reason=row["reason"],
            metadata=dict(json.loads(row["metadata_json"])),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_signal_at=row["last_signal_at"],
        )

    def _coerce_timestamp(self, value: str | datetime | None) -> str:
        if value is None:
            return datetime.utcnow().isoformat()
        if isinstance(value, datetime):
            return value.isoformat()
        normalized = value.strip()
        if not normalized:
            raise ValueError("timestamp cannot be empty")
        return normalized

