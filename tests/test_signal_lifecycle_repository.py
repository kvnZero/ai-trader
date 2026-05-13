from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app.persistence import SignalLifecycleRepository, init_database


class SignalLifecycleRepositoryTests(TestCase):
    def test_upsert_creates_and_updates_lifecycle_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "signal-lifecycle.db"))
            repository = SignalLifecycleRepository(database)

            created = repository.upsert(
                symbol="600519",
                status="created",
                reason="initial signal detected",
                metadata={"source": "scheduled", "score": 0.61},
                signal_at="2026-05-13T09:35:00+08:00",
                updated_at="2026-05-13T09:35:00+08:00",
                created_at="2026-05-13T09:35:00+08:00",
            )

            self.assertEqual(created.symbol, "600519")
            self.assertEqual(created.status, "created")
            self.assertEqual(created.reason, "initial signal detected")
            self.assertEqual(created.metadata["source"], "scheduled")
            self.assertEqual(created.created_at, "2026-05-13T09:35:00+08:00")
            self.assertEqual(created.last_signal_at, "2026-05-13T09:35:00+08:00")

            updated = repository.upsert(
                symbol="600519",
                status="confirmed",
                reason="follow-through confirmed",
                metadata={"source": "scheduled", "score": 0.84, "phase": "breakout"},
                signal_at="2026-05-13T10:05:00+08:00",
                updated_at="2026-05-13T10:06:00+08:00",
                created_at="2026-05-13T10:06:00+08:00",
            )

            self.assertEqual(updated.symbol, "600519")
            self.assertEqual(updated.status, "confirmed")
            self.assertEqual(updated.reason, "follow-through confirmed")
            self.assertEqual(updated.metadata["phase"], "breakout")
            self.assertEqual(updated.created_at, "2026-05-13T09:35:00+08:00")
            self.assertEqual(updated.updated_at, "2026-05-13T10:06:00+08:00")
            self.assertEqual(updated.last_signal_at, "2026-05-13T10:05:00+08:00")

    def test_get_and_list_support_status_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "signal-lifecycle.db"))
            repository = SignalLifecycleRepository(database)

            repository.upsert(
                symbol="300750",
                status="active",
                reason="momentum improving",
                metadata={"source": "research"},
                signal_at="2026-05-13T11:00:00+08:00",
                updated_at="2026-05-13T11:00:00+08:00",
                created_at="2026-05-13T11:00:00+08:00",
            )
            repository.upsert(
                symbol="688981",
                status="invalidated",
                reason="trend broke",
                metadata={"source": "scheduled"},
                signal_at="2026-05-13T10:00:00+08:00",
                updated_at="2026-05-13T10:00:00+08:00",
                created_at="2026-05-13T10:00:00+08:00",
            )

            fetched = repository.get("300750")
            assert fetched is not None
            self.assertEqual(fetched.status, "active")

            rows = repository.list_rows(limit=10)
            self.assertEqual([row.symbol for row in rows], ["300750", "688981"])

            active_rows = repository.list_rows(status="active", limit=10)
            self.assertEqual(len(active_rows), 1)
            self.assertEqual(active_rows[0].symbol, "300750")


if __name__ == "__main__":
    import unittest

    unittest.main()

