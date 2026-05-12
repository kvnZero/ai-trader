from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

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
