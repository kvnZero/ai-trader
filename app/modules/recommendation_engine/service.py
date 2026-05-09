from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain import (
    AgentRecommendation,
    CompanyMatch,
    FinalRecommendation,
    RecommendationAction,
    SentimentItem,
    SignalDirection,
    TechnicalSignal,
)
from app.modules.recommendation_engine.contracts import (
    RecommendationComponentScore,
    RecommendationDecisionTrace,
)
from app.modules.trader_agent import TraderAgentInput, TraderAgentService

_DECISION_TECHNICAL_WEIGHT = 0.45
_DECISION_SENTIMENT_WEIGHT = 0.20
_DECISION_AGENT_WEIGHT = 0.35
_CONFLICT_PENALTY = 0.08
_STALE_SENTIMENT_HOURS = 72
_LOW_MAPPING_CONFIDENCE = 0.45


@dataclass(frozen=True, slots=True)
class RecommendationBundle:
    recommendation: FinalRecommendation
    decision_trace: RecommendationDecisionTrace
    trader_agent_input: TraderAgentInput


class RecommendationEngineService:
    """Fuse deterministic evidence and optional trader-agent output."""

    def __init__(self, trader_agent_service: TraderAgentService | None = None):
        self.trader_agent_service = trader_agent_service or TraderAgentService()

    def build_recommendation(
        self,
        *,
        symbol: str,
        technical_signals: list[TechnicalSignal] | None = None,
        sentiment_items: list[SentimentItem] | None = None,
        company_matches: list[CompanyMatch] | None = None,
        agent_recommendation: AgentRecommendation | None = None,
        trader_agent_input: TraderAgentInput | None = None,
        evaluation_at: datetime | None = None,
    ) -> FinalRecommendation:
        return self.build_recommendation_bundle(
            symbol=symbol,
            technical_signals=technical_signals,
            sentiment_items=sentiment_items,
            company_matches=company_matches,
            agent_recommendation=agent_recommendation,
            trader_agent_input=trader_agent_input,
            evaluation_at=evaluation_at,
        ).recommendation

    def build_recommendation_bundle(
        self,
        *,
        symbol: str,
        technical_signals: list[TechnicalSignal] | None = None,
        sentiment_items: list[SentimentItem] | None = None,
        company_matches: list[CompanyMatch] | None = None,
        agent_recommendation: AgentRecommendation | None = None,
        trader_agent_input: TraderAgentInput | None = None,
        evaluation_at: datetime | None = None,
    ) -> RecommendationBundle:
        resolved_technical_signals = list(technical_signals or [])
        resolved_sentiment_items = list(sentiment_items or [])
        resolved_company_matches = list(company_matches or [])

        assembled_input = trader_agent_input or self.trader_agent_service.assemble_input(
            symbol=symbol,
            technical_signals=resolved_technical_signals,
            sentiment_items=resolved_sentiment_items,
            company_matches=resolved_company_matches,
            evaluation_at=evaluation_at,
        )
        resolved_agent_recommendation = (
            agent_recommendation
            or self.trader_agent_service.generate_recommendation_from_input(assembled_input)
        )
        decision_trace = self._build_decision_trace(
            symbol=symbol,
            trader_agent_input=assembled_input,
            agent_recommendation=resolved_agent_recommendation,
            technical_signals=resolved_technical_signals,
            sentiment_items=resolved_sentiment_items,
            company_matches=resolved_company_matches,
            evaluation_at=evaluation_at,
        )
        recommendation = self._build_final_recommendation(
            symbol=symbol,
            technical_signals=resolved_technical_signals,
            sentiment_items=resolved_sentiment_items,
            company_matches=resolved_company_matches,
            agent_recommendation=resolved_agent_recommendation,
            decision_trace=decision_trace,
        )
        return RecommendationBundle(
            recommendation=recommendation,
            decision_trace=decision_trace,
            trader_agent_input=assembled_input,
        )

    def _build_decision_trace(
        self,
        *,
        symbol: str,
        trader_agent_input: TraderAgentInput,
        agent_recommendation: AgentRecommendation,
        technical_signals: list[TechnicalSignal],
        sentiment_items: list[SentimentItem],
        company_matches: list[CompanyMatch],
        evaluation_at: datetime | None,
    ) -> RecommendationDecisionTrace:
        generated_at = self._resolve_generated_at(
            trader_agent_input=trader_agent_input,
            evaluation_at=evaluation_at,
        )
        technical_component = self._build_technical_component(
            trader_agent_input=trader_agent_input,
            technical_signals=technical_signals,
        )
        sentiment_component = self._build_sentiment_component(
            trader_agent_input=trader_agent_input,
            sentiment_items=sentiment_items,
            company_matches=company_matches,
            generated_at=generated_at,
        )
        agent_component = self._build_agent_component(
            agent_recommendation=agent_recommendation,
        )
        conflicts = self._build_conflicts(
            technical_component=technical_component,
            sentiment_component=sentiment_component,
            agent_component=agent_component,
        )
        risk_flags = self._build_risk_flags(
            trader_agent_input=trader_agent_input,
            technical_signals=technical_signals,
            sentiment_items=sentiment_items,
            company_matches=company_matches,
            conflicts=conflicts,
            generated_at=generated_at,
        )
        final_score = self._build_final_score(
            technical_component=technical_component,
            sentiment_component=sentiment_component,
            agent_component=agent_component,
            conflicts=conflicts,
            risk_flags=risk_flags,
        )
        final_action = self._resolve_final_action(
            final_score=final_score,
            technical_component=technical_component,
            agent_component=agent_component,
            risk_flags=risk_flags,
        )
        final_confidence = self._build_final_confidence(
            final_score=final_score,
            technical_component=technical_component,
            sentiment_component=sentiment_component,
            agent_component=agent_component,
            conflicts=conflicts,
            risk_flags=risk_flags,
        )
        evidence_summary = self._build_evidence_summary(
            technical_component=technical_component,
            sentiment_component=sentiment_component,
            agent_component=agent_component,
            conflicts=conflicts,
        )
        return RecommendationDecisionTrace(
            symbol=symbol,
            generated_at=generated_at,
            final_action=final_action,
            final_confidence=final_confidence,
            final_score=final_score,
            technical_component=technical_component,
            sentiment_component=sentiment_component,
            agent_component=agent_component,
            conflicts=conflicts,
            risk_flags=risk_flags,
            evidence_summary=evidence_summary,
        )

    def _build_final_recommendation(
        self,
        *,
        symbol: str,
        technical_signals: list[TechnicalSignal],
        sentiment_items: list[SentimentItem],
        company_matches: list[CompanyMatch],
        agent_recommendation: AgentRecommendation,
        decision_trace: RecommendationDecisionTrace,
    ) -> FinalRecommendation:
        summary = self._build_summary(
            symbol=symbol,
            decision_trace=decision_trace,
            agent_recommendation=agent_recommendation,
        )
        risk_notes = self._unique_strings(
            decision_trace.risk_flags + list(agent_recommendation.risks)
        )
        return FinalRecommendation(
            symbol=symbol,
            action=decision_trace.final_action,
            confidence=decision_trace.final_confidence,
            summary=summary,
            technical_signals=technical_signals,
            company_matches=company_matches,
            sentiment_items=sentiment_items,
            agent_recommendation=agent_recommendation,
            risk_notes=risk_notes,
        )

    def _build_technical_component(
        self,
        *,
        trader_agent_input: TraderAgentInput,
        technical_signals: list[TechnicalSignal],
    ) -> RecommendationComponentScore:
        summary = trader_agent_input.technical_summary
        coverage = min(1.0, len(technical_signals) / 5) if technical_signals else 0.0
        confidence = round(
            min(1.0, max(abs(summary.net_score), 0.18) * 0.72 + coverage * 0.28),
            3,
        )
        evidence = (
            summary.bullish_evidence[:2]
            if summary.net_score >= 0
            else summary.bearish_evidence[:2]
        )
        if not evidence:
            evidence = summary.bullish_evidence[:1] + summary.bearish_evidence[:1]
        return RecommendationComponentScore(
            source="technical_signals",
            direction=summary.direction,
            score=summary.net_score,
            confidence=confidence,
            evidence=evidence,
        )

    def _build_sentiment_component(
        self,
        *,
        trader_agent_input: TraderAgentInput,
        sentiment_items: list[SentimentItem],
        company_matches: list[CompanyMatch],
        generated_at: datetime,
    ) -> RecommendationComponentScore:
        summary = trader_agent_input.sentiment_summary
        score = summary.weighted_score * max(0.35, summary.coverage_confidence)
        coverage = min(1.0, len(sentiment_items) / 4) if sentiment_items else 0.0
        mapping_confidence = (
            sum(match.confidence for match in company_matches) / len(company_matches)
            if company_matches
            else 0.0
        )
        freshness_factor = self._freshness_factor(
            freshest_published_at=summary.freshest_published_at,
            generated_at=generated_at,
        )
        confidence = round(
            min(
                1.0,
                coverage * 0.32 + mapping_confidence * 0.38 + freshness_factor * 0.30,
            ),
            3,
        )
        evidence = (
            summary.bullish_evidence[:2]
            if score >= 0
            else summary.bearish_evidence[:2]
        )
        if not evidence:
            evidence = summary.bullish_evidence[:1] + summary.bearish_evidence[:1]
        return RecommendationComponentScore(
            source="sentiment_items",
            direction=summary.direction,
            score=round(self._clamp(score), 3),
            confidence=confidence,
            evidence=evidence,
        )

    def _build_agent_component(
        self,
        *,
        agent_recommendation: AgentRecommendation,
    ) -> RecommendationComponentScore:
        direction = self._action_to_direction(agent_recommendation.action)
        signed_score = self._action_score(agent_recommendation.action, agent_recommendation.confidence)
        evidence = list(agent_recommendation.evidence[:3])
        if agent_recommendation.thesis and not evidence:
            evidence = [agent_recommendation.thesis]
        return RecommendationComponentScore(
            source="trader_agent",
            direction=direction,
            score=signed_score,
            confidence=round(max(0.0, min(1.0, agent_recommendation.confidence)), 3),
            evidence=evidence,
        )

    def _build_conflicts(
        self,
        *,
        technical_component: RecommendationComponentScore,
        sentiment_component: RecommendationComponentScore,
        agent_component: RecommendationComponentScore | None,
    ) -> list[str]:
        conflicts: list[str] = []
        if self._directions_conflict(technical_component.direction, sentiment_component.direction):
            conflicts.append("technical and sentiment components disagree on direction")
        if agent_component is not None:
            if self._directions_conflict(agent_component.direction, technical_component.direction):
                conflicts.append("agent view diverges from the technical component")
            if self._directions_conflict(agent_component.direction, sentiment_component.direction):
                conflicts.append("agent view diverges from the sentiment component")
        return conflicts

    def _build_risk_flags(
        self,
        *,
        trader_agent_input: TraderAgentInput,
        technical_signals: list[TechnicalSignal],
        sentiment_items: list[SentimentItem],
        company_matches: list[CompanyMatch],
        conflicts: list[str],
        generated_at: datetime,
    ) -> list[str]:
        risk_flags = list(trader_agent_input.risk_flags)
        if not technical_signals:
            risk_flags.append("final recommendation is operating without technical signals")
        if not sentiment_items:
            risk_flags.append("final recommendation is operating without sentiment inputs")
        if sentiment_items and not company_matches:
            risk_flags.append("sentiment evidence lacks supporting company mappings")
        elif company_matches:
            mapping_confidence = sum(match.confidence for match in company_matches) / len(company_matches)
            if mapping_confidence < _LOW_MAPPING_CONFIDENCE:
                risk_flags.append("company mappings are low-confidence for sentiment attribution")
        freshest_sentiment = trader_agent_input.sentiment_summary.freshest_published_at
        if freshest_sentiment is not None:
            age_hours = (
                generated_at - self._normalize_datetime(freshest_sentiment)
            ).total_seconds() / 3600
            if age_hours >= _STALE_SENTIMENT_HOURS:
                risk_flags.append("sentiment inputs may be stale for current market conditions")
        risk_flags.extend(conflicts)
        return self._unique_strings(risk_flags)

    def _build_final_score(
        self,
        *,
        technical_component: RecommendationComponentScore,
        sentiment_component: RecommendationComponentScore,
        agent_component: RecommendationComponentScore | None,
        conflicts: list[str],
        risk_flags: list[str],
    ) -> float:
        score = (
            technical_component.score * _DECISION_TECHNICAL_WEIGHT
            + sentiment_component.score * _DECISION_SENTIMENT_WEIGHT
        )
        if agent_component is not None:
            score += agent_component.score * _DECISION_AGENT_WEIGHT
        score -= len(conflicts) * _CONFLICT_PENALTY
        if "final recommendation is operating without technical signals" in risk_flags:
            score *= 0.75
        if "final recommendation is operating without sentiment inputs" in risk_flags:
            score *= 0.90
        return round(self._clamp(score), 3)

    def _resolve_final_action(
        self,
        *,
        final_score: float,
        technical_component: RecommendationComponentScore,
        agent_component: RecommendationComponentScore | None,
        risk_flags: list[str],
    ) -> RecommendationAction:
        if final_score >= 0.42:
            return RecommendationAction.BUY
        if final_score <= -0.52:
            return RecommendationAction.SELL
        if final_score <= -0.18:
            return RecommendationAction.AVOID
        if (
            agent_component is not None
            and agent_component.direction is SignalDirection.BEARISH
            and technical_component.direction is SignalDirection.BEARISH
            and "technical and sentiment components disagree on direction" not in risk_flags
        ):
            return RecommendationAction.AVOID
        return RecommendationAction.WATCH

    def _build_final_confidence(
        self,
        *,
        final_score: float,
        technical_component: RecommendationComponentScore,
        sentiment_component: RecommendationComponentScore,
        agent_component: RecommendationComponentScore | None,
        conflicts: list[str],
        risk_flags: list[str],
    ) -> float:
        base = (
            abs(final_score) * 0.58
            + technical_component.confidence * 0.20
            + sentiment_component.confidence * 0.10
            + (agent_component.confidence * 0.12 if agent_component is not None else 0.0)
        )
        base -= min(0.24, len(conflicts) * 0.07)
        if "sentiment inputs may be stale for current market conditions" in risk_flags:
            base -= 0.06
        if "company mappings are low-confidence for sentiment attribution" in risk_flags:
            base -= 0.05
        if "final recommendation is operating without technical signals" in risk_flags:
            base -= 0.12
        confidence = max(0.05, min(0.95, base))
        return round(confidence, 3)

    def _build_evidence_summary(
        self,
        *,
        technical_component: RecommendationComponentScore,
        sentiment_component: RecommendationComponentScore,
        agent_component: RecommendationComponentScore | None,
        conflicts: list[str],
    ) -> list[str]:
        evidence = list(technical_component.evidence[:2]) + list(sentiment_component.evidence[:2])
        if agent_component is not None:
            evidence.extend(agent_component.evidence[:2])
        if conflicts:
            evidence.append(f"conflict note: {conflicts[0]}")
        return self._unique_strings(evidence[:6])

    def _build_summary(
        self,
        *,
        symbol: str,
        decision_trace: RecommendationDecisionTrace,
        agent_recommendation: AgentRecommendation,
    ) -> str:
        action = decision_trace.final_action.value
        agent_score = (
            decision_trace.agent_component.score
            if decision_trace.agent_component is not None
            else 0.0
        )
        summary = (
            f"{symbol} is rated {action} with {decision_trace.final_confidence:.0%} confidence. "
            f"Technical score {decision_trace.technical_component.score:+.2f}, "
            f"sentiment score {decision_trace.sentiment_component.score:+.2f}, "
            f"agent score {agent_score:+.2f}."
        )
        if decision_trace.conflicts:
            summary += " Conflicting evidence remains in the payload."
        elif agent_recommendation.thesis:
            summary += f" {agent_recommendation.thesis}"
        return summary

    def _resolve_generated_at(
        self,
        *,
        trader_agent_input: TraderAgentInput,
        evaluation_at: datetime | None,
    ) -> datetime:
        if evaluation_at is not None:
            return self._normalize_datetime(evaluation_at)
        return self._normalize_datetime(trader_agent_input.generated_at)

    def _freshness_factor(
        self,
        *,
        freshest_published_at: datetime | None,
        generated_at: datetime,
    ) -> float:
        if freshest_published_at is None:
            return 0.0
        age_hours = (
            generated_at - self._normalize_datetime(freshest_published_at)
        ).total_seconds() / 3600
        if age_hours <= 6:
            return 1.0
        if age_hours <= 24:
            return 0.85
        if age_hours <= 72:
            return 0.65
        if age_hours <= 168:
            return 0.45
        return 0.25

    def _action_to_direction(self, action: RecommendationAction) -> SignalDirection:
        if action is RecommendationAction.BUY:
            return SignalDirection.BULLISH
        if action in {RecommendationAction.SELL, RecommendationAction.AVOID}:
            return SignalDirection.BEARISH
        return SignalDirection.NEUTRAL

    def _action_score(self, action: RecommendationAction, confidence: float) -> float:
        magnitude = max(0.0, min(1.0, confidence))
        if action is RecommendationAction.BUY:
            return round(magnitude, 3)
        if action is RecommendationAction.SELL:
            return round(-magnitude, 3)
        if action is RecommendationAction.AVOID:
            return round(-magnitude * 0.72, 3)
        return round(magnitude * 0.15, 3)

    def _directions_conflict(
        self,
        left: SignalDirection,
        right: SignalDirection,
    ) -> bool:
        pair = {left, right}
        return pair == {SignalDirection.BULLISH, SignalDirection.BEARISH}

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _clamp(self, value: float) -> float:
        return max(-1.0, min(1.0, value))

    def _unique_strings(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered


def build_default_recommendation_engine_service() -> RecommendationEngineService:
    return RecommendationEngineService()
