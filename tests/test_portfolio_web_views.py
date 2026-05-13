from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app import create_app
from app.persistence import (
    AlertRepository,
    PortfolioCashRepository,
    PortfolioHoldingRepository,
    IssueLedgerRepository,
    MarketEventRepository,
    PortfolioSettingsRepository,
    RecommendationEventRepository,
    RecommendationSnapshotRepository,
    SignalLifecycleRepository,
    WatchlistRepository,
    init_database,
)


class PortfolioWebViewTests(TestCase):
    def test_recommendations_page_renders_account_state_and_position_impact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "portfolio-web.db"))
            watchlist_repository = WatchlistRepository(database)
            holding_repository = PortfolioHoldingRepository(database)
            cash_repository = PortfolioCashRepository(database)
            watchlist_repository.create_stock("600519", "贵州茅台")
            watchlist_repository.record_refresh(
                "600519",
                latest_recommendation="buy",
                latest_confidence=0.90,
                latest_reason="趋势延续",
                status="active",
                status_label="监控中",
                last_analysis_at="2026-05-13 10:30",
            )
            holding_repository.upsert_holding(
                symbol="600519",
                name="贵州茅台",
                shares=100,
                avg_cost=1500.0,
                last_price=1600.0,
            )
            cash_repository.upsert_balance(balance=120000.0)

            app = create_app()
            app.config["TESTING"] = True
            app.config["TRADER_DATABASE"] = database
            app.config["TRADER_WATCHLIST_REPOSITORY"] = watchlist_repository
            app.config["TRADER_ALERT_REPOSITORY"] = AlertRepository(database)
            app.config["TRADER_MARKET_EVENT_REPOSITORY"] = MarketEventRepository(database)
            app.config["TRADER_RECOMMENDATION_EVENT_REPOSITORY"] = RecommendationEventRepository(database)
            app.config["TRADER_PORTFOLIO_SETTINGS_REPOSITORY"] = PortfolioSettingsRepository(database)
            app.config["TRADER_RECOMMENDATION_SNAPSHOT_REPOSITORY"] = RecommendationSnapshotRepository(database)
            app.config["TRADER_ISSUE_LEDGER_REPOSITORY"] = IssueLedgerRepository(database)
            app.config["TRADER_SIGNAL_LIFECYCLE_REPOSITORY"] = SignalLifecycleRepository(database)
            app.config["TRADER_PORTFOLIO_HOLDING_REPOSITORY"] = holding_repository
            app.config["TRADER_PORTFOLIO_CASH_REPOSITORY"] = cash_repository

            with app.test_client() as client:
                response = client.get("/recommendations")

            self.assertEqual(response.status_code, 200)
            body = response.get_data(as_text=True)
            self.assertIn("当前持仓与现金", body)
            self.assertIn("当前账户状态如何影响建议仓位", body)
            self.assertIn("当前持仓优先处理项", body)
            self.assertIn("Cash Balance", body)
            self.assertIn("120000.0", body)
            self.assertIn("600519 已有持仓已覆盖目标仓位，本次不新增。", body)
            self.assertIn("取现金比例与剩余风险预算的较小值。", body)

    def test_system_page_shows_read_only_holding_risk_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "portfolio-system.db"))
            watchlist_repository = WatchlistRepository(database)
            holding_repository = PortfolioHoldingRepository(database)
            cash_repository = PortfolioCashRepository(database)
            recommendation_event_repository = RecommendationEventRepository(database)

            watchlist_repository.create_stock("600519", "贵州茅台")
            watchlist_repository.record_refresh(
                "600519",
                latest_recommendation="watch",
                latest_confidence=0.45,
                latest_reason="趋势放缓，先观察。",
                status="active",
                status_label="监控中",
                last_analysis_at="2026-05-13 10:30",
            )
            holding_repository.upsert_holding(
                symbol="600519",
                name="贵州茅台",
                shares=100,
                avg_cost=1500.0,
                last_price=1480.0,
            )
            cash_repository.upsert_balance(balance=50000.0)
            recommendation_event_repository.create_event(
                symbol="600519",
                previous_action="buy",
                current_action="watch",
                confidence=0.45,
                summary="趋势放缓，切回观察。",
            )

            app = create_app()
            app.config["TESTING"] = True
            app.config["TRADER_DATABASE"] = database
            app.config["TRADER_WATCHLIST_REPOSITORY"] = watchlist_repository
            app.config["TRADER_ALERT_REPOSITORY"] = AlertRepository(database)
            app.config["TRADER_MARKET_EVENT_REPOSITORY"] = MarketEventRepository(database)
            app.config["TRADER_RECOMMENDATION_EVENT_REPOSITORY"] = recommendation_event_repository
            app.config["TRADER_PORTFOLIO_SETTINGS_REPOSITORY"] = PortfolioSettingsRepository(database)
            app.config["TRADER_RECOMMENDATION_SNAPSHOT_REPOSITORY"] = RecommendationSnapshotRepository(database)
            app.config["TRADER_ISSUE_LEDGER_REPOSITORY"] = IssueLedgerRepository(database)
            app.config["TRADER_SIGNAL_LIFECYCLE_REPOSITORY"] = SignalLifecycleRepository(database)
            app.config["TRADER_PORTFOLIO_HOLDING_REPOSITORY"] = holding_repository
            app.config["TRADER_PORTFOLIO_CASH_REPOSITORY"] = cash_repository

            with app.test_client() as client:
                response = client.get("/system")

            self.assertEqual(response.status_code, 200)
            body = response.get_data(as_text=True)
            self.assertIn("持仓风险只读摘要", body)
            self.assertIn("去 recommendations 处理", body)
            self.assertIn("600519", body)

    def test_account_state_form_persists_to_repositories_and_redirects(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "portfolio-form.db"))
            holding_repository = PortfolioHoldingRepository(database)
            cash_repository = PortfolioCashRepository(database)

            app = create_app()
            app.config["TESTING"] = True
            app.config["TRADER_DATABASE"] = database
            app.config["TRADER_WATCHLIST_REPOSITORY"] = WatchlistRepository(database)
            app.config["TRADER_ALERT_REPOSITORY"] = AlertRepository(database)
            app.config["TRADER_MARKET_EVENT_REPOSITORY"] = MarketEventRepository(database)
            app.config["TRADER_RECOMMENDATION_EVENT_REPOSITORY"] = RecommendationEventRepository(database)
            app.config["TRADER_PORTFOLIO_SETTINGS_REPOSITORY"] = PortfolioSettingsRepository(database)
            app.config["TRADER_RECOMMENDATION_SNAPSHOT_REPOSITORY"] = RecommendationSnapshotRepository(database)
            app.config["TRADER_ISSUE_LEDGER_REPOSITORY"] = IssueLedgerRepository(database)
            app.config["TRADER_SIGNAL_LIFECYCLE_REPOSITORY"] = SignalLifecycleRepository(database)
            app.config["TRADER_PORTFOLIO_HOLDING_REPOSITORY"] = holding_repository
            app.config["TRADER_PORTFOLIO_CASH_REPOSITORY"] = cash_repository

            with app.test_client() as client:
                response = client.post(
                    "/recommendations/account-state",
                    data={
                        "cash_balance": "180000",
                        "holding_symbol": ["600519", "300750"],
                        "holding_name": ["贵州茅台", "宁德时代"],
                        "holding_shares": ["100", "200"],
                        "holding_avg_cost": ["1500", "220"],
                        "holding_last_price": ["1600", "230"],
                        "holding_notes": ["", ""],
                    },
                    follow_redirects=False,
                )

            self.assertEqual(response.status_code, 302)
            location = response.headers.get("Location", "")
            self.assertTrue(location.endswith("/recommendations"))

            cash_row = cash_repository.get_balance()
            self.assertIsNotNone(cash_row)
            assert cash_row is not None
            self.assertEqual(cash_row.balance, 180000.0)

            rows = holding_repository.list_rows()
            self.assertEqual(len(rows), 2)
            row_by_symbol = {row.symbol: row for row in rows}
            self.assertEqual(row_by_symbol["600519"].shares, 100.0)
            self.assertEqual(row_by_symbol["300750"].last_price, 230.0)


if __name__ == "__main__":
    import unittest

    unittest.main()
