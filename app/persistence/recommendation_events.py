from __future__ import annotations

from dataclasses import dataclass

from app.persistence.db import Database


@dataclass(frozen=True, slots=True)
class RecommendationEventRow:
    symbol: str
    previous_action: str | None
    current_action: str
    confidence: float
    summary: str
    created_at: str


class RecommendationEventRepository:
    def __init__(self, database: Database):
        self.database = database

    def create_event(
        self,
        *,
        symbol: str,
        previous_action: str | None,
        current_action: str,
        confidence: float,
        summary: str,
    ) -> bool:
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO recommendation_events (
                    symbol, previous_action, current_action, confidence, summary
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (symbol, previous_action, current_action, confidence, summary),
            )
            conn.commit()
        return cursor.rowcount > 0

    def list_recent(self, limit: int = 8, *, symbol: str | None = None) -> list[RecommendationEventRow]:
        parameters: tuple[object, ...]
        query = """
            SELECT symbol, previous_action, current_action, confidence, summary, created_at
            FROM recommendation_events
        """
        if symbol:
            query += " WHERE symbol = ?"
            parameters = (symbol.strip(), limit)
        else:
            parameters = (limit,)
        query += " ORDER BY id DESC LIMIT ?"
        with self.database.connection() as conn:
            rows = conn.execute(query, parameters).fetchall()
        return [
            RecommendationEventRow(
                symbol=row["symbol"],
                previous_action=row["previous_action"],
                current_action=row["current_action"],
                confidence=float(row["confidence"]),
                summary=row["summary"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
