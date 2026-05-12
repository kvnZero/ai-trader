from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from unittest import TestCase

from app.domain import MarketBar
from app.evaluation import build_backtest_summary_report
from app.persistence import RecommendationSnapshotRow
from app.modules.market_data.contracts import MarketDataResult


@dataclass
class _FakeMarketDataService:
    bars: list[MarketBar]

    def get_daily_bars(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        adjust: str = "",
        limit: int | None = None,
    ) -> MarketDataResult[list[MarketBar]]:
        del symbol, start_date, end_date, adjust, limit
        return MarketDataResult(data=self.bars, source="fake")


class BacktestSummaryReportTests(TestCase):
    def test_builds_backtest_summary(self) -> None:
        bars = [
            MarketBar(symbol="600519", trade_date=date(2026, 5, 11), open_price=100, high_price=102, low_price=99, close_price=101, volume=1),
            MarketBar(symbol="600519", trade_date=date(2026, 5, 12), open_price=101, high_price=106, low_price=100, close_price=105, volume=1),
            MarketBar(symbol="600519", trade_date=date(2026, 5, 13), open_price=105, high_price=108, low_price=104, close_price=107, volume=1),
        ]
        report = build_backtest_summary_report(
            snapshots=[
                RecommendationSnapshotRow(
                    symbol="600519",
                    source="scheduled",
                    recommendation="buy",
                    confidence=0.8,
                    market_regime="trend",
                    market_regime_label="趋势",
                    confirmation_score=0.9,
                    sentiment_count=3,
                    company_match_count=2,
                    turnover=100000000.0,
                    reason="trend",
                    created_at="2026-05-11T09:30",
                )
            ],
            market_data_service=_FakeMarketDataService(bars=bars),
        )

        self.assertEqual(report.snapshot_count, 1)
        self.assertEqual(report.evaluated_count, 1)
        self.assertEqual(report.buy_sell_hit_count, 1)
        self.assertEqual(report.buy_sell_hit_rate, 1.0)
        self.assertEqual(report.average_forward_return_pct, 5.941)
        self.assertEqual(len(report.regime_breakdown), 1)
        self.assertEqual(len(report.action_breakdown), 1)
        self.assertEqual(len(report.evaluations), 1)


if __name__ == "__main__":
    import unittest

    unittest.main()
