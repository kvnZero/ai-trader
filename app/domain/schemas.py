from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class SignalDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class RecommendationAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    WATCH = "watch"
    AVOID = "avoid"


@dataclass(frozen=True, slots=True)
class ModuleCapability:
    slug: str
    title: str
    description: str
    owner_module: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class MarketBar:
    symbol: str
    trade_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    turnover: float | None = None
    amplitude: float | None = None
    change_percent: float | None = None


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    symbol: str
    name: str
    last_price: float
    change_percent: float
    volume: float
    turnover: float | None
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class TechnicalSignal:
    name: str
    direction: SignalDirection
    score: float
    summary: str
    evidence: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SentimentItem:
    source: str
    title: str
    content: str
    published_at: datetime
    url: str | None = None
    sentiment_score: float | None = None
    tags: list[str] = field(default_factory=list)
    raw_reference: str | None = None


@dataclass(frozen=True, slots=True)
class CompanyReference:
    symbol: str
    company_name: str
    exchange: str = "SZSE/SSE"
    industry: str | None = None
    themes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CompanyMatch:
    company: CompanyReference
    confidence: float
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AgentRecommendation:
    action: RecommendationAction
    confidence: float
    thesis: str
    trigger_conditions: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FinalRecommendation:
    symbol: str
    action: RecommendationAction
    confidence: float
    summary: str
    technical_signals: list[TechnicalSignal] = field(default_factory=list)
    company_matches: list[CompanyMatch] = field(default_factory=list)
    sentiment_items: list[SentimentItem] = field(default_factory=list)
    agent_recommendation: AgentRecommendation | None = None
    risk_notes: list[str] = field(default_factory=list)
