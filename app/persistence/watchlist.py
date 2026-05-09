from __future__ import annotations

from dataclasses import dataclass

from app.persistence.db import Database


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
                "工作日 09:30-11:30 / 13:00-15:00",
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
                "工作日 09:30-11:30 / 13:00-15:00",
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
