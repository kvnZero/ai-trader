from __future__ import annotations

from datetime import datetime
from io import BytesIO
from urllib.error import URLError
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.modules.sentiment_ingestion.adapters import RssFeedSentimentSourceAdapter
from app.modules.sentiment_ingestion.contracts import (
    SentimentSourceCategory,
    SentimentSourceConfigurationError,
    SentimentSourceDefinition,
    SentimentSourceMetadata,
    SentimentSourceUnavailableError,
)


class _MockResponse:
    def __init__(self, payload: bytes) -> None:
        self._buffer = BytesIO(payload)

    def read(self) -> bytes:
        return self._buffer.read()

    def __enter__(self) -> "_MockResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb


class RssFeedSentimentSourceAdapterTests(TestCase):
    def _definition(self, *, feed_url: str) -> SentimentSourceDefinition:
        return SentimentSourceDefinition(
            metadata=SentimentSourceMetadata(
                source_id="rss-source",
                source_name="RSS Source",
                category=SentimentSourceCategory.FINANCE_NEWS,
                base_url=feed_url,
            ),
            adapter_name="rss_feed",
        )

    def test_collect_parses_rss_items(self) -> None:
        now = datetime(2026, 5, 11, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Feed</title>
            <item>
              <title>RSS Headline</title>
              <description>RSS Content</description>
              <link>https://example.com/rss-1</link>
              <guid>rss-1</guid>
              <pubDate>Mon, 11 May 2026 09:00:00 +0800</pubDate>
              <category>market</category>
              <category>stocks</category>
            </item>
          </channel>
        </rss>
        """

        with patch(
            "app.modules.sentiment_ingestion.adapters.urlopen",
            return_value=_MockResponse(xml),
        ):
            items = RssFeedSentimentSourceAdapter().collect(
                self._definition(feed_url="https://example.com/rss.xml"),
                now=now,
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "RSS Headline")
        self.assertEqual(items[0].content, "RSS Content")
        self.assertEqual(items[0].url, "https://example.com/rss-1")
        self.assertEqual(items[0].source_item_id, "rss-1")
        self.assertEqual(items[0].tags, ["market", "stocks"])
        self.assertEqual(
            items[0].published_at,
            datetime(2026, 5, 11, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

    def test_collect_parses_atom_entries_and_falls_back_to_now(self) -> None:
        now = datetime(2026, 5, 11, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        xml = b"""<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>Atom Feed</title>
          <entry>
            <title>Atom Headline</title>
            <summary>Atom Summary</summary>
            <link href="https://example.com/atom-1" rel="alternate" />
            <id>tag:example.com,2026:1</id>
            <category term="policy" />
          </entry>
        </feed>
        """

        with patch(
            "app.modules.sentiment_ingestion.adapters.urlopen",
            return_value=_MockResponse(xml),
        ):
            items = RssFeedSentimentSourceAdapter().collect(
                self._definition(feed_url="https://example.com/atom.xml"),
                now=now,
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Atom Headline")
        self.assertEqual(items[0].content, "Atom Summary")
        self.assertEqual(items[0].url, "https://example.com/atom-1")
        self.assertEqual(items[0].source_item_id, "tag:example.com,2026:1")
        self.assertEqual(items[0].tags, ["policy"])
        self.assertEqual(items[0].published_at, now)

    def test_collect_raises_unavailable_on_network_failure(self) -> None:
        now = datetime(2026, 5, 11, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch(
            "app.modules.sentiment_ingestion.adapters.urlopen",
            side_effect=URLError("boom"),
        ):
            with self.assertRaises(SentimentSourceUnavailableError):
                RssFeedSentimentSourceAdapter().collect(
                    self._definition(feed_url="https://example.com/rss.xml"),
                    now=now,
                )

    def test_collect_requires_feed_url(self) -> None:
        definition = SentimentSourceDefinition(
            metadata=SentimentSourceMetadata(
                source_id="rss-source",
                source_name="RSS Source",
                category=SentimentSourceCategory.FINANCE_NEWS,
            ),
            adapter_name="rss_feed",
        )
        with self.assertRaises(SentimentSourceConfigurationError):
            RssFeedSentimentSourceAdapter().collect(
                definition,
                now=datetime(2026, 5, 11, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
