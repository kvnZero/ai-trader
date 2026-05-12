from __future__ import annotations

from datetime import datetime
from unittest import TestCase

from app.evaluation import build_recommendation_review_report
from app.persistence import (
    AlertRow,
    RecommendationEventRow,
    SentimentSourceFailureRow,
    SentimentWorkerStateRow,
    WatchlistRow,
)


class RecommendationReviewReportTests(TestCase):
    def test_builds_empty_report(self) -> None:
        report = build_recommendation_review_report(
            watchlist_rows=[],
            recommendation_events=[],
            recent_runs=[],
            unread_alerts=[],
            sentiment_worker_state=None,
            latest_source_failures=[],
            generated_at=datetime(2026, 5, 11, 10, 0),
        )

        self.assertEqual(report.watchlist_count, 0)
        self.assertEqual(report.action_counts["buy"], 0)
        self.assertEqual(report.conservative_ratio, 0.0)
        self.assertEqual(report.recent_event_count, 0)
        self.assertIsNone(report.latest_event)
        self.assertEqual(report.sentiment_worker_status, "idle")

    def test_builds_populated_report(self) -> None:
        report = build_recommendation_review_report(
            watchlist_rows=[
                WatchlistRow(
                    symbol="600519",
                    name="贵州茅台",
                    monitoring_enabled=True,
                    use_default_schedule=True,
                    schedule_label="工作日",
                    status="active",
                    status_label="监控中",
                    latest_recommendation="buy",
                    latest_confidence=0.78,
                    latest_reason="趋势延续",
                    last_analysis_at="10:30",
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
                    latest_confidence=0.31,
                    latest_reason="等待确认",
                    last_analysis_at="10:32",
                ),
            ],
            recommendation_events=[
                RecommendationEventRow(
                    symbol="600519",
                    previous_action="watch",
                    current_action="buy",
                    confidence=0.78,
                    summary="趋势延续",
                    created_at="2026-05-11T10:30",
                )
            ],
            recent_runs=[
                {"symbol": "600519", "status": "scheduled", "stale": False, "detail": "ok", "created_at": "2026-05-11T10:30"},
                {"symbol": "300750", "status": "scheduled", "stale": True, "detail": "stale", "created_at": "2026-05-11T10:31"},
            ],
            unread_alerts=[
                AlertRow(
                    id=1,
                    symbol="600519",
                    title="alert",
                    summary="summary",
                    level="high",
                    unread=True,
                    created_at="2026-05-11T10:31",
                )
            ],
            sentiment_worker_state=SentimentWorkerStateRow(
                worker_name="sentiment_worker",
                status="degraded",
                last_started_at="2026-05-11T10:00",
                last_completed_at="2026-05-11T10:05",
                last_success_at="2026-05-11T10:05",
                last_heartbeat_at="2026-05-11T10:05",
                latest_item_published_at="2026-05-11T09:58",
                last_run_id=3,
                item_count=25,
                source_run_count=7,
                failure_count=1,
                duplicate_count=0,
                stale_count=0,
                error_message="",
            ),
            latest_source_failures=[
                SentimentSourceFailureRow(
                    source_id="rss-1",
                    source_name="36氪",
                    category="finance_news",
                    adapter_name="rss_feed",
                    failed_at="2026-05-11T10:04",
                    error_code="sentiment_source_unavailable",
                    error_message="boom",
                    retryable=True,
                    details={},
                )
            ],
            generated_at=datetime(2026, 5, 11, 10, 10),
        )

        self.assertEqual(report.watchlist_count, 2)
        self.assertEqual(report.action_counts["buy"], 1)
        self.assertEqual(report.action_counts["watch"], 1)
        self.assertEqual(report.conservative_count, 1)
        self.assertEqual(report.unread_high_alert_count, 1)
        self.assertEqual(report.stale_run_count, 1)
        self.assertEqual(report.sentiment_worker_status, "degraded")
        self.assertEqual(report.sentiment_failure_count, 1)
        self.assertIsNotNone(report.latest_event)
        assert report.latest_event is not None
        self.assertEqual(report.latest_event.symbol, "600519")


if __name__ == "__main__":
    import unittest

    unittest.main()
