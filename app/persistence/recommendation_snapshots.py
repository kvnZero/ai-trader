from __future__ import annotations

from dataclasses import dataclass

from app.persistence.db import Database


@dataclass(frozen=True, slots=True)
class RecommendationSnapshotRow:
    symbol: str
    source: str
    recommendation: str
    confidence: float
    market_regime: str | None
    market_regime_label: str | None
    confirmation_score: float | None
    sentiment_count: int
    company_match_count: int
    turnover: float | None
    reason: str
    created_at: str


class RecommendationSnapshotRepository:
    def __init__(self, database: Database):
        self.database = database

    def create_snapshot(
        self,
        *,
        symbol: str,
        source: str,
        recommendation: str,
        confidence: float,
        market_regime: str | None,
        market_regime_label: str | None,
        confirmation_score: float | None,
        sentiment_count: int,
        company_match_count: int,
        turnover: float | None,
        reason: str,
        created_at: str,
    ) -> bool:
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO recommendation_snapshots (
                    symbol, source, recommendation, confidence, market_regime,
                    market_regime_label, confirmation_score, sentiment_count,
                    company_match_count, turnover, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    source,
                    recommendation,
                    confidence,
                    market_regime,
                    market_regime_label,
                    confirmation_score,
                    sentiment_count,
                    company_match_count,
                    turnover,
                    reason,
                    created_at,
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    def list_recent(
        self,
        *,
        limit: int = 20,
        symbol: str | None = None,
    ) -> list[RecommendationSnapshotRow]:
        query = """
            SELECT symbol, source, recommendation, confidence, market_regime,
                   market_regime_label, confirmation_score, sentiment_count,
                   company_match_count, turnover, reason, created_at
            FROM recommendation_snapshots
        """
        parameters: tuple[object, ...]
        if symbol:
            query += " WHERE symbol = ?"
            parameters = (symbol.strip(), limit)
        else:
            parameters = (limit,)
        query += " ORDER BY id DESC LIMIT ?"

        with self.database.connection() as conn:
            rows = conn.execute(query, parameters).fetchall()
        return [
            RecommendationSnapshotRow(
                symbol=row["symbol"],
                source=row["source"],
                recommendation=row["recommendation"],
                confidence=float(row["confidence"]),
                market_regime=row["market_regime"],
                market_regime_label=row["market_regime_label"],
                confirmation_score=(
                    float(row["confirmation_score"])
                    if row["confirmation_score"] is not None
                    else None
                ),
                sentiment_count=int(row["sentiment_count"]),
                company_match_count=int(row["company_match_count"]),
                turnover=float(row["turnover"]) if row["turnover"] is not None else None,
                reason=row["reason"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
