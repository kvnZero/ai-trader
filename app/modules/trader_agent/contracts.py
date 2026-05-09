from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain import CompanyMatch, SentimentItem, SignalDirection, TechnicalSignal


@dataclass(frozen=True, slots=True)
class TraderTechnicalSummary:
    direction: SignalDirection
    bullish_score: float
    bearish_score: float
    neutral_score: float
    mixed_score: float
    net_score: float
    strongest_bullish_signal: TechnicalSignal | None = None
    strongest_bearish_signal: TechnicalSignal | None = None
    bullish_evidence: list[str] = field(default_factory=list)
    bearish_evidence: list[str] = field(default_factory=list)
    caution_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TraderSentimentSummary:
    direction: SignalDirection
    average_score: float | None
    weighted_score: float
    positive_count: int
    negative_count: int
    neutral_count: int
    coverage_confidence: float
    freshest_published_at: datetime | None = None
    oldest_published_at: datetime | None = None
    bullish_evidence: list[str] = field(default_factory=list)
    bearish_evidence: list[str] = field(default_factory=list)
    attribution_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TraderAgentInput:
    symbol: str
    generated_at: datetime
    directional_bias: SignalDirection
    technical_summary: TraderTechnicalSummary
    sentiment_summary: TraderSentimentSummary
    technical_signals: list[TechnicalSignal] = field(default_factory=list)
    sentiment_items: list[SentimentItem] = field(default_factory=list)
    company_matches: list[CompanyMatch] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    prompt_context: dict[str, object] = field(default_factory=dict)
