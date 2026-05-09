from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

from app.domain import SentimentItem


class SentimentIngestionError(Exception):
    """Base error for the sentiment ingestion capability."""


class SentimentSourceConfigurationError(SentimentIngestionError):
    """Raised when a source definition cannot be ingested as configured."""


class SentimentSourceNotRegisteredError(SentimentIngestionError):
    """Raised when a source definition references an unknown adapter."""


class SentimentSourceCategory(StrEnum):
    FINANCE_NEWS = "finance_news"
    FAST_NEWS = "fast_news"
    PLATFORM = "platform"


class SuppressionReason(StrEnum):
    DUPLICATE = "duplicate"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class SentimentSourceMetadata:
    source_id: str
    source_name: str
    category: SentimentSourceCategory
    base_url: str | None = None
    region: str = "CN"
    language: str = "zh-CN"
    tags: list[str] = field(default_factory=list)
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class SentimentSourceDefinition:
    metadata: SentimentSourceMetadata
    adapter_name: str
    enabled: bool = True
    max_item_age: timedelta | None = None
    default_item_tags: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawSentimentPayload:
    title: str
    content: str
    published_at: datetime | date | str
    url: str | None = None
    sentiment_score: float | None = None
    tags: list[str] = field(default_factory=list)
    source_item_id: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IngestedSentimentRecord:
    item: SentimentItem
    source_metadata: SentimentSourceMetadata
    adapter_name: str
    dedup_key: str
    collected_at: datetime
    age_seconds: int
    source_item_id: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SuppressedSentimentRecord:
    source_metadata: SentimentSourceMetadata
    adapter_name: str
    title: str
    published_at: datetime
    dedup_key: str
    reason: SuppressionReason
    age_seconds: int
    source_item_id: str | None = None


@dataclass(frozen=True, slots=True)
class SentimentSourceRun:
    source_metadata: SentimentSourceMetadata
    adapter_name: str
    executed_at: datetime
    fetched_count: int
    emitted_count: int
    duplicate_count: int
    stale_count: int
    max_item_age_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class SentimentIngestionResult:
    records: list[IngestedSentimentRecord] = field(default_factory=list)
    source_runs: list[SentimentSourceRun] = field(default_factory=list)
    duplicate_records: list[SuppressedSentimentRecord] = field(default_factory=list)
    stale_records: list[SuppressedSentimentRecord] = field(default_factory=list)

    @property
    def items(self) -> list[SentimentItem]:
        return [record.item for record in self.records]

    @property
    def dedup_keys(self) -> list[str]:
        return [record.dedup_key for record in self.records]
