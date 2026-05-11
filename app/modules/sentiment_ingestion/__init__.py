"""Independent sentiment ingestion capability package."""

from app.modules.sentiment_ingestion.adapters import (
    AKShareLiveNewsSourceAdapter,
    AkshareStockNewsAdapter,
    RssFeedSentimentSourceAdapter,
    SampleSentimentSourceAdapter,
    SentimentSourceAdapter,
    SentimentSourceRegistry,
    StaticSentimentSourceAdapter,
    build_default_registry,
)
from app.modules.sentiment_ingestion.contracts import (
    IngestedSentimentRecord,
    RawSentimentPayload,
    SentimentIngestionError,
    SentimentIngestionResult,
    SentimentSourceCategory,
    SentimentSourceConfigurationError,
    SentimentSourceDefinition,
    SentimentSourceMetadata,
    SentimentSourceNotRegisteredError,
    SentimentSourceFailure,
    SentimentSourceRun,
    SuppressedSentimentRecord,
    SuppressionReason,
)
from app.modules.sentiment_ingestion.presets import (
    build_default_sample_sources,
    build_static_source_definition,
)
from app.modules.sentiment_ingestion.service import (
    SentimentIngestionService,
    build_default_sentiment_service,
)

__all__ = [
    "IngestedSentimentRecord",
    "AKShareLiveNewsSourceAdapter",
    "AkshareStockNewsAdapter",
    "RawSentimentPayload",
    "RssFeedSentimentSourceAdapter",
    "SampleSentimentSourceAdapter",
    "SentimentIngestionError",
    "SentimentIngestionResult",
    "SentimentIngestionService",
    "SentimentSourceAdapter",
    "SentimentSourceCategory",
    "SentimentSourceConfigurationError",
    "SentimentSourceDefinition",
    "SentimentSourceFailure",
    "SentimentSourceMetadata",
    "SentimentSourceNotRegisteredError",
    "SentimentSourceRegistry",
    "SentimentSourceRun",
    "StaticSentimentSourceAdapter",
    "SuppressedSentimentRecord",
    "SuppressionReason",
    "build_default_registry",
    "build_default_sample_sources",
    "build_default_sentiment_service",
    "build_static_source_definition",
]
