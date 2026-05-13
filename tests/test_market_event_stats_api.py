from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app import create_app
from app.persistence import MarketEventRepository, init_database


class MarketEventStatsApiTests(TestCase):
    def test_stats_api_returns_grouped_event_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "events.db"))
            repository = MarketEventRepository(database)
            repository.upsert_event(
                symbol="600519",
                title="财报窗口",
                event_type="earnings_window",
                severity="high",
                event_date="2026-05-20",
                source="event_engine",
            )
            repository.upsert_event(
                symbol="600519",
                title="分红登记",
                event_type="dividend",
                severity="medium",
                event_date="2026-05-21",
                source="event_engine",
            )
            repository.upsert_event(
                symbol="300750",
                title="解禁提醒",
                event_type="unlock",
                severity="high",
                event_date="2026-05-22",
                source="event_engine",
            )

            app = create_app()
            app.config["TESTING"] = True
            app.config["TRADER_DATABASE"] = database
            app.config["TRADER_MARKET_EVENT_REPOSITORY"] = repository

            with app.test_client() as client:
                response = client.get("/api/events/stats?symbol=600519")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            assert payload is not None
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["symbol"], "600519")
            self.assertEqual(payload["report"]["total_count"], 2)
            self.assertEqual(
                payload["report"]["severity_counts"],
                [
                    {"key": "high", "count": 1},
                    {"key": "medium", "count": 1},
                ],
            )
            self.assertEqual(
                payload["report"]["type_counts"],
                [
                    {"key": "dividend", "count": 1},
                    {"key": "earnings_window", "count": 1},
                ],
            )
            self.assertEqual(
                payload["report"]["symbol_counts"],
                [{"key": "600519", "count": 2}],
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
