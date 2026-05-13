from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app.config import Settings
from app.monitoring.refresh import WatchlistRefreshService
from app.modules.market_data.contracts import MarketDataResult
from app.persistence import (
    AlertRepository,
    IssueLedgerRepository,
    RecommendationEventRepository,
    RecommendationSnapshotRepository,
    SignalLifecycleRepository,
    WatchlistRepository,
    init_database,
)


class SignalLifecycleRefreshTests(TestCase):
    def test_refresh_persists_lifecycle_when_market_data_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "signal-lifecycle-refresh.db"))
            settings = Settings(database_path=str(Path(tmpdir) / "signal-lifecycle-refresh.db"))
            watchlist_repository = WatchlistRepository(database)
            alert_repository = AlertRepository(database)
            issue_repository = IssueLedgerRepository(database)
            recommendation_event_repository = RecommendationEventRepository(database)
            recommendation_snapshot_repository = RecommendationSnapshotRepository(database)
            signal_lifecycle_repository = SignalLifecycleRepository(database)

            watchlist_repository.create_stock("600519", "贵州茅台")
            watchlist_repository.record_refresh(
                "600519",
                latest_recommendation="watch",
                latest_confidence=0.41,
                latest_reason="等待确认。",
                status="active",
                status_label="监控中",
                last_analysis_at="2026-05-13 09:35",
            )

            service = WatchlistRefreshService(
                settings=settings,
                watchlist_repository=watchlist_repository,
                alert_repository=alert_repository,
                issue_repository=issue_repository,
                recommendation_event_repository=recommendation_event_repository,
                recommendation_snapshot_repository=recommendation_snapshot_repository,
                signal_lifecycle_repository=signal_lifecycle_repository,
            )

            with patch.object(
                service.market_service,
                "get_latest_snapshot",
                return_value=MarketDataResult(data=None, source="stub"),
            ):
                outcome = service.refresh_symbol("600519", source="manual")

            self.assertIsNotNone(outcome)
            row = signal_lifecycle_repository.get("600519")
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row.status, "weakened")
            self.assertEqual(row.metadata["source"], "manual")


if __name__ == "__main__":
    import unittest

    unittest.main()
