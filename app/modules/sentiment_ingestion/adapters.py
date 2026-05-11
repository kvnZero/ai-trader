from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

import akshare as ak

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


class AkshareStockNewsAdapter(SentimentSourceAdapter):
    adapter_name = "akshare_stock_news_em"

    def collect(
        self,
        definition: SentimentSourceDefinition,
        *,
        now: datetime,
    ) -> list[RawSentimentPayload]:
        del now
        symbols = definition.parameters.get("symbols") or definition.parameters.get("symbol")
        if isinstance(symbols, str):
            symbol_list = [symbols]
        elif isinstance(symbols, Iterable):
            symbol_list = [str(item).strip() for item in symbols if str(item).strip()]
        else:
            raise SentimentSourceConfigurationError(
                f"AkShare source '{definition.metadata.source_id}' must define 'symbol' or 'symbols'."
            )

        if not symbol_list:
            raise SentimentSourceConfigurationError(
                f"AkShare source '{definition.metadata.source_id}' resolved no valid symbols."
            )

        max_items_per_symbol = int(definition.parameters.get("max_items_per_symbol", 5))
        records: list[RawSentimentPayload] = []

        for symbol in symbol_list:
            frame = self._fetch_frame(symbol)
            for row in frame.head(max_items_per_symbol).to_dict("records"):
                records.append(self._coerce_row(symbol=symbol, row=row))
        return records

    def _fetch_frame(self, symbol: str):
        try:
            frame = ak.stock_news_em(symbol=symbol)
        except Exception as exc:
            raise SentimentSourceConfigurationError(
                f"AkShare news fetch failed for symbol '{symbol}': {exc}"
            ) from exc

        required_columns = {"新闻标题", "新闻内容", "发布时间", "新闻链接"}
        if not required_columns.issubset(set(frame.columns)):
            raise SentimentSourceConfigurationError(
                f"AkShare news response for '{symbol}' is missing required columns."
            )
        return frame

    def _coerce_row(self, *, symbol: str, row: Mapping[str, Any]) -> RawSentimentPayload:
        title = str(row.get("新闻标题", "")).strip()
        content = str(row.get("新闻内容", "")).strip()
        published_at = str(row.get("发布时间", "")).strip()
        url = str(row.get("新闻链接", "")).strip() or None
        source_name = str(row.get("文章来源", "东方财富")).strip() or "东方财富"
        keyword = str(row.get("关键词", symbol)).strip() or symbol

        return RawSentimentPayload(
            title=title,
            content=content,
            published_at=published_at,
            url=url,
            sentiment_score=self._estimate_sentiment_score(title=title, content=content),
            tags=["a-share", "news", source_name, keyword],
            source_item_id=f"{symbol}:{published_at}:{title[:32]}",
            raw_payload=dict(row),
        )

    def _estimate_sentiment_score(self, *, title: str, content: str) -> float:
        text = f"{title} {content}"
        positive_keywords = ("增长", "回升", "突破", "增持", "利好", "修复", "回流", "景气")
        negative_keywords = ("下滑", "回落", "亏损", "减持", "利空", "承压", "风险", "走弱")
        score = 0.0
        for keyword in positive_keywords:
            if keyword in text:
                score += 0.14
        for keyword in negative_keywords:
            if keyword in text:
                score -= 0.14
        return max(-1.0, min(1.0, round(score, 2)))


def build_default_registry() -> SentimentSourceRegistry:
    return SentimentSourceRegistry(
        adapters=[
            StaticSentimentSourceAdapter(),
            SampleSentimentSourceAdapter(),
            AkshareStockNewsAdapter(),
        ]
    )
