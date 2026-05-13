from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app.persistence import AlertRepository, init_database
from app.workers.events import _persist_high_priority_event_alerts


class EventWorkerAlertTests(TestCase):
    def test_creates_alerts_only_for_high_priority_symbol_events_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "events-alerts.db"))
            repository = AlertRepository(database)
            events = [
                {
                    "symbol": "600519",
                    "title": "贵州茅台 停复牌提醒",
                    "event_type": "suspension_resume",
                    "severity": "high",
                    "event_date": "2026-05-13",
                    "source": "baidu_trade_calendar",
                    "details": {
                        "detail": "重大事项停牌",
                        "suspend_date": "2026-05-13",
                    },
                },
                {
                    "symbol": "600519",
                    "title": "贵州茅台 停复牌提醒",
                    "event_type": "suspension_resume",
                    "severity": "high",
                    "event_date": "2026-05-13",
                    "source": "baidu_trade_calendar",
                    "details": {
                        "detail": "重大事项停牌",
                        "suspend_date": "2026-05-13",
                    },
                },
                {
                    "symbol": "600519",
                    "title": "贵州茅台 分红派息提醒",
                    "event_type": "dividend_ex_date",
                    "severity": "medium",
                    "event_date": "2026-05-13",
                    "source": "baidu_trade_calendar",
                    "details": {},
                },
                {
                    "symbol": None,
                    "title": "财报 / 业绩预告季",
                    "event_type": "earnings_window",
                    "severity": "high",
                    "event_date": "2026-05-13",
                    "source": "event_worker",
                    "details": {"rule": "quarterly_earnings_window"},
                },
            ]

            created_count = _persist_high_priority_event_alerts(
                alert_repository=repository,
                events=events,
            )
            repeated_count = _persist_high_priority_event_alerts(
                alert_repository=repository,
                events=events,
            )
            unread = repository.list_unread()

            self.assertEqual(created_count, 1)
            self.assertEqual(repeated_count, 0)
            self.assertEqual(len(unread), 1)
            self.assertEqual(unread[0].symbol, "600519")
            self.assertEqual(unread[0].level, "high")
            self.assertIn("重大事项停牌", unread[0].summary)


if __name__ == "__main__":
    import unittest

    unittest.main()
