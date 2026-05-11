from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest import TestCase

from app.modules.sentiment_ingestion import (
    RawSentimentPayload,
    SentimentIngestionService,
    SentimentSourceCategory,
    SentimentSourceDefinition,
    SentimentSourceMetadata,
)
from app.persistence import SentimentRepository, init_database


class SentimentRepositoryTests(TestCase):
    def test_read_latest_returns_persisted_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "sentiment.db"
            database = init_database(str(database_path))
            repository = SentimentRepository(database)

            now = datetime(2026, 5, 11, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
            result = SentimentIngestionService(
                default_sources=[
                    SentimentSourceDefinition(
                        metadata=SentimentSourceMetadata(
                            source_id="sample-source",
                            source_name="Sample Source",
                            category=SentimentSourceCategory.FINANCE_NEWS,
                        ),
                        adapter_name="static",
                        parameters={
                            "items": [
                                RawSentimentPayload(
                                    title="Sample Headline",
                                    content="Sample Content",
                                    published_at=now,
                                    tags=["sample"],
                                )
                            ]
                        },
                    )
                ]
            ).ingest(now=now)

            run_id = repository.start_run(started_at=now)
            assert run_id is not None
            repository.record_success(run_id=run_id, result=result, completed_at=now)

            snapshot = repository.read_latest(symbols=["600519"])

            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot["updated_at"], now.isoformat())
            self.assertEqual(len(snapshot["items"]), 1)
            self.assertEqual(snapshot["items"][0].title, "Sample Headline")
            self.assertEqual(len(snapshot["source_runs"]), 1)
            self.assertEqual(snapshot["source_runs"][0].source_name, "Sample Source")
            self.assertEqual(len(snapshot["source_failures"]), 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
