from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import re
from typing import Any
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

import akshare as ak
import pandas as pd

from app.modules.sentiment_ingestion.contracts import (
    RawSentimentPayload,
    SentimentIngestionError,
    SentimentSourceConfigurationError,
    SentimentSourceDefinition,
    SentimentSourceNormalizationError,
    SentimentSourceNotRegisteredError,
    SentimentSourceUnavailableError,
)
from app.modules.sentiment_ingestion.presets import get_sample_feed_items

_SOURCE_TZ = ZoneInfo("Asia/Shanghai")
_STOCK_CODE_PATTERN = re.compile(r"(\d{6})")
_RELATIVE_TIME_PATTERN = re.compile(r"^(?P<amount>\d+)\s*(?P<unit>分钟|分|小时|时|天)前$")
_STOCK_TITLE_COLUMNS = ("新闻标题", "标题", "title")
_STOCK_CONTENT_COLUMNS = ("新闻内容", "摘要", "summary", "content")
_STOCK_PUBLISHED_AT_COLUMNS = ("发布时间", "时间", "日期时间", "published_at")
_STOCK_URL_COLUMNS = ("新闻链接", "链接", "url")
_STOCK_SOURCE_COLUMNS = ("文章来源", "来源", "source")
_STOCK_KEYWORD_COLUMNS = ("关键词", "股票代码", "证券代码", "symbol", "code")
_GLOBAL_TITLE_COLUMNS = ("标题", "新闻标题", "title")
_GLOBAL_CONTENT_COLUMNS = ("摘要", "内容", "summary", "content")
_GLOBAL_PUBLISHED_AT_COLUMNS = ("发布时间", "时间", "日期时间", "published_at")
_GLOBAL_URL_COLUMNS = ("链接", "新闻链接", "url")
_GLOBAL_TAG_COLUMNS = ("tag", "标签", "分类", "category")


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


