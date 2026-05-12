from __future__ import annotations

from datetime import datetime
from unittest import TestCase

from app.evaluation import build_issue_stats_report
from app.persistence import IssueLedgerRow


class IssueStatsReportTests(TestCase):
    def test_builds_issue_stats(self) -> None:
        report = build_issue_stats_report(
            issue_rows=[
                IssueLedgerRow(
                    id=1,
                    issue_type="sentiment_source_failure",
                    severity="high",
                    status="open",
                    symbol="600519",
                    source="36kr",
                    origin_worker="sentiment_worker",
                    message="timeout",
                    details={},
                    created_at="2026-05-12T10:00",
                    last_seen_at="2026-05-12T10:05",
                    occurrence_count=2,
                    resolved_at=None,
                ),
                IssueLedgerRow(
                    id=2,
                    issue_type="entity_mapping_low_confidence",
                    severity="medium",
                    status="resolved",
                    symbol="300750",
                    source="monitoring_refresh",
                    origin_worker="monitoring_worker",
                    message="low confidence",
                    details={},
                    created_at="2026-05-13T10:00",
                    last_seen_at="2026-05-13T10:00",
                    occurrence_count=1,
                    resolved_at="2026-05-13T11:00",
                ),
            ],
            generated_at=datetime(2026, 5, 14, 9, 30),
        )

        self.assertEqual(report.total_count, 2)
        self.assertEqual(report.open_count, 1)
        self.assertEqual(report.high_count, 1)
        self.assertEqual(report.status_counts[0].key, "open")
        self.assertEqual(report.severity_counts[0].key, "high")
        self.assertEqual(report.type_counts[0].count, 1)
        self.assertEqual(len(report.trend), 2)


if __name__ == "__main__":
    import unittest

    unittest.main()
