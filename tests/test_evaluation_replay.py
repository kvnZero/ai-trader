from __future__ import annotations

from datetime import datetime
from unittest import TestCase

from app.evaluation import build_replay_summary_report
from app.persistence import RecommendationSnapshotRow


class ReplaySummaryReportTests(TestCase):
    def test_builds_empty_report(self) -> None:
        report = build_replay_summary_report(
            snapshots=[],
            generated_at=datetime(2026, 5, 12, 10, 0),
        )

        self.assertEqual(report.snapshot_count, 0)
        self.assertEqual(report.average_confidence, 0.0)
        self.assertEqual(report.action_counts["buy"], 0)
        self.assertEqual(report.regime_counts, {})
        self.assertEqual(report.symbol_coverage_count, 0)

    def test_builds_grouped_replay_report(self) -> None:
        report = build_replay_summary_report(
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
                    created_at="2026-05-12T10:00",
                ),
                RecommendationSnapshotRow(
                    symbol="300750",
                    source="scheduled",
                    recommendation="watch",
                    confidence=0.35,
                    market_regime="panic",
                    market_regime_label="恐慌",
                    confirmation_score=0.2,
                    sentiment_count=1,
                    company_match_count=1,
                    turnover=20000000.0,
                    reason="panic",
                    created_at="2026-05-12T10:05",
                ),
            ],
            generated_at=datetime(2026, 5, 12, 10, 10),
        )

        self.assertEqual(report.snapshot_count, 2)
        self.assertEqual(report.action_counts["buy"], 1)
        self.assertEqual(report.action_counts["watch"], 1)
        self.assertEqual(report.regime_counts["trend"], 1)
        self.assertEqual(report.regime_counts["panic"], 1)
        self.assertEqual(report.symbol_coverage_count, 2)
        self.assertEqual(report.latest_snapshot_at, "2026-05-12T10:00")
        self.assertEqual(len(report.snapshots), 2)


if __name__ == "__main__":
    import unittest

    unittest.main()
