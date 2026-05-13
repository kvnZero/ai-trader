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

    def test_build_stats_report_groups_by_severity_type_and_symbol(self) -> None:
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
            repository.upsert_event(
                symbol=None,
                title="宏观数据发布",
                event_type="macro",
                severity="low",
                event_date="2026-05-23",
                source="event_engine",
            )

            report = repository.build_stats_report()

            self.assertEqual(report.total_count, 4)
            self.assertEqual(
                [(row.key, row.count) for row in report.severity_counts],
                [("high", 2), ("low", 1), ("medium", 1)],
            )
            self.assertEqual(
                [(row.key, row.count) for row in report.type_counts],
                [("dividend", 1), ("earnings_window", 1), ("macro", 1), ("unlock", 1)],
            )
            self.assertEqual(
                [(row.key, row.count) for row in report.symbol_counts],
                [("600519", 2), ("300750", 1)],
            )

            filtered_report = repository.build_stats_report(symbol="600519")
            self.assertEqual(filtered_report.total_count, 2)
            self.assertEqual(
                [(row.key, row.count) for row in filtered_report.symbol_counts],
                [("600519", 2)],
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
