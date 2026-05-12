from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app.persistence import RecommendationSnapshotRepository, init_database


class RecommendationSnapshotRepositoryTests(TestCase):
    def test_create_and_list_recent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "snapshots.db"))
            repository = RecommendationSnapshotRepository(database)

            created = repository.create_snapshot(
                symbol="600519",
                source="scheduled",
                recommendation="buy",
                confidence=0.76,
                market_regime="trend",
                market_regime_label="趋势",
                confirmation_score=0.82,
                sentiment_count=3,
                company_match_count=2,
                turnover=123456789.0,
                reason="趋势延续",
                created_at="2026-05-11T10:30",
            )

            self.assertTrue(created)
            rows = repository.list_recent(limit=5)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].symbol, "600519")
            self.assertEqual(rows[0].recommendation, "buy")
            self.assertEqual(rows[0].market_regime, "trend")
            self.assertEqual(rows[0].sentiment_count, 3)


if __name__ == "__main__":
    import unittest

    unittest.main()
