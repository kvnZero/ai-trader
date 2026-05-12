from __future__ import annotations

from datetime import datetime
from unittest import TestCase

from app.evaluation import build_issue_timeline_report
from app.persistence import AlertRow, IssueLedgerRow, RecommendationSnapshotRow, SentimentSourceFailureRow, SentimentWorkerStateRow


class IssueTimelineReportTests(TestCase):
    def test_builds_empty_issue_timeline(self) -> None:
        report = build_issue_timeline_report(
            worker_state=None,
            source_failures=[],
            snapshots=[],
            unread_alerts=[],
            generated_at=datetime(2026, 5, 12, 10, 0),
        )

        self.assertEqual(report.issue_count, 0)
        self.assertEqual(report.open_count, 0)
        self.assertEqual(report.high_count, 0)
        self.assertEqual(report.items, [])

    def test_builds_mixed_issue_timeline(self) -> None:
        report = build_issue_timeline_report(
            worker_state=SentimentWorkerStateRow(
                worker_name="sentiment_worker",
                status="degraded",
                last_started_at="2026-05-12T10:00",
                last_completed_at="2026-05-12T10:05",
                last_success_at="2026-05-12T10:05",
                last_heartbeat_at="2026-05-12T10:05",
                latest_item_published_at="2026-05-12T09:58",
                last_run_id=3,
                item_count=25,
                source_run_count=7,
                failure_count=1,
                duplicate_count=0,
                stale_count=0,
                error_message="",
            ),
            source_failures=[
                SentimentSourceFailureRow(
                    source_id="rss-1",
                    source_name="36氪",
                    category="finance_news",
                    adapter_name="rss_feed",
                    failed_at="2026-05-12T10:04",
                    error_code="sentiment_source_unavailable",
                    error_message="timeout",
                    retryable=True,
                    details={},
                )
            ],
            snapshots=[
                RecommendationSnapshotRow(
                    symbol="300750",
                    source="scheduled",
                    recommendation="avoid",
                    confidence=0.21,
                    market_regime="panic",
                    market_regime_label="恐慌",
                    confirmation_score=0.2,
                    sentiment_count=1,
                    company_match_count=0,
                    turnover=20000000.0,
                    reason="信号质量不足，不执行交易",
                    created_at="2026-05-12T10:03",
                )
            ],
            unread_alerts=[
                AlertRow(
                    id=1,
                    symbol="600519",
                    title="alert",
                    summary="summary",
                    level="high",
                    unread=True,
                    created_at="2026-05-12T10:06",
                )
            ],
            generated_at=datetime(2026, 5, 12, 10, 10),
        )

        self.assertEqual(report.issue_count, 4)
        self.assertEqual(report.high_count, 1)
        self.assertIn("unread_alert", report.type_counts)
        self.assertIn("low_quality_signal", report.type_counts)

    def test_prefers_ledger_rows_when_present(self) -> None:
        report = build_issue_timeline_report(
            ledger_rows=[
                IssueLedgerRow(
                    id=1,
                    issue_type="sentiment_source_failure",
                    severity="high",
                    status="open",
                    symbol=None,
                    source="36kr",
                    origin_worker="sentiment_worker",
                    message="timeout",
                    details={"retryable": True},
                    created_at="2026-05-12T10:00",
                    last_seen_at="2026-05-12T10:03",
                    occurrence_count=3,
                    resolved_at=None,
                )
            ],
            worker_state=None,
            source_failures=[],
            snapshots=[],
            unread_alerts=[],
            generated_at=datetime(2026, 5, 12, 10, 10),
        )

        self.assertEqual(report.issue_count, 1)
        self.assertEqual(report.type_counts["sentiment_source_failure"], 1)
        self.assertEqual(report.items[0].issue_id, 1)
        self.assertEqual(report.items[0].source, "36kr")


if __name__ == "__main__":
    import unittest

    unittest.main()
