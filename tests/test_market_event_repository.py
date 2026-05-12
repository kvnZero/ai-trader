from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app.persistence import MarketEventRepository, init_database


class MarketEventRepositoryTests(TestCase):
    def test_upsert_and_query_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "events.db"))
            repository = MarketEventRepository(database)

            created = repository.upsert_event(
                symbol="600519",
                title="财报窗口",
                event_type="earnings_window",
                severity="high",
                event_date="2026-05-20",
                source="event_engine",
                details={"quarter": "Q1"},
            )
            self.assertTrue(created)

            updated = repository.upsert_event(
                symbol="600519",
                title="财报窗口",
                event_type="earnings_window",
                severity="medium",
                event_date="2026-05-20",
                source="event_engine",
                details={"quarter": "Q1", "updated": True},
            )
            self.assertTrue(updated)

            recent = repository.list_recent(limit=10)
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0].severity, "medium")

            upcoming = repository.list_upcoming(limit=10)
            self.assertEqual(len(upcoming), 1)
            self.assertEqual(upcoming[0].event_type, "earnings_window")


if __name__ == "__main__":
    import unittest

    unittest.main()
