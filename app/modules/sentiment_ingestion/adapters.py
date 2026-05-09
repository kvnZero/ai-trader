from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from app.modules.sentiment_ingestion.contracts import (
    RawSentimentPayload,
    SentimentSourceConfigurationError,
    SentimentSourceDefinition,
    SentimentSourceNotRegisteredError,
)
from app.modules.sentiment_ingestion.presets import get_sample_feed_items


class SentimentSourceAdapter(ABC):
    adapter_name: str

    @abstractmethod
    def collect(
        self,
        definition: SentimentSourceDefinition,
        *,
        now: datetime,
    ) -> list[RawSentimentPayload]:
        """Fetch raw source items for a single source definition."""


class SentimentSourceRegistry:
    def __init__(
        self,
        adapters: Iterable[SentimentSourceAdapter] | None = None,
    ) -> None:
        self._adapters: dict[str, SentimentSourceAdapter] = {}
        for adapter in adapters or ():
            self.register(adapter)

    def register(self, adapter: SentimentSourceAdapter) -> None:
        self._adapters[adapter.adapter_name] = adapter

    def resolve(self, adapter_name: str) -> SentimentSourceAdapter:
        try:
            return self._adapters[adapter_name]
        except KeyError as exc:
            raise SentimentSourceNotRegisteredError(
                f"Sentiment source adapter '{adapter_name}' is not registered."
            ) from exc


class StaticSentimentSourceAdapter(SentimentSourceAdapter):
    adapter_name = "static"

    def collect(
        self,
        definition: SentimentSourceDefinition,
        *,
        now: datetime,
    ) -> list[RawSentimentPayload]:
        del now
        raw_items = definition.parameters.get("items", ())
        if isinstance(raw_items, (str, bytes)) or not isinstance(raw_items, Iterable):
            raise SentimentSourceConfigurationError(
                f"Static source '{definition.metadata.source_id}' must define iterable items."
            )

        return [self._coerce_item(definition=definition, item=item) for item in raw_items]

    def _coerce_item(
        self,
        *,
        definition: SentimentSourceDefinition,
        item: RawSentimentPayload | Mapping[str, Any] | Any,
    ) -> RawSentimentPayload:
        if isinstance(item, RawSentimentPayload):
            return item

        if not isinstance(item, Mapping):
            raise SentimentSourceConfigurationError(
                f"Static source '{definition.metadata.source_id}' contains a non-mapping item."
            )

        if not item.get("title") or not item.get("content") or "published_at" not in item:
            raise SentimentSourceConfigurationError(
                f"Static source '{definition.metadata.source_id}' items require "
                "'title', 'content', and 'published_at'."
            )

        return RawSentimentPayload(
            title=str(item["title"]),
            content=str(item["content"]),
            published_at=item["published_at"],
            url=str(item["url"]) if item.get("url") else None,
            sentiment_score=(
                float(item["sentiment_score"])
                if item.get("sentiment_score") is not None
                else None
            ),
            tags=[str(tag) for tag in item.get("tags", ())],
            source_item_id=str(item["source_item_id"]) if item.get("source_item_id") else None,
            raw_payload=dict(item),
        )


class SampleSentimentSourceAdapter(SentimentSourceAdapter):
    adapter_name = "sample"

    def collect(
        self,
        definition: SentimentSourceDefinition,
        *,
        now: datetime,
    ) -> list[RawSentimentPayload]:
        sample_feed = definition.parameters.get("sample_feed")
        if not sample_feed:
            raise SentimentSourceConfigurationError(
                f"Sample source '{definition.metadata.source_id}' must define 'sample_feed'."
            )

        return get_sample_feed_items(str(sample_feed), now=now)


def build_default_registry() -> SentimentSourceRegistry:
    return SentimentSourceRegistry(
        adapters=[
            StaticSentimentSourceAdapter(),
            SampleSentimentSourceAdapter(),
        ]
    )
