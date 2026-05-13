from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app import create_app
from app.routes import _build_recommendations_workspace
from app.persistence import (
    AlertRepository,
    IssueLedgerRepository,
    MarketEventRepository,
    PortfolioCashRepository,
    PortfolioHoldingRepository,
    PortfolioSettingsRepository,
    RecommendationEventRepository,
    RecommendationSnapshotRepository,
    SignalLifecycleRepository,
    WatchlistRepository,
    init_database,
)


class PortfolioRebalanceWorkspaceTests(TestCase):
    def test_recommendations_workspace_includes_rebalance_playbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "portfolio-rebalance-view.db"))
            watchlist_repository = WatchlistRepository(database)
            holding_repository = PortfolioHoldingRepository(database)
            cash_repository = PortfolioCashRepository(database)
            event_repository = MarketEventRepository(database)
            issue_repository = IssueLedgerRepository(database)
            snapshot_repository = RecommendationSnapshotRepository(database)
            lifecycle_repository = SignalLifecycleRepository(database)

            watchlist_repository.create_stock("600519", "贵州茅台")
            watchlist_repository.record_refresh(
                "600519",
                latest_recommendation="buy",
                latest_confidence=0.82,
                latest_reason="趋势延续",
                status="active",
                status_label="监控中",
                last_analysis_at="2026-05-13 10:00",
            )
            watchlist_repository.create_stock("601318", "中国平安")
            watchlist_repository.record_refresh(
                "601318",
                latest_recommendation="buy",
                latest_confidence=0.75,
                latest_reason="估值修复",
                status="active",
                status_label="监控中",
                last_analysis_at="2026-05-13 10:05",
            )

            holding_repository.upsert_holding(
                symbol="600519",
                name="贵州茅台",
                shares=100,
                avg_cost=1500.0,
                last_price=1600.0,
            )
            cash_repository.upsert_balance(balance=300000.0)
            event_repository.upsert_event(
                symbol="600519",
                title="公告窗口",
                event_type="announcement",
                severity="high",
                event_date="2026-05-13",
                source="event_engine",
            )
            issue_repository.create_issue(
                issue_type="position_risk",
                severity="high",
                status="open",
                symbol="600519",
                source="risk_engine",
                message="仓位过于集中",
                created_at="2026-05-13T10:10",
            )
            snapshot_repository.create_snapshot(
                symbol="600519",
                source="scheduled",
                recommendation="buy",
                confidence=0.82,
                market_regime="trend",
                market_regime_label="趋势",
                confirmation_score=0.8,
                sentiment_count=4,
                company_match_count=3,
                turnover=1000000.0,
                reason="趋势延续",
                created_at="2026-05-13T10:12",
            )
            snapshot_repository.create_snapshot(
                symbol="601318",
                source="scheduled",
                recommendation="buy",
                confidence=0.75,
                market_regime="trend",
                market_regime_label="趋势",
                confirmation_score=0.72,
                sentiment_count=3,
                company_match_count=2,
                turnover=900000.0,
                reason="估值修复",
                created_at="2026-05-13T10:14",
            )
            lifecycle_repository.upsert(
                symbol="600519",
                status="weakened",
                reason="波动加大",
                signal_at="2026-05-13T10:15:00",
                updated_at="2026-05-13T10:15:00",
                created_at="2026-05-13T09:45:00",
            )

            app = create_app()
            app.config["TESTING"] = True
            app.config["TRADER_DATABASE"] = database
            app.config["TRADER_WATCHLIST_REPOSITORY"] = watchlist_repository
            app.config["TRADER_ALERT_REPOSITORY"] = AlertRepository(database)
            app.config["TRADER_MARKET_EVENT_REPOSITORY"] = event_repository
            app.config["TRADER_RECOMMENDATION_EVENT_REPOSITORY"] = RecommendationEventRepository(database)
            app.config["TRADER_PORTFOLIO_SETTINGS_REPOSITORY"] = PortfolioSettingsRepository(database)
            app.config["TRADER_RECOMMENDATION_SNAPSHOT_REPOSITORY"] = snapshot_repository
            app.config["TRADER_ISSUE_LEDGER_REPOSITORY"] = issue_repository
            app.config["TRADER_SIGNAL_LIFECYCLE_REPOSITORY"] = lifecycle_repository
            app.config["TRADER_PORTFOLIO_HOLDING_REPOSITORY"] = holding_repository
            app.config["TRADER_PORTFOLIO_CASH_REPOSITORY"] = cash_repository

            with app.app_context():
                workspace = _build_recommendations_workspace()

            playbook = workspace["portfolio_rebalance_playbook"]
            self.assertEqual(playbook.generated_at is not None, True)
            self.assertEqual(playbook.action_counts.trim_reduce, 1)
            self.assertEqual(playbook.action_counts.buy_add, 1)
            self.assertGreaterEqual(len(playbook.actions), 2)
            self.assertEqual(playbook.actions[0].symbol, "600519")
            self.assertEqual(playbook.actions[0].action, "trim_reduce")
            self.assertEqual(playbook.actions[1].symbol, "601318")
            self.assertEqual(playbook.actions[1].action, "buy_add")


if __name__ == "__main__":
    import unittest

    unittest.main()
