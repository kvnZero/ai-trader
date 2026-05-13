from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app.persistence import (
    IssueLedgerRepository,
    MarketEventRepository,
    PortfolioHoldingRepository,
    RecommendationSnapshotRepository,
    SignalLifecycleRepository,
    init_database,
)
from app.portfolio.risk_overview import build_portfolio_risk_overview


class PortfolioRiskOverviewTests(TestCase):
    def test_build_portfolio_risk_overview_derives_actions_from_risk_stack(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "portfolio-risk.db"))
            holding_repository = PortfolioHoldingRepository(database)
            market_event_repository = MarketEventRepository(database)
            lifecycle_repository = SignalLifecycleRepository(database)
            issue_repository = IssueLedgerRepository(database)
            snapshot_repository = RecommendationSnapshotRepository(database)

            holding_repository.upsert_holding(
                symbol="600519",
                name="贵州茅台",
                shares=100,
                avg_cost=1500.0,
                last_price=1600.0,
            )
            holding_repository.upsert_holding(
                symbol="300750",
                name="宁德时代",
                shares=80,
                avg_cost=220.0,
                last_price=230.0,
            )
            holding_repository.upsert_holding(
                symbol="000858",
                name="五粮液",
                shares=60,
                avg_cost=130.0,
                last_price=131.0,
            )
            holding_repository.upsert_holding(
                symbol="601318",
                name="中国平安",
                shares=120,
                avg_cost=45.0,
                last_price=46.0,
            )

            market_event_repository.upsert_event(
                symbol="600519",
                title="监管窗口",
                event_type="regulation",
                severity="high",
                event_date="2026-05-13",
                source="event_engine",
            )
            issue_repository.create_issue(
                issue_type="risk_limit_breach",
                severity="high",
                status="open",
                symbol="600519",
                source="risk_engine",
                message="集中度过高",
                created_at="2026-05-13T10:00",
            )
            snapshot_repository.create_snapshot(
                symbol="600519",
                source="scheduled",
                recommendation="buy",
                confidence=0.63,
                market_regime="trend",
                market_regime_label="趋势",
                confirmation_score=0.75,
                sentiment_count=4,
                company_match_count=3,
                turnover=1000000.0,
                reason="仍有趋势支撑",
                created_at="2026-05-13T10:05",
            )

            lifecycle_repository.upsert(
                symbol="300750",
                status="invalidated",
                reason="主信号失效",
                signal_at="2026-05-13T10:10:00",
                updated_at="2026-05-13T10:10:00",
                created_at="2026-05-13T09:50:00",
            )
            snapshot_repository.create_snapshot(
                symbol="300750",
                source="scheduled",
                recommendation="watch",
                confidence=0.51,
                market_regime="range",
                market_regime_label="震荡",
                confirmation_score=0.42,
                sentiment_count=2,
                company_match_count=1,
                turnover=900000.0,
                reason="等待修复",
                created_at="2026-05-13T10:11",
            )

            issue_repository.create_issue(
                issue_type="data_gap",
                severity="high",
                status="open",
                symbol="000858",
                source="refresh",
                message="价格刷新缺口",
                created_at="2026-05-13T10:20",
            )
            snapshot_repository.create_snapshot(
                symbol="000858",
                source="scheduled",
                recommendation="buy",
                confidence=0.38,
                market_regime="range",
                market_regime_label="震荡",
                confirmation_score=0.35,
                sentiment_count=1,
                company_match_count=1,
                turnover=800000.0,
                reason="信号偏弱",
                created_at="2026-05-13T10:21",
            )

            snapshot_repository.create_snapshot(
                symbol="601318",
                source="scheduled",
                recommendation="buy",
                confidence=0.72,
                market_regime="trend",
                market_regime_label="趋势",
                confirmation_score=0.78,
                sentiment_count=3,
                company_match_count=2,
                turnover=1100000.0,
                reason="持有",
                created_at="2026-05-13T10:30",
            )

            report = build_portfolio_risk_overview(
                holding_repository=holding_repository,
                market_event_repository=market_event_repository,
                signal_lifecycle_repository=lifecycle_repository,
                issue_repository=issue_repository,
                recommendation_snapshot_repository=snapshot_repository,
            )

            self.assertEqual(report.held_symbol_count, 4)
            self.assertEqual(report.action_counts["trim"], 1)
            self.assertEqual(report.action_counts["reduce"], 1)
            self.assertEqual(report.action_counts["watch"], 1)
            self.assertEqual(report.action_counts["hold"], 1)
            self.assertEqual(report.high_risk_count, 2)
            self.assertEqual(
                [(item.symbol, item.portfolio_action) for item in report.items],
                [
                    ("300750", "trim"),
                    ("600519", "reduce"),
                    ("000858", "watch"),
                    ("601318", "hold"),
                ],
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
