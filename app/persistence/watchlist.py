from __future__ import annotations

from dataclasses import dataclass

from app.persistence.db import Database


DEFAULT_SCHEDULE_LABEL = "工作日 09:30-11:30 / 13:00-15:00"
DEFAULT_STATUS_LABEL = "监控中"
DISABLED_STATUS_LABEL = "未开启"
DEFAULT_LATEST_REASON = "等待首次分析。"


@dataclass(frozen=True, slots=True)
class WatchlistRow:
    symbol: str
    name: str
    monitoring_enabled: bool
    use_default_schedule: bool
    schedule_label: str
    status: str
    status_label: str
    latest_recommendation: str
    latest_confidence: float
    latest_reason: str
    last_analysis_at: str | None


class WatchlistRepository:
    def __init__(self, database: Database):
        self.database = database

    def seed_defaults(self) -> None:
        defaults = (
            (
                "600519",
                "贵州茅台",
                1,
                1,
                DEFAULT_SCHEDULE_LABEL,
                "active",
                "监控中",
                "buy",
                0.78,
                "趋势延续，消费龙头情绪稳定，量价结构未破坏。",
                "10:28",
            ),
            (
                "300750",
                "宁德时代",
                1,
                1,
                DEFAULT_SCHEDULE_LABEL,
                "paused",
                "闭市暂停",
                "watch",
                0.55,
                "波动放大，等待新的趋势确认，暂不追价。",
                "15:01",
            ),
            (
                "688981",
                "中芯国际",
                0,
                0,
                "自定义关闭",
                "disabled",
                "未开启",
                "avoid",
                0.41,
                "当前监控关闭，仅保留上次建议记录。",
                "09:12",
            ),
        )
        with self.database.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM watchlist_stocks").fetchone()[0]
            if count > 0:
                return
            conn.executemany(
                """
                INSERT INTO watchlist_stocks (
                    symbol, name, monitoring_enabled, use_default_schedule, schedule_label,
                    status, status_label, latest_recommendation, latest_confidence,
                    latest_reason, last_analysis_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                defaults,
            )
            conn.commit()

    def list_rows(self) -> list[WatchlistRow]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, name, monitoring_enabled, use_default_schedule, schedule_label,
                       status, status_label, latest_recommendation, latest_confidence,
                       latest_reason, last_analysis_at
                FROM watchlist_stocks
                ORDER BY monitoring_enabled DESC, symbol ASC
                """
            ).fetchall()
        return [
            WatchlistRow(
                symbol=row["symbol"],
                name=row["name"],
                monitoring_enabled=bool(row["monitoring_enabled"]),
                use_default_schedule=bool(row["use_default_schedule"]),
                schedule_label=row["schedule_label"],
                status=row["status"],
                status_label=row["status_label"],
                latest_recommendation=row["latest_recommendation"],
                latest_confidence=float(row["latest_confidence"]),
                latest_reason=row["latest_reason"],
                last_analysis_at=row["last_analysis_at"],
            )
            for row in rows
        ]

    def create_stock(self, symbol: str, name: str) -> bool:
        symbol = symbol.strip()
        name = name.strip()
        if not symbol or not name:
            return False

        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO watchlist_stocks (
                    symbol, name, monitoring_enabled, use_default_schedule, schedule_label,
                    status, status_label, latest_recommendation, latest_confidence,
                    latest_reason, last_analysis_at
                ) VALUES (?, ?, 1, 1, ?, 'active', ?, 'watch', 0.0, ?, NULL)
                ON CONFLICT(symbol) DO UPDATE SET
                    name = excluded.name,
                    monitoring_enabled = 1,
                    use_default_schedule = 1,
                    schedule_label = excluded.schedule_label,
                    status = excluded.status,
                    status_label = excluded.status_label,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (symbol, name, DEFAULT_SCHEDULE_LABEL, DEFAULT_STATUS_LABEL, DEFAULT_LATEST_REASON),
            )
            conn.commit()
        return cursor.rowcount > 0

    def delete_stock(self, symbol: str) -> bool:
        symbol = symbol.strip()
        if not symbol:
            return False

        with self.database.connection() as conn:
            cursor = conn.execute("DELETE FROM watchlist_stocks WHERE symbol = ?", (symbol,))
            conn.commit()
        return cursor.rowcount > 0

    def toggle_stock_monitoring(self, symbol: str) -> bool:
        symbol = symbol.strip()
        if not symbol:
            return False

        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE watchlist_stocks
                SET monitoring_enabled = CASE monitoring_enabled WHEN 1 THEN 0 ELSE 1 END,
                    status = CASE monitoring_enabled WHEN 1 THEN 'disabled' ELSE 'active' END,
                    status_label = CASE monitoring_enabled WHEN 1 THEN ? ELSE ? END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE symbol = ?
                """,
                (DISABLED_STATUS_LABEL, DEFAULT_STATUS_LABEL, symbol),
            )
            conn.commit()
        return cursor.rowcount > 0

    def record_refresh(
        self,
        symbol: str,
        *,
        latest_recommendation: str,
        latest_confidence: float,
        latest_reason: str,
        status: str,
        status_label: str,
        last_analysis_at: str | None,
    ) -> bool:
        symbol = symbol.strip()
        if not symbol:
            return False

        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE watchlist_stocks
                SET latest_recommendation = ?,
                    latest_confidence = ?,
                    latest_reason = ?,
                    status = ?,
                    status_label = ?,
                    last_analysis_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE symbol = ?
                """,
                (
                    latest_recommendation,
                    latest_confidence,
                    latest_reason,
                    status,
                    status_label,
                    last_analysis_at,
                    symbol,
                ),
            )
            conn.commit()
        return cursor.rowcount > 0
