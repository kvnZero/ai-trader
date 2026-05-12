from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from app.persistence.db import Database


@dataclass(frozen=True, slots=True)
class IssueLedgerRow:
    id: int
    issue_type: str
    severity: str
    status: str
    symbol: str | None
    source: str
    origin_worker: str
    message: str
    details: dict[str, object]
    created_at: str
    resolved_at: str | None


class IssueLedgerRepository:
    def __init__(self, database: Database):
        self.database = database

    def create_issue(
        self,
        *,
        issue_type: str,
        severity: str = "medium",
        status: str = "open",
        symbol: str | None = None,
        source: str = "",
        origin_worker: str = "",
        message: str = "",
        details: dict[str, object] | None = None,
        created_at: datetime | str | None = None,
        resolved_at: datetime | str | None = None,
    ) -> bool:
        created_value = self._format_datetime(created_at or datetime.now(UTC))
        resolved_value = self._format_datetime(resolved_at)
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO issue_ledger (
                    issue_type, severity, status, symbol, source, origin_worker,
                    message, details_json, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    issue_type,
                    severity,
                    status,
                    symbol,
                    source,
                    origin_worker,
                    message,
                    json.dumps(details or {}, ensure_ascii=False, default=str),
                    created_value,
                    resolved_value,
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    def resolve_issue(self, issue_id: int, *, resolved_at: datetime | str | None = None) -> bool:
        return self._set_status(issue_id, status="resolved", resolved_at=resolved_at)

    def ignore_issue(self, issue_id: int, *, resolved_at: datetime | str | None = None) -> bool:
        return self._set_status(issue_id, status="ignored", resolved_at=resolved_at)

    def list_recent(
        self,
        *,
        limit: int = 20,
        symbol: str | None = None,
        issue_type: str | None = None,
        severity: str | None = None,
        status: str | None = None,
    ) -> list[IssueLedgerRow]:
        query = """
            SELECT id, issue_type, severity, status, symbol, source, origin_worker,
                   message, details_json, created_at, resolved_at
            FROM issue_ledger
        """
        clauses: list[str] = []
        parameters: list[object] = []
        if symbol:
            clauses.append("symbol = ?")
            parameters.append(symbol.strip())
        if issue_type:
            clauses.append("issue_type = ?")
            parameters.append(issue_type)
        if severity:
            clauses.append("severity = ?")
            parameters.append(severity)
        if status:
            clauses.append("status = ?")
            parameters.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        parameters.append(limit)

        with self.database.connection() as conn:
            rows = conn.execute(query, tuple(parameters)).fetchall()
        return [self._row_to_issue(row) for row in rows]

    def count_open(self) -> int:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM issue_ledger WHERE status = 'open'",
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def _set_status(
        self,
        issue_id: int,
        *,
        status: str,
        resolved_at: datetime | str | None = None,
    ) -> bool:
        resolved_value = self._format_datetime(resolved_at or datetime.now(UTC))
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE issue_ledger
                SET status = ?,
                    resolved_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'open'
                """,
                (status, resolved_value, issue_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def _row_to_issue(self, row) -> IssueLedgerRow:
        return IssueLedgerRow(
            id=int(row["id"]),
            issue_type=row["issue_type"],
            severity=row["severity"],
            status=row["status"],
            symbol=row["symbol"],
            source=row["source"],
            origin_worker=row["origin_worker"],
            message=row["message"],
            details=dict(json.loads(row["details_json"])),
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    def _format_datetime(self, value: datetime | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat(timespec="minutes")
        return str(value)
