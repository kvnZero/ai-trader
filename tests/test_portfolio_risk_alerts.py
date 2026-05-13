from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app.config import Settings
from app.monitoring.refresh import RefreshOutcome, WatchlistRefreshService
from app.persistence import (
    AlertRepository,
    IssueLedgerRepository,
    PortfolioHoldingRepository,
    RecommendationEventRepository,
    WatchlistRepository,
    init_database,
)
from app.persistence.watchlist import WatchlistRow
from app.workers.events import _persist_portfolio_event_risk_alerts


class PortfolioRiskAlertTests(TestCase):
    def test_events_worker_creates_portfolio_risk_alert_for_held_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "portfolio-risk-events.db"))
            holding_repository = PortfolioHoldingRepository(database)
            holding_repository.upsert_holding(
                symbol="600519",
                name="贵州茅台",
                shares=100,
                avg_cost=1500.0,
                last_price=1600.0,
            )
            alert_repository = AlertRepository(database)
            issue_repository = IssueLedgerRepository(database)

            created_count = _persist_portfolio_event_risk_alerts(
                holding_repository=holding_repository,
                alert_repository=alert_repository,
                issue_repository=issue_repository,
                events=[
                    {
                        "symbol": "600519",
                        "title": "贵州茅台 停复牌提醒",
                        "event_type": "suspension_resume",
                        "severity": "high",
                        "event_date": "2026-05-13",
                        "source": "baidu_trade_calendar",
                        "details": {"detail": "重大事项停牌"},
                    }
                ],
            )

            alerts = alert_repository.list_unread()
            issues = issue_repository.list_recent(limit=10)
            self.assertEqual(created_count, 1)
            self.assertTrue(any("持仓风险事件" in item.title for item in alerts))
            self.assertTrue(any(item.issue_type == "portfolio_market_event_high_risk" for item in issues))

    def test_refresh_service_escalates_invalidated_held_symbol_and_open_high_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "portfolio-risk-refresh.db"))
            settings = Settings(database_path=str(Path(tmpdir) / "portfolio-risk-refresh.db"))
            watchlist_repository = WatchlistRepository(database)
            alert_repository = AlertRepository(database)
            issue_repository = IssueLedgerRepository(database)
            recommendation_event_repository = RecommendationEventRepository(database)
            holding_repository = PortfolioHoldingRepository(database)
            holding_repository.upsert_holding(
                symbol="600519",
                name="贵州茅台",
                shares=100,
                avg_cost=1500.0,
                last_price=1600.0,
            )
            issue_repository.create_issue(
                issue_type="market_data_unavailable",
                severity="high",
                status="open",
                symbol="600519",
                source="monitoring_refresh",
                origin_worker="monitoring_worker",
                message="行情不可用",
                details={},
            )

            service = WatchlistRefreshService(
                settings=settings,
                watchlist_repository=watchlist_repository,
                alert_repository=alert_repository,
                issue_repository=issue_repository,
                recommendation_event_repository=recommendation_event_repository,
            )
            row = WatchlistRow(
                symbol="600519",
                name="贵州茅台",
                monitoring_enabled=True,
                use_default_schedule=True,
                schedule_label="工作日",
                status="active",
                status_label="监控中",
                latest_recommendation="buy",
                latest_confidence=0.7,
                latest_reason="趋势延续",
                last_analysis_at="10:30",
            )
            outcome = RefreshOutcome(
                symbol="600519",
                changed=False,
                recommendation="watch",
                confidence=0.3,
                reason="信号失效，转入观察。",
                lifecycle_state="invalidated",
                lifecycle_reason="关键趋势结构已破坏。",
                status="active",
                status_label="监控中",
                analysis_at="10:35",
                alert_created=False,
                source="scheduled",
            )

            service._record_portfolio_risk_escalations(
                row=row,
                outcome=outcome,
                source="scheduled",
            )

            alerts = alert_repository.list_unread()
            issues = issue_repository.list_recent(limit=10, symbol="600519")
            self.assertTrue(any("持仓信号风险" in item.title for item in alerts))
            self.assertTrue(any("持仓高优问题未处理" in item.title for item in alerts))
            self.assertTrue(any(item.issue_type == "portfolio_signal_invalidated" for item in issues))
            self.assertTrue(any(item.issue_type == "portfolio_open_high_issues" for item in issues))


if __name__ == "__main__":
    import unittest

    unittest.main()