class RssFeedSentimentSourceAdapter(SentimentSourceAdapter):
    adapter_name = "rss_feed"

    def collect(
        self,
        definition: SentimentSourceDefinition,
        *,
        now: datetime,
    ) -> list[RawSentimentPayload]:
        feed_url = self._coerce_feed_url(definition)
        timeout = self._coerce_timeout(definition)
        raw_xml = self._fetch_feed_xml(
            feed_url=feed_url,
            timeout=timeout,
            source_id=definition.metadata.source_id,
        )

        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError as exc:
            raise SentimentSourceNormalizationError(
                f"RSS/Atom feed for source '{definition.metadata.source_id}' could not be parsed.",
                details={
                    "source_id": definition.metadata.source_id,
                    "feed_url": feed_url,
                },
                cause=exc,
            ) from exc

        feed_kind = self._detect_feed_kind(root)
        if feed_kind == "atom":
            return self._parse_atom_feed(
                definition=definition,
                root=root,
                now=now,
                feed_url=feed_url,
            )
        return self._parse_rss_feed(
            definition=definition,
            root=root,
            now=now,
            feed_url=feed_url,
        )

    def _coerce_feed_url(self, definition: SentimentSourceDefinition) -> str:
        feed_url = definition.parameters.get("feed_url") or definition.parameters.get("url")
        if feed_url is None:
            feed_url = definition.metadata.base_url
        if not feed_url:
            raise SentimentSourceConfigurationError(
                f"RSS source '{definition.metadata.source_id}' must define 'feed_url' or base_url.",
                details={"source_id": definition.metadata.source_id},
            )
        return str(feed_url).strip()

    def _coerce_timeout(self, definition: SentimentSourceDefinition) -> float:
        raw_timeout = definition.parameters.get("timeout_seconds")
        if raw_timeout is None:
            raw_timeout = definition.parameters.get("timeout", 10)
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise SentimentSourceConfigurationError(
                f"RSS source '{definition.metadata.source_id}' must define a numeric timeout.",
                details={
                    "source_id": definition.metadata.source_id,
                    "timeout": raw_timeout,
                },
            ) from exc
        if timeout <= 0:
            raise SentimentSourceConfigurationError(
                f"RSS source '{definition.metadata.source_id}' must define a positive timeout.",
                details={
                    "source_id": definition.metadata.source_id,
                    "timeout": raw_timeout,
                },
            )
        return timeout

    def _fetch_feed_xml(
        self,
        *,
        feed_url: str,
        timeout: float,
        source_id: str,
    ) -> bytes:
        request = Request(
            feed_url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; trader-rss-adapter/1.0)",
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise SentimentSourceUnavailableError(
                f"RSS/Atom feed request failed for source '{source_id}'.",
                details={
                    "source_id": source_id,
                    "feed_url": feed_url,
                },
                cause=exc,
            ) from exc

    def _detect_feed_kind(self, root: ET.Element) -> str:
        root_name = self._local_name(root.tag)
        if root_name == "feed":
            return "atom"
        return "rss"

    def _parse_rss_feed(
        self,
        *,
        definition: SentimentSourceDefinition,
        root: ET.Element,
        now: datetime,
        feed_url: str,
    ) -> list[RawSentimentPayload]:
        items = root.findall("./channel/item")
        if not items:
            items = [element for element in root.iter() if self._local_name(element.tag) == "item"]

        payloads: list[RawSentimentPayload] = []
        for item in items:
            payloads.append(
                self._build_payload_from_element(
                    definition=definition,
                    element=item,
                    now=now,
                    feed_url=feed_url,
                    feed_kind="rss",
                )
            )
        return payloads

    def _parse_atom_feed(
        self,
        *,
        definition: SentimentSourceDefinition,
        root: ET.Element,
        now: datetime,
        feed_url: str,
    ) -> list[RawSentimentPayload]:
        entries = [element for element in root if self._local_name(element.tag) == "entry"]
        payloads: list[RawSentimentPayload] = []
        for entry in entries:
            payloads.append(
                self._build_payload_from_element(
                    definition=definition,
                    element=entry,
                    now=now,
                    feed_url=feed_url,
                    feed_kind="atom",
                )
            )
        return payloads

    def _build_payload_from_element(
        self,
        *,
        definition: SentimentSourceDefinition,
        element: ET.Element,
        now: datetime,
        feed_url: str,
        feed_kind: str,
    ) -> RawSentimentPayload:
        title = self._normalize_text(self._find_child_text(element, {"title"}))
        content = self._normalize_text(
            self._find_child_text(
                element,
                {"description", "encoded", "content", "summary"},
            )
        )
        if content is None:
            content = title

        if title is None or content is None:
            raise SentimentSourceNormalizationError(
                f"RSS/Atom feed for source '{definition.metadata.source_id}' is missing title/content.",
                details={
                    "source_id": definition.metadata.source_id,
                    "feed_url": feed_url,
                    "feed_kind": feed_kind,
                },
            )

        published_at = self._coerce_feed_timestamp(
            self._find_child_text(
                element,
                {"pubDate", "published", "updated", "date", "dc:date"},
            ),
            source_id=definition.metadata.source_id,
            now=now,
            feed_url=feed_url,
            feed_kind=feed_kind,
        )
        url = self._extract_link(element, feed_kind=feed_kind)
        source_item_id = self._extract_source_item_id(
            element,
            url=url,
            title=title,
            content=content,
            published_at=published_at,
            source_id=definition.metadata.source_id,
            feed_url=feed_url,
        )
        tags = self._collect_tags(element, feed_kind=feed_kind)
        raw_payload = {
            "source_id": definition.metadata.source_id,
            "feed_url": feed_url,
            "feed_kind": feed_kind,
            "title": title,
            "content": content,
            "url": url,
            "published_at": published_at.isoformat(),
            "source_item_id": source_item_id,
            "tags": tags,
            "row": self._element_to_dict(element),
        }
        return RawSentimentPayload(
            title=title,
            content=content,
            published_at=published_at,
            url=url,
            sentiment_score=None,
            tags=tags,
            source_item_id=source_item_id,
            raw_payload=raw_payload,
        )

    def _normalize_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = " ".join(value.split())
            return text or None
        if pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    def _merge_tags(self, *tag_groups: Iterable[str | None]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for tags in tag_groups:
            for raw_tag in tags:
                if raw_tag is None:
                    continue
                tag = str(raw_tag).strip()
                if not tag or tag in seen:
                    continue
                seen.add(tag)
                merged.append(tag)
        return merged

    def _build_source_item_id(
        self,
        *,
        source_id: str,
        title: str,
        content: str,
        published_at: datetime,
        symbol: str | None,
    ) -> str:
        return sha256(
            "|".join(
                [
                    source_id,
                    symbol or "",
                    published_at.isoformat(),
                    title,
                    content,
                ]
            ).encode("utf-8")
        ).hexdigest()

    def _coerce_feed_timestamp(
        self,
        value: Any,
        *,
        source_id: str,
        now: datetime,
        feed_url: str,
        feed_kind: str,
    ) -> datetime:
        if value is None:
            return now
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=_SOURCE_TZ)
        if isinstance(value, date):
            return datetime.combine(value, time.min, tzinfo=_SOURCE_TZ)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return now
            parsed = self._parse_rss_timestamp(text)
            if parsed is not None:
                return parsed
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return now
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=_SOURCE_TZ)
        raise SentimentSourceNormalizationError(
            f"RSS/Atom feed for source '{source_id}' has an unsupported timestamp value.",
            details={
                "source_id": source_id,
                "feed_url": feed_url,
                "feed_kind": feed_kind,
                "value_type": type(value).__name__,
            },
        )

    def _parse_rss_timestamp(self, value: str) -> datetime | None:
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M %z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(value, fmt)
            except ValueError:
                continue
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=_SOURCE_TZ)
        return None

    def _extract_link(self, element: ET.Element, *, feed_kind: str) -> str | None:
        if feed_kind == "atom":
            link_elements = [child for child in element if self._local_name(child.tag) == "link"]
            if not link_elements:
                return None
            preferred = next(
                (
                    child.attrib.get("href")
                    for child in link_elements
                    if child.attrib.get("rel", "alternate") == "alternate"
                    and child.attrib.get("href")
                ),
                None,
            )
            if preferred:
                return preferred.strip()
            for child in link_elements:
                href = child.attrib.get("href")
                if href:
                    return href.strip()
            return None

        link = self._find_child_text(element, {"link"})
        return link.strip() if isinstance(link, str) and link.strip() else None

    def _extract_source_item_id(
        self,
        element: ET.Element,
        *,
        url: str | None,
        title: str,
        content: str,
        published_at: datetime,
        source_id: str,
        feed_url: str,
    ) -> str:
        guid = self._find_child_text(element, {"guid", "id"})
        if guid:
            return guid.strip()
        if url:
            return url
        return self._build_source_item_id(
            source_id=source_id,
            title=title,
            content=content,
            published_at=published_at,
            symbol=feed_url,
        )

    def _collect_tags(self, element: ET.Element, *, feed_kind: str) -> list[str]:
        tags: list[str] = []
        if feed_kind == "atom":
            for child in element:
                if self._local_name(child.tag) != "category":
                    continue
                term = child.attrib.get("term") or child.text
                if term:
                    tags.append(term)
            return self._merge_tags(tags)

        for child in element:
            if self._local_name(child.tag) != "category":
                continue
            if child.text:
                tags.append(child.text)
        return self._merge_tags(tags)

    def _find_child_text(
        self,
        element: ET.Element,
        names: set[str],
    ) -> str | None:
        for child in element.iter():
            if child is element:
                continue
            if self._local_name(child.tag) not in names:
                continue
            text = self._element_text(child)
            if text is not None:
                return text
        return None

    def _element_text(self, element: ET.Element) -> str | None:
        text = " ".join(part.strip() for part in element.itertext())
        text = " ".join(text.split())
        return text or None

    def _local_name(self, tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def _element_to_dict(self, element: ET.Element) -> dict[str, Any]:
        data: dict[str, Any] = {"tag": self._local_name(element.tag)}
        if element.attrib:
            data["attributes"] = dict(element.attrib)
        text = self._element_text(element)
        if text is not None:
            data["text"] = text
        children: list[dict[str, Any]] = []
        for child in element:
            children.append(self._element_to_dict(child))
        if children:
            data["children"] = children
        return data


class AkshareStockNewsAdapter(SentimentSourceAdapter):
    adapter_name = "akshare_stock_news_em"

    def collect(
        self,
        definition: SentimentSourceDefinition,
        *,
        now: datetime,
    ) -> list[RawSentimentPayload]:
        mode = self._coerce_mode(definition)
        if mode == "stock":
            records: list[RawSentimentPayload] = []
            for symbol in self._resolve_symbols(definition):
                records.extend(
                    self._collect_stock_news_for_symbol(
                        definition,
                        symbol=symbol,
                        now=now,
                        fallback_used=False,
                        fallback_reason=None,
                    )
                )
            return records
        if mode == "global":
            return self._collect_global_news(
                definition,
                now=now,
                fallback_used=False,
                fallback_reason=None,
            )

        raise SentimentSourceConfigurationError(
            f"Sentiment source '{definition.metadata.source_id}' must set news_mode to "
            "'stock' or 'global'.",
            details={
                "source_id": definition.metadata.source_id,
                "news_mode": mode,
            },
        )

    def _collect_stock_news_for_symbol(
        self,
        definition: SentimentSourceDefinition,
        *,
        symbol: str,
        now: datetime,
        fallback_used: bool,
        fallback_reason: str | None,
    ) -> list[RawSentimentPayload]:
        limit = self._coerce_stock_limit(definition, default=20)
        allow_global_fallback = self._coerce_bool(
            definition.parameters.get("allow_global_fallback"),
            default=True,
            field_name="allow_global_fallback",
            source_id=definition.metadata.source_id,
        )

        try:
            frame = self._execute_query(
                "AKShare stock news",
                lambda: ak.stock_news_em(symbol=symbol),
                source_id=definition.metadata.source_id,
                retryable=True,
            )
            return self._normalize_stock_rows(
                definition=definition,
                symbol=symbol,
                frame=frame,
                now=now,
                limit=limit,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )
        except (SentimentSourceUnavailableError, SentimentSourceNormalizationError) as primary_error:
            if not allow_global_fallback:
                raise

            try:
                return self._collect_global_news(
                    definition,
                    now=now,
                    fallback_used=True,
                    fallback_reason=str(primary_error),
                    fallback_symbol=symbol,
                    limit=limit,
                )
            except (SentimentSourceUnavailableError, SentimentSourceNormalizationError) as fallback_error:
                raise self._build_fallback_failure(
                    definition=definition,
                    symbol=symbol,
                    primary_error=primary_error,
                    fallback_error=fallback_error,
                ) from fallback_error

    def _collect_global_news(
        self,
        definition: SentimentSourceDefinition,
        *,
        now: datetime,
        fallback_used: bool,
        fallback_reason: str | None,
        fallback_symbol: str | None = None,
        limit: int | None = None,
    ) -> list[RawSentimentPayload]:
        effective_limit = limit if limit is not None else self._coerce_limit(
            definition,
            default=20,
        )
        frame = self._execute_query(
            "AKShare global finance news",
            ak.stock_info_global_em,
            source_id=definition.metadata.source_id,
            retryable=True,
        )
        return self._normalize_global_rows(
            definition=definition,
            frame=frame,
            now=now,
            limit=effective_limit,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            fallback_symbol=fallback_symbol,
        )

    def _normalize_stock_rows(
        self,
        *,
        definition: SentimentSourceDefinition,
        symbol: str,
        frame: pd.DataFrame,
        now: datetime,
        limit: int,
        fallback_used: bool,
        fallback_reason: str | None,
    ) -> list[RawSentimentPayload]:
        if frame.empty:
            return []

        missing_columns = self._missing_columns(frame, _STOCK_TITLE_COLUMNS, _STOCK_CONTENT_COLUMNS, _STOCK_PUBLISHED_AT_COLUMNS)
        if missing_columns:
            raise SentimentSourceNormalizationError(
                f"AKShare stock news response for source '{definition.metadata.source_id}' is missing "
                f"required columns: {', '.join(missing_columns)}.",
                details={
                    "source_id": definition.metadata.source_id,
                    "symbol": symbol,
                    "missing_columns": missing_columns,
                    "available_columns": list(frame.columns),
                    "retrieval_mode": "stock_news_em",
                },
            )

        items: list[RawSentimentPayload] = []
        for row in frame.head(limit).to_dict("records"):
            title = self._require_text(
                row,
                _STOCK_TITLE_COLUMNS,
                field_name="title",
                source_id=definition.metadata.source_id,
                symbol=symbol,
            )
            content = self._require_text(
                row,
                _STOCK_CONTENT_COLUMNS,
                field_name="content",
                source_id=definition.metadata.source_id,
                symbol=symbol,
            )
            published_at = self._coerce_timestamp(
                self._pick_value(row, _STOCK_PUBLISHED_AT_COLUMNS),
                source_id=definition.metadata.source_id,
                field_name="published_at",
                now=now,
                symbol=symbol,
            )
            url = self._optional_text(row, _STOCK_URL_COLUMNS)
            article_source = self._optional_text(row, _STOCK_SOURCE_COLUMNS)
            keyword = self._optional_text(row, _STOCK_KEYWORD_COLUMNS)
            source_item_id = url or self._build_source_item_id(
                source_id=definition.metadata.source_id,
                title=title,
                content=content,
                published_at=published_at,
                symbol=symbol,
            )
            items.append(
                RawSentimentPayload(
                    title=title,
                    content=content,
                    published_at=published_at,
                    url=url,
                    sentiment_score=None,
                    tags=self._merge_tags(
                        ["akshare", "live-news", "stock-news"],
                        [symbol],
                        [keyword],
                        [article_source],
                    ),
                    source_item_id=source_item_id,
                    raw_payload={
                        "source_id": definition.metadata.source_id,
                        "news_mode": "stock",
                        "retrieval_mode": "stock_news_em",
                        "fallback_used": fallback_used,
                        "fallback_reason": fallback_reason,
                        "symbol": symbol,
                        "title": title,
                        "content": content,
                        "published_at": published_at.isoformat(),
                        "url": url,
                        "article_source": article_source,
                        "keyword": keyword,
                        "row": dict(row),
                    },
                )
            )
        return items

    def _normalize_global_rows(
        self,
        *,
        definition: SentimentSourceDefinition,
        frame: pd.DataFrame,
        now: datetime,
        limit: int,
        fallback_used: bool,
        fallback_reason: str | None,
        fallback_symbol: str | None,
    ) -> list[RawSentimentPayload]:
        if frame.empty:
            return []

        missing_columns = self._missing_columns(frame, _GLOBAL_TITLE_COLUMNS, _GLOBAL_CONTENT_COLUMNS, _GLOBAL_PUBLISHED_AT_COLUMNS)
        if missing_columns:
            raise SentimentSourceNormalizationError(
                f"AKShare global news response for source '{definition.metadata.source_id}' is missing "
                f"required columns: {', '.join(missing_columns)}.",
                details={
                    "source_id": definition.metadata.source_id,
                    "missing_columns": missing_columns,
                    "available_columns": list(frame.columns),
                    "retrieval_mode": "stock_info_global_em",
                },
            )

        items: list[RawSentimentPayload] = []
        for row in frame.head(limit).to_dict("records"):
            title = self._require_text(
                row,
                _GLOBAL_TITLE_COLUMNS,
                field_name="title",
                source_id=definition.metadata.source_id,
            )
            content = self._require_text(
                row,
                _GLOBAL_CONTENT_COLUMNS,
                field_name="content",
                source_id=definition.metadata.source_id,
            )
            published_at = self._coerce_timestamp(
                self._pick_value(row, _GLOBAL_PUBLISHED_AT_COLUMNS),
                source_id=definition.metadata.source_id,
                field_name="published_at",
                now=now,
            )
            url = self._optional_text(row, _GLOBAL_URL_COLUMNS)
            tag = self._optional_text(row, _GLOBAL_TAG_COLUMNS)
            source_item_id = url or self._build_source_item_id(
                source_id=definition.metadata.source_id,
                title=title,
                content=content,
                published_at=published_at,
                symbol=fallback_symbol,
            )
            items.append(
                RawSentimentPayload(
                    title=title,
                    content=content,
                    published_at=published_at,
                    url=url,
                    sentiment_score=None,
                    tags=self._merge_tags(
                        ["akshare", "live-news", "global-news"],
                        [tag],
                    ),
                    source_item_id=source_item_id,
                    raw_payload={
                        "source_id": definition.metadata.source_id,
                        "news_mode": "global",
                        "retrieval_mode": "stock_info_global_em",
                        "fallback_used": fallback_used,
                        "fallback_reason": fallback_reason,
                        "requested_symbol": fallback_symbol,
                        "title": title,
                        "content": content,
                        "published_at": published_at.isoformat(),
                        "url": url,
                        "tag": tag,
                        "row": dict(row),
                    },
                )
            )
        return items

    def _build_fallback_failure(
        self,
        *,
        definition: SentimentSourceDefinition,
        symbol: str,
        primary_error: SentimentSourceUnavailableError | SentimentSourceNormalizationError,
        fallback_error: SentimentSourceUnavailableError | SentimentSourceNormalizationError,
    ) -> SentimentIngestionError:
        error_cls: type[SentimentIngestionError]
        if isinstance(primary_error, SentimentSourceNormalizationError) or isinstance(
            fallback_error,
            SentimentSourceNormalizationError,
        ):
            error_cls = SentimentSourceNormalizationError
        else:
            error_cls = SentimentSourceUnavailableError

        return error_cls(
            f"AKShare live news could not be collected for source '{definition.metadata.source_id}' "
            f"(symbol={symbol}). Both the stock feed and the global fallback failed.",
            details={
                "source_id": definition.metadata.source_id,
                "symbol": symbol,
                "primary_error": type(primary_error).__name__,
                "primary_message": str(primary_error),
                "fallback_error": type(fallback_error).__name__,
                "fallback_message": str(fallback_error),
            },
            cause=fallback_error,
        )

    def _resolve_symbol(self, definition: SentimentSourceDefinition) -> str:
        symbol = definition.parameters.get("symbol")
        if symbol is None:
            raise SentimentSourceConfigurationError(
                f"AKShare live news source '{definition.metadata.source_id}' must define 'symbol' or 'symbols'."
            )
        return _normalize_stock_code(str(symbol))

    def _resolve_symbols(self, definition: SentimentSourceDefinition) -> list[str]:
        raw_symbols = definition.parameters.get("symbols")
        if raw_symbols is None:
            return [self._resolve_symbol(definition)]

        if isinstance(raw_symbols, str):
            candidates = [raw_symbols]
        elif isinstance(raw_symbols, Iterable):
            candidates = [str(item).strip() for item in raw_symbols if str(item).strip()]
        else:
            raise SentimentSourceConfigurationError(
                f"AKShare live news source '{definition.metadata.source_id}' must define 'symbols' as an iterable.",
                details={
                    "source_id": definition.metadata.source_id,
                    "symbols": raw_symbols,
                },
            )

        symbols = [_normalize_stock_code(symbol) for symbol in candidates]
        if not symbols:
            raise SentimentSourceConfigurationError(
                f"AKShare live news source '{definition.metadata.source_id}' resolved no valid symbols.",
                details={"source_id": definition.metadata.source_id},
            )
        return symbols

    def _coerce_mode(self, definition: SentimentSourceDefinition) -> str:
        raw_mode = definition.parameters.get("news_mode", "stock")
        mode = str(raw_mode).strip().lower()
        if not mode:
            return "stock"
        return mode

    def _coerce_stock_limit(self, definition: SentimentSourceDefinition, *, default: int) -> int:
        raw_limit = definition.parameters.get("max_items_per_symbol")
        if raw_limit is None:
            raw_limit = definition.parameters.get("limit", default)
        return self._coerce_limit_from_value(definition, raw_limit=raw_limit)

    def _coerce_limit(self, definition: SentimentSourceDefinition, *, default: int) -> int:
        raw_limit = definition.parameters.get("limit", default)
        return self._coerce_limit_from_value(definition, raw_limit=raw_limit)

    def _coerce_limit_from_value(
        self,
        definition: SentimentSourceDefinition,
        *,
        raw_limit: Any,
    ) -> int:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise SentimentSourceConfigurationError(
                f"Sentiment source '{definition.metadata.source_id}' must define a positive integer 'limit'.",
                details={
                    "source_id": definition.metadata.source_id,
                    "limit": raw_limit,
                },
            ) from exc
        if limit <= 0:
            raise SentimentSourceConfigurationError(
                f"Sentiment source '{definition.metadata.source_id}' must define a positive integer 'limit'.",
                details={
                    "source_id": definition.metadata.source_id,
                    "limit": raw_limit,
                },
            )
        return limit

    def _coerce_bool(
        self,
        value: Any,
        *,
        default: bool,
        field_name: str,
        source_id: str,
    ) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "no", "n", "off"}:
                return False

        raise SentimentSourceConfigurationError(
            f"Sentiment source '{source_id}' field '{field_name}' must be boolean-like.",
            details={
                "source_id": source_id,
                "field": field_name,
                "value": value,
            },
        )

    def _execute_query(
        self,
        operation: str,
        fetcher: Any,
        *,
        source_id: str,
        retryable: bool,
    ) -> pd.DataFrame:
        try:
            frame = fetcher()
        except Exception as exc:
            error_cls = SentimentSourceUnavailableError if retryable else SentimentSourceConfigurationError
            raise error_cls(
                f"AKShare request failed for {operation}",
                details={
                    "source_id": source_id,
                    "operation": operation,
                },
                cause=exc,
            ) from exc

        if not isinstance(frame, pd.DataFrame):
            raise SentimentSourceNormalizationError(
                f"AKShare response was not a pandas DataFrame for {operation}",
                details={
                    "source_id": source_id,
                    "operation": operation,
                    "response_type": type(frame).__name__,
                },
            )
        return frame

    def _missing_columns(
        self,
        frame: pd.DataFrame,
        *column_groups: tuple[str, ...],
    ) -> list[str]:
        missing: list[str] = []
        available = set(frame.columns)
        for group in column_groups:
            if any(candidate in available for candidate in group):
                continue
            missing.append("/".join(group))
        return missing

    def _require_text(
        self,
        row: dict[str, Any],
        candidates: tuple[str, ...],
        *,
        field_name: str,
        source_id: str,
        symbol: str | None = None,
    ) -> str:
        value = self._pick_value(row, candidates)
        text = self._normalize_text(value)
        if text is None:
            raise SentimentSourceNormalizationError(
                f"AKShare {field_name} is missing from news data",
                details={
                    "source_id": source_id,
                    "field": field_name,
                    "symbol": symbol,
                    "available_columns": list(row.keys()),
                },
            )
        return text

    def _optional_text(
        self,
        row: dict[str, Any],
        candidates: tuple[str, ...],
    ) -> str | None:
        return self._normalize_text(self._pick_value(row, candidates))

    def _coerce_timestamp(
        self,
        value: Any,
        *,
        source_id: str,
        field_name: str,
        now: datetime,
        symbol: str | None = None,
    ) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=_SOURCE_TZ)
        if isinstance(value, date):
            return datetime.combine(value, time.min, tzinfo=_SOURCE_TZ)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                raise SentimentSourceNormalizationError(
                    f"AKShare {field_name} is empty",
                    details={
                        "source_id": source_id,
                        "field": field_name,
                        "symbol": symbol,
                    },
                )
            relative = self._parse_relative_timestamp(text, now=now)
            if relative is not None:
                return relative

            candidate = text.replace("Z", "+00:00")
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M",
                "%Y-%m-%d",
                "%Y/%m/%d",
            ):
                try:
                    parsed = datetime.strptime(candidate, fmt)
                except ValueError:
                    continue
                return parsed.replace(tzinfo=_SOURCE_TZ)

            try:
                parsed = datetime.fromisoformat(candidate)
            except ValueError as exc:
                raise SentimentSourceNormalizationError(
                    f"AKShare {field_name} could not be parsed as a datetime",
                    details={
                        "source_id": source_id,
                        "field": field_name,
                        "symbol": symbol,
                        "value": value,
                    },
                    cause=exc,
                ) from exc
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=_SOURCE_TZ)

        raise SentimentSourceNormalizationError(
            f"AKShare {field_name} has an unsupported value type",
            details={
                "source_id": source_id,
                "field": field_name,
                "symbol": symbol,
                "value_type": type(value).__name__,
            },
        )

    def _parse_relative_timestamp(self, text: str, *, now: datetime) -> datetime | None:
        if text in {"刚刚", "刚才"}:
            return now

        match = _RELATIVE_TIME_PATTERN.match(text)
        if match is None:
            return None

        amount = int(match.group("amount"))
        unit = match.group("unit")
        if unit in {"分钟", "分"}:
            delta = timedelta(minutes=amount)
        elif unit in {"小时", "时"}:
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)
        return now - delta

    def _normalize_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = " ".join(value.split())
            return text or None
        if pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    def _pick_value(self, row: Mapping[str, Any], candidates: tuple[str, ...]) -> Any | None:
        for candidate in candidates:
            if candidate not in row:
                continue
            value = row[candidate]
            if value is None:
                continue
            if isinstance(value, str):
                if value.strip():
                    return value
                continue
            if not pd.isna(value):
                return value
        return None

    def _merge_tags(self, *tag_groups: Iterable[str | None]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for tags in tag_groups:
            for raw_tag in tags:
                if raw_tag is None:
                    continue
                tag = str(raw_tag).strip()
                if not tag or tag in seen:
                    continue
                seen.add(tag)
                merged.append(tag)
        return merged

    def _build_source_item_id(
        self,
        *,
        source_id: str,
        title: str,
        content: str,
        published_at: datetime,
        symbol: str | None,
    ) -> str:
        digest = self._hash_text(
            "|".join(
                [
                    source_id,
                    symbol or "",
                    published_at.isoformat(),
                    title,
                    content,
                ]
            )
        )
        return digest

    def _hash_text(self, value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()


def _normalize_stock_code(symbol: str) -> str:
    raw = str(symbol).strip()
    if not raw:
        raise SentimentSourceConfigurationError("AKShare live news source symbol must not be empty.")

    match = _STOCK_CODE_PATTERN.search(raw)
    if match:
        return match.group(1)

    digits = "".join(character for character in raw if character.isdigit())
    if 1 <= len(digits) <= 6:
        return digits.zfill(6)

    raise SentimentSourceConfigurationError(
        f"Symbol '{symbol}' is not a valid A-share stock code.",
        details={"symbol": raw},
    )


def build_default_registry() -> SentimentSourceRegistry:
    return SentimentSourceRegistry(
        adapters=[
            StaticSentimentSourceAdapter(),
            SampleSentimentSourceAdapter(),
            RssFeedSentimentSourceAdapter(),
            AkshareStockNewsAdapter(),
        ]
    )


AKShareLiveNewsSourceAdapter = AkshareStockNewsAdapter
