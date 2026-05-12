from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app.persistence import IssueLedgerRepository, init_database


class IssueLedgerRepositoryTests(TestCase):
    def test_create_and_list_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "issues.db"))
            repository = IssueLedgerRepository(database)

            created = repository.create_issue(
                issue_type="sentiment_source_failure",
                severity="high",
                status="open",
                symbol="600519",
                source="36kr",
                origin_worker="sentiment_worker",
                message="timeout",
                details={"retryable": True},
                created_at="2026-05-12T10:00",
            )
            self.assertTrue(created)

            rows = repository.list_recent(limit=10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].issue_type, "sentiment_source_failure")
            self.assertEqual(rows[0].symbol, "600519")
            self.assertEqual(rows[0].severity, "high")
            self.assertEqual(rows[0].occurrence_count, 1)

            created_again = repository.create_issue(
                issue_type="sentiment_source_failure",
                severity="high",
                status="open",
                symbol="600519",
                source="36kr",
                origin_worker="sentiment_worker",
                message="timeout",
                details={"retryable": True},
                created_at="2026-05-12T10:05",
            )
            self.assertTrue(created_again)

            rows = repository.list_recent(limit=10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].occurrence_count, 2)
            self.assertEqual(rows[0].last_seen_at, "2026-05-12T10:05")

            resolved = repository.resolve_issue(rows[0].id)
            self.assertTrue(resolved)
            rows_after = repository.list_recent(limit=10)
            self.assertEqual(rows_after[0].status, "resolved")


if __name__ == "__main__":
    import unittest

    unittest.main()
