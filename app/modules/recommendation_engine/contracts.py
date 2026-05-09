from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain import RecommendationAction, SignalDirection


@dataclass(frozen=True, slots=True)
class RecommendationComponentScore:
    source: str
    direction: SignalDirection
    score: float
    confidence: float
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RecommendationDecisionTrace:
    symbol: str
    generated_at: datetime
    final_action: RecommendationAction
    final_confidence: float
    final_score: float
    technical_component: RecommendationComponentScore
    sentiment_component: RecommendationComponentScore
    agent_component: RecommendationComponentScore | None = None
    conflicts: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    evidence_summary: list[str] = field(default_factory=list)
