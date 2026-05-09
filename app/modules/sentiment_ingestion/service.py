from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from app.domain import SentimentItem
from app.modules.sentiment_ingestion.adapters import (
    SentimentSourceRegistry,
    build_default_registry,
)
from app.modules.sentiment_ingestion.contracts import (
    IngestedSentimentRecord,
    RawSentimentPayload,
    SentimentIngestionResult,
    SentimentSourceConfigurationError,
    SentimentSourceDefinition,
    SentimentSourceRun,
    SuppressedSentimentRecord,
    SuppressionReason,
)
from app.modules.sentiment_ingestion.presets import build_default_sample_sources


class SentimentIngestionService:
    def __init__(
        self,
        *,
        registry: SentimentSourceRegistry | None = None,
        default_sources: Iterable[SentimentSourceDefinition] | None = None,
        default_max_item_age: timedelta = timedelta(hours=12),
        default_timezone: ZoneInfo | None = None,
    ) -> None:
        self._registry = registry or build_default_registry()
        self._default_sources = list(default_sources or build_default_sample_sources())
        self._default_max_item_age = default_max_item_age
        self._default_timezone = default_timezone or ZoneInfo("Asia/Shanghai")

    def ingest(
        self,
        sources: Iterable[SentimentSourceDefinition] | None = None,
        *,
        now: datetime | None = None,
        seen_dedup_keys: Collection[str] | None = None,
        max_item_age: timedelta | None = None,
    ) -> SentimentIngestionResult:
        effective_now = self._normalize_datetime(now or datetime.now(self._default_timezone))
        active_sources = [
            source
            for source in list(sources or self._default_sources)
            if source.enabled
        ]
        dedup_keys = set(seen_dedup_keys or ())
        records: list[IngestedSentimentRecord] = []
        duplicate_records: list[SuppressedSentimentRecord] = []
        stale_records: list[SuppressedSentimentRecord] = []
        source_runs: list[SentimentSourceRun] = []

        for source in active_sources:
            adapter = self._registry.resolve(source.adapter_name)
            raw_items = adapter.collect(source, now=effective_now)
            emitted_count = 0
            duplicate_count = 0
            stale_count = 0
            effective_max_age = source.max_item_age or max_item_age or self._default_max_item_age

            for raw_item in raw_items:
                record = self._normalize_item(
                    source=source,
                    raw_item=raw_item,
                    collected_at=effective_now,
                )
                if self._is_stale(
                    published_at=record.item.published_at,
                    now=effective_now,
                    max_item_age=effective_max_age,
                ):
                    stale_records.append(
                        self._build_suppressed_record(
                            record=record,
                            reason=SuppressionReason.STALE,
                        )
                    )
                    stale_count += 1
                    continue

                if record.dedup_key in dedup_keys:
                    duplicate_records.append(
                        self._build_suppressed_record(
                            record=record,
                            reason=SuppressionReason.DUPLICATE,
                        )
                    )
                    duplicate_count += 1
                    continue

                dedup_keys.add(record.dedup_key)
                records.append(record)
                emitted_count += 1

            source_runs.append(
                SentimentSourceRun(
                    source_metadata=source.metadata,
                    adapter_name=source.adapter_name,
                    executed_at=effective_now,
                    fetched_count=len(raw_items),
                    emitted_count=emitted_count,
                    duplicate_count=duplicate_count,
                    stale_count=stale_count,
                    max_item_age_seconds=(
                        int(effective_max_age.total_seconds())
                        if effective_max_age is not None
                        else None
                    ),
                )
            )

        records.sort(key=lambda record: record.item.published_at, reverse=True)
        duplicate_records.sort(key=lambda record: record.published_at, reverse=True)
        stale_records.sort(key=lambda record: record.published_at, reverse=True)
        source_runs.sort(key=lambda run: run.source_metadata.source_id)
        return SentimentIngestionResult(
            records=records,
            source_runs=source_runs,
            duplicate_records=duplicate_records,
            stale_records=stale_records,
        )

    def _normalize_item(
        self,
        *,
        source: SentimentSourceDefinition,
        raw_item: RawSentimentPayload,
        collected_at: datetime,
    ) -> IngestedSentimentRecord:
        title = self._normalize_text(raw_item.title, field_name="title")
        content = self._normalize_text(raw_item.content, field_name="content")
        published_at = self._coerce_timestamp(raw_item.published_at)
        url = self._normalize_optional_text(raw_item.url)
        sentiment_score = self._coerce_sentiment_score(raw_item.sentiment_score)
        tags = self._merge_tags(
            source.default_item_tags,
            source.metadata.tags,
            raw_item.tags,
        )
        raw_reference = self._build_raw_reference(
            source_id=source.metadata.source_id,
            source_item_id=raw_item.source_item_id,
            fallback_key=self._hash_text(f"{title}|{content}"),
        )
        item = SentimentItem(
            source=source.metadata.source_name,
            title=title,
            content=content,
            published_at=published_at,
            url=url,
            sentiment_score=sentiment_score,
            tags=tags,
            raw_reference=raw_reference,
        )
        dedup_key = self._build_dedup_key(
            title=title,
            content=content,
            url=url,
        )
        age_seconds = max(0, int((collected_at - published_at).total_seconds()))
        return IngestedSentimentRecord(
            item=item,
            source_metadata=source.metadata,
            adapter_name=source.adapter_name,
            dedup_key=dedup_key,
            collected_at=collected_at,
            age_seconds=age_seconds,
            source_item_id=raw_item.source_item_id,
            raw_payload=dict(raw_item.raw_payload),
        )

    def _build_suppressed_record(
        self,
        *,
        record: IngestedSentimentRecord,
        reason: SuppressionReason,
    ) -> SuppressedSentimentRecord:
        return SuppressedSentimentRecord(
            source_metadata=record.source_metadata,
            adapter_name=record.adapter_name,
            title=record.item.title,
            published_at=record.item.published_at,
            dedup_key=record.dedup_key,
            reason=reason,
            age_seconds=record.age_seconds,
            source_item_id=record.source_item_id,
        )

    def _normalize_text(self, value: str, *, field_name: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise SentimentSourceConfigurationError(
                f"Sentiment item {field_name} cannot be empty after normalization."
            )
        return normalized

    def _normalize_optional_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    def _coerce_timestamp(self, value: datetime | date | str) -> datetime:
        if isinstance(value, datetime):
            return self._normalize_datetime(value)
        if isinstance(value, date):
            return self._normalize_datetime(datetime.combine(value, time.min))
        if isinstance(value, str):
            candidate = value.strip()
            if candidate.endswith("Z"):
                candidate = f"{candidate[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(candidate)
            except ValueError as exc:
                raise SentimentSourceConfigurationError(
                    f"Unsupported published_at value: {value!r}"
                ) from exc
            return self._normalize_datetime(parsed)
        raise SentimentSourceConfigurationError(
            f"Unsupported published_at type: {type(value)!r}"
        )

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=self._default_timezone)
        return value.astimezone(self._default_timezone)

    def _coerce_sentiment_score(self, value: float | None) -> float | None:
        if value is None:
            return None
        score = float(value)
        return max(-1.0, min(1.0, score))

    def _merge_tags(self, *tag_groups: Iterable[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for tags in tag_groups:
            for raw_tag in tags:
                tag = raw_tag.strip()
                if not tag or tag in seen:
                    continue
                seen.add(tag)
                merged.append(tag)
        return merged

    def _build_raw_reference(
        self,
        *,
        source_id: str,
        source_item_id: str | None,
        fallback_key: str,
    ) -> str:
        return f"{source_id}:{source_item_id or fallback_key[:16]}"

    def _build_dedup_key(
        self,
        *,
        title: str,
        content: str,
        url: str | None,
    ) -> str:
        del url
        # Title/content fingerprint suppresses syndicated duplicates across sources and polls.
        return self._hash_text(f"{title.lower()}|{content.lower()}")

    def _hash_text(self, value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()

    def _is_stale(
        self,
        *,
        published_at: datetime,
        now: datetime,
        max_item_age: timedelta | None,
    ) -> bool:
        if max_item_age is None:
            return False
        age = now - published_at
        if age < timedelta(0):
            return False
        return age > max_item_age


def build_default_sentiment_service() -> SentimentIngestionService:
    return SentimentIngestionService()
