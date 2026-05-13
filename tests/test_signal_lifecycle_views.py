from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app import create_app
from app.persistence import (
    AlertRepository,
    MarketEventRepository,
    PortfolioSettingsRepository,
    RecommendationEventRepository,
    RecommendationSnapshotRepository,
    SignalLifecycleRepository,
    WatchlistRepository,
    init_database,
)


class SignalLifecycleViewTests(TestCase):
    def test_research_page_shows_signal_lifecycle_status_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "lifecycle.db"))
            watchlist_repository = WatchlistRepository(database)
            recommendation_event_repository = RecommendationEventRepository(database)
            signal_lifecycle_repository = SignalLifecycleRepository(database)

            watchlist_repository.create_stock("600519", "贵州茅台")
            watchlist_repository.record_refresh(
                "600519",
                latest_recommendation="watch",
                latest_confidence=0.42,
                latest_reason="等待新的趋势确认。",
                status="active",
                status_label="监控中",
                last_analysis_at="2026-05-13 10:30",
            )
            watchlist_repository.record_analysis_run(
                "600519",
                status="scheduled",
                stale=False,
                detail="完成一轮盘中刷新。",
            )
            recommendation_event_repository.create_event(
                symbol="600519",
                previous_action="buy",
                current_action="watch",
                confidence=0.42,
                summary="趋势放缓，先降级为观察。",
            )
            signal_lifecycle_repository.upsert(
                symbol="600519",
                status="weakened",
                reason="短线动能减弱，进入保守观察阶段。",
                metadata={"source": "refresh"},
                signal_at="2026-05-13T10:32:00",
                updated_at="2026-05-13T10:32:00",
                created_at="2026-05-13T10:20:00",
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
            app.config["TRADER_SIGNAL_LIFECYCLE_REPOSITORY"] = signal_lifecycle_repository

            with app.test_client() as client:
                response = client.get("/research?query=600519")

            self.assertEqual(response.status_code, 200)
            body = response.get_data(as_text=True)
            self.assertIn("信号生命周期状态", body)
            self.assertIn("信号减弱", body)
            self.assertIn("短线动能减弱，进入保守观察阶段。", body)
            self.assertIn("2026-05-13 10:32:00", body)

    def test_lifecycle_api_returns_structured_symbol_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "lifecycle-api.db"))
            watchlist_repository = WatchlistRepository(database)
            recommendation_event_repository = RecommendationEventRepository(database)
            signal_lifecycle_repository = SignalLifecycleRepository(database)

            watchlist_repository.create_stock("300750", "宁德时代")
            watchlist_repository.record_refresh(
                "300750",
                latest_recommendation="buy",
                latest_confidence=0.74,
                latest_reason="趋势保持完整。",
                status="active",
                status_label="监控中",
                last_analysis_at="2026-05-13 11:00",
            )
            signal_lifecycle_repository.upsert(
                symbol="300750",
                status="confirmed",
                reason="多周期信号完成确认。",
                metadata={"source": "refresh"},
                signal_at="2026-05-13T11:01:00",
                updated_at="2026-05-13T11:01:00",
                created_at="2026-05-13T10:40:00",
            )
            recommendation_event_repository.create_event(
                symbol="300750",
                previous_action="watch",
                current_action="buy",
                confidence=0.74,
                summary="信号完成确认，切换为买入。",
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
            app.config["TRADER_SIGNAL_LIFECYCLE_REPOSITORY"] = signal_lifecycle_repository

            with app.test_client() as client:
                response = client.get("/api/recommendations/lifecycle?symbol=300750")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            assert payload is not None
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["symbol"], "300750")
            self.assertEqual(payload["lifecycle"]["state"], "changed")
            self.assertEqual(payload["lifecycle"]["state_label"], "确认中")
            self.assertEqual(payload["lifecycle"]["current_action"], "buy")
            self.assertEqual(payload["lifecycle"]["reason_summary"], "多周期信号完成确认。")
            self.assertEqual(payload["lifecycle"]["last_updated_at"], "2026-05-13 11:01:00")


if __name__ == "__main__":
    import unittest

    unittest.main()
