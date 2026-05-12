from __future__ import annotations

from unittest import TestCase

from app.modules.entity_mapping.dictionary import build_default_company_dictionary
from app.persistence.portfolio import PortfolioSettingsRow
from app.persistence.watchlist import WatchlistRow
from app.portfolio import build_portfolio_summary


class PortfolioServiceTests(TestCase):
    def test_builds_position_plans_with_constraints(self) -> None:
        company_dictionary = build_default_company_dictionary()
        rows = [
            WatchlistRow(
                symbol="600519",
                name="贵州茅台",
                monitoring_enabled=True,
                use_default_schedule=True,
                schedule_label="工作日",
                status="active",
                status_label="监控中",
                latest_recommendation="buy",
                latest_confidence=0.8,
                latest_reason="趋势延续",
                last_analysis_at="10:30",
            ),
            WatchlistRow(
                symbol="000858",
                name="五粮液",
                monitoring_enabled=True,
                use_default_schedule=True,
                schedule_label="工作日",
                status="active",
                status_label="监控中",
                latest_recommendation="buy",
                latest_confidence=0.7,
                latest_reason="白酒跟随",
                last_analysis_at="10:31",
            ),
            WatchlistRow(
                symbol="300750",
                name="宁德时代",
                monitoring_enabled=True,
                use_default_schedule=True,
                schedule_label="工作日",
                status="active",
                status_label="监控中",
                latest_recommendation="watch",
                latest_confidence=0.5,
                latest_reason="等待确认",
                last_analysis_at="10:32",
            ),
        ]

        summary = build_portfolio_summary(
            watchlist_rows=rows,
            company_dictionary=company_dictionary,
            settings=PortfolioSettingsRow(
                profile="default",
                max_total_risk_budget_pct=40.0,
                max_single_position_pct=20.0,
                max_industry_exposure_pct=25.0,
                max_theme_overlap_pct=30.0,
            ),
        )

        self.assertEqual(summary.total_watchlist_count, 3)
        self.assertGreaterEqual(len(summary.position_plans), 2)
        self.assertLessEqual(summary.remaining_risk_budget_pct, 40.0)
        self.assertIn("白酒", summary.industry_exposure)
        self.assertGreaterEqual(summary.high_conviction_count, 2)


if __name__ == "__main__":
    import unittest

    unittest.main()
