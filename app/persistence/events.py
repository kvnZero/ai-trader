from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from app.persistence.db import Database


@dataclass(frozen=True, slots=True)
class MarketEventRow:
    symbol: str | None
    title: str
    event_type: str
    severity: str
    event_date: str
    source: str
    details: dict[str, object]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class MarketEventStatsRow:
    key: str
    count: int


@dataclass(frozen=True, slots=True)
class MarketEventStatsReport:
    generated_at: str
    total_count: int
    severity_counts: list[MarketEventStatsRow]
    type_counts: list[MarketEventStatsRow]
    symbol_counts: list[MarketEventStatsRow]


class MarketEventRepository:
    def __init__(self, database: Database):
        self.database = database

    def upsert_event(
        self,
        *,
        symbol: str | None,
        title: str,
        event_type: str,
        severity: str,
        event_date: str,
        source: str,
        details: dict[str, object] | None = None,
    ) -> bool:
        natural_key = self._build_natural_key(
            symbol=symbol,
            title=title,
            event_type=event_type,
            event_date=event_date,
        )
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO market_events (
                    natural_key, symbol, title, event_type, severity, event_date, source, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(natural_key) DO UPDATE SET
                    severity = excluded.severity,
                    source = excluded.source,
                    details_json = excluded.details_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    natural_key,
                    symbol,
                    title,
                    event_type,
                    severity,
                    event_date,
                    source,
                    json.dumps(details or {}, ensure_ascii=False, default=str),
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    def list_recent(self, *, limit: int = 20, symbol: str | None = None) -> list[MarketEventRow]:
        query = """
            SELECT symbol, title, event_type, severity, event_date, source, details_json, created_at, updated_at
            FROM market_events
        """
        parameters: tuple[object, ...]
        if symbol:
            query += " WHERE symbol = ?"
            parameters = (symbol.strip(), limit)
        else:
            parameters = (limit,)
        query += " ORDER BY event_date DESC, id DESC LIMIT ?"
        with self.database.connection() as conn:
            rows = conn.execute(query, parameters).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_upcoming(self, *, limit: int = 20, symbol: str | None = None) -> list[MarketEventRow]:
        query = """
            SELECT symbol, title, event_type, severity, event_date, source, details_json, created_at, updated_at
            FROM market_events
            WHERE event_date >= date('now')
        """
        parameters: tuple[object, ...]
        if symbol:
            query += " AND symbol = ?"
            parameters = (symbol.strip(), limit)
        else:
            parameters = (limit,)
        query += " ORDER BY event_date ASC, id DESC LIMIT ?"
        with self.database.connection() as conn:
            rows = conn.execute(query, parameters).fetchall()
        return [self._row_to_event(row) for row in rows]

    def build_stats_report(
        self,
        *,
        symbol: str | None = None,
        event_type: str | None = None,
        severity: str | None = None,
        generated_at: datetime | None = None,
    ) -> MarketEventStatsReport:
        where_clause, parameters = self._build_filters(
            symbol=symbol,
            event_type=event_type,
            severity=severity,
        )
        with self.database.connection() as conn:
            total_count = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM market_events{where_clause}",
                    parameters,
                ).fetchone()[0]
            )
            severity_counts = self._fetch_group_counts(
                conn,
                group_field="severity",
                where_clause=where_clause,
                parameters=parameters,
            )
            type_counts = self._fetch_group_counts(
                conn,
                group_field="event_type",
                where_clause=where_clause,
                parameters=parameters,
            )
            symbol_counts = self._fetch_group_counts(
                conn,
                group_field="symbol",
                where_clause=where_clause,
                parameters=parameters,
                exclude_null=True,
            )

        timestamp = (generated_at or datetime.now(UTC)).isoformat(timespec="minutes")
        return MarketEventStatsReport(
            generated_at=timestamp,
            total_count=total_count,
            severity_counts=severity_counts,
            type_counts=type_counts,
            symbol_counts=symbol_counts,
        )

    def _row_to_event(self, row) -> MarketEventRow:
        return MarketEventRow(
            symbol=row["symbol"],
            title=row["title"],
            event_type=row["event_type"],
            severity=row["severity"],
            event_date=row["event_date"],
            source=row["source"],
            details=dict(json.loads(row["details_json"])),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _build_filters(
        self,
        *,
        symbol: str | None,
        event_type: str | None,
        severity: str | None,
    ) -> tuple[str, tuple[object, ...]]:
        clauses: list[str] = []
        parameters: list[object] = []
        if symbol:
            clauses.append("symbol = ?")
            parameters.append(symbol.strip())
        if event_type:
            clauses.append("event_type = ?")
            parameters.append(event_type.strip())
        if severity:
            clauses.append("severity = ?")
            parameters.append(severity.strip())
        if not clauses:
            return "", ()
        return f" WHERE {' AND '.join(clauses)}", tuple(parameters)

    def _fetch_group_counts(
        self,
        conn,
        *,
        group_field: str,
        where_clause: str,
        parameters: tuple[object, ...],
        exclude_null: bool = False,
    ) -> list[MarketEventStatsRow]:
        effective_where = where_clause
        if exclude_null:
            effective_where = (
                f"{where_clause} AND COALESCE({group_field}, '') <> ''"
                if where_clause
                else f" WHERE COALESCE({group_field}, '') <> ''"
            )
        rows = conn.execute(
            f"""
            SELECT {group_field} AS group_key, COUNT(*) AS event_count
            FROM market_events
            {effective_where}
            GROUP BY {group_field}
            ORDER BY event_count DESC, group_key ASC
            """,
            parameters,
        ).fetchall()
        return [
            MarketEventStatsRow(
                key=str(row["group_key"]),
                count=int(row["event_count"]),
            )
            for row in rows
        ]

    def _build_natural_key(
        self,
        *,
        symbol: str | None,
        title: str,
        event_type: str,
        event_date: str,
    ) -> str:
        return hashlib.sha256(
            "|".join([symbol or "", event_type, event_date, title]).encode("utf-8")
        ).hexdigest()
