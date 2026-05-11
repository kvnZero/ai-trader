from __future__ import annotations

from dataclasses import dataclass

from app.persistence.db import Database


@dataclass(frozen=True, slots=True)
class AlertRow:
    id: int
    symbol: str
    title: str
    summary: str
    level: str
    unread: bool
    created_at: str


class AlertRepository:
    def __init__(self, database: Database):
        self.database = database

    def _row_to_alert(self, row) -> AlertRow:
        return AlertRow(
            id=int(row["id"]),
            symbol=row["symbol"],
            title=row["title"],
            summary=row["summary"],
            level=row["level"],
            unread=bool(row["unread"]),
            created_at=row["created_at"],
        )

    def seed_defaults(self) -> None:
        defaults = (
            (
                "600519",
                "贵州茅台建议从 WATCH 调整为 BUY",
                "技术结构重新转强，舆情面没有新增利空。",
                "high",
                1,
            ),
            (
                "002594",
                "比亚迪舆情热度上升",
                "快讯密度提升，但建议尚未变更。",
                "medium",
                1,
            ),
        )
        with self.database.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
            if count > 0:
                return
            conn.executemany(
                """
                INSERT INTO alerts (symbol, title, summary, level, unread)
                VALUES (?, ?, ?, ?, ?)
                """,
                defaults,
            )
            conn.commit()

    def list_unread(self) -> list[AlertRow]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, title, summary, level, unread, created_at
                FROM alerts
                WHERE unread = 1
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        return [self._row_to_alert(row) for row in rows]

    def mark_read(self, alert_id: int) -> bool:
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE alerts
                SET unread = 0,
                    read_at = CURRENT_TIMESTAMP
                WHERE id = ? AND unread = 1
                """,
                (alert_id,),
            )
            conn.commit()
        return cursor.rowcount > 0

    def mark_all_read(self) -> int:
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE alerts
                SET unread = 0,
                    read_at = CURRENT_TIMESTAMP
                WHERE unread = 1
                """
            )
            conn.commit()
        return cursor.rowcount
