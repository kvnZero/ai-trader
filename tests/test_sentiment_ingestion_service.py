from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import unittest

from app.modules.sentiment_ingestion import (
    RawSentimentPayload,
    SentimentIngestionService,
    SentimentSourceAdapter,
    SentimentSourceCategory,
    SentimentSourceDefinition,
    SentimentSourceMetadata,
    SentimentSourceRegistry,
    StaticSentimentSourceAdapter,
)
from app.modules.sentiment_ingestion.contracts import SentimentSourceUnavailableError


class _FailingSentimentSourceAdapter(SentimentSourceAdapter):
    adapter_name = "failing"

    def collect(
        self,
        definition: SentimentSourceDefinition,
        *,
        now: datetime,
    ) -> list[RawSentimentPayload]:
        del now
        raise SentimentSourceUnavailableError(
            "boom",
            details={"source_id": definition.metadata.source_id},
        )


class SentimentIngestionServiceTests(unittest.TestCase):
    def test_ingest_continues_when_one_source_fails(self) -> None:
        now = datetime(2026, 5, 11, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        registry = SentimentSourceRegistry(
            [StaticSentimentSourceAdapter(), _FailingSentimentSourceAdapter()]
        )
        sources = [
            SentimentSourceDefinition(
                metadata=SentimentSourceMetadata(
                    source_id="fail-source",
                    source_name="Fail Source",
                    category=SentimentSourceCategory.FINANCE_NEWS,
                ),
                adapter_name="failing",
            ),
            SentimentSourceDefinition(
                metadata=SentimentSourceMetadata(
                    source_id="ok-source",
                    source_name="OK Source",
                    category=SentimentSourceCategory.FINANCE_NEWS,
                ),
                adapter_name="static",
                parameters={
                    "items": [
                        RawSentimentPayload(
                            title="foo",
                            content="bar",
                            published_at=now,
                        )
                    ]
                },
            ),
        ]

        result = SentimentIngestionService(
            registry=registry,
            default_sources=sources,
        ).ingest(now=now)

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].item.title, "foo")
        self.assertEqual(len(result.source_failures), 1)
        self.assertEqual(result.source_failures[0].error_code, "sentiment_source_unavailable")
        self.assertEqual(result.source_failures[0].source_metadata.source_id, "fail-source")
        self.assertEqual(len(result.source_runs), 2)


if __name__ == "__main__":
    unittest.main()
