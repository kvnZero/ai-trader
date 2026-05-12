from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app.config import Settings
from app.monitoring.refresh import WatchlistRefreshService
from app.persistence import AlertRepository, IssueLedgerRepository, RecommendationEventRepository, WatchlistRepository, init_database
from app.persistence.watchlist import WatchlistRow


class RefreshIssueLoggingTests(TestCase):
    def test_records_decision_risk_flags_as_ledger_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "refresh.db"))
            settings = Settings(database_path=str(Path(tmpdir) / "refresh.db"))
            watchlist_repository = WatchlistRepository(database)
            alert_repository = AlertRepository(database)
            issue_repository = IssueLedgerRepository(database)
            recommendation_event_repository = RecommendationEventRepository(database)
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
                latest_recommendation="watch",
                latest_confidence=0.5,
                latest_reason="",
                last_analysis_at=None,
            )

            service._record_decision_risk_issues(
                row=row,
                source="scheduled",
                risk_flags=[
                    "final recommendation is operating without technical signals",
                    "sentiment evidence lacks supporting company mappings",
                    "sentiment inputs may be stale for current market conditions",
                ],
                decision_action="watch",
                decision_confidence=0.34,
            )

            rows = issue_repository.list_recent(limit=10)
            self.assertEqual(len(rows), 3)
            self.assertEqual(
                {row.issue_type for row in rows},
                {
                    "technical_coverage_unavailable",
                    "entity_mapping_missing",
                    "sentiment_data_stale",
                },
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
