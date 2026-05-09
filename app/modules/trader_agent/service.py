from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Protocol

from app.domain import (
    AgentRecommendation,
    CompanyMatch,
    RecommendationAction,
    SentimentItem,
    SignalDirection,
    TechnicalSignal,
)
from app.modules.trader_agent.contracts import (
    TraderAgentInput,
    TraderSentimentSummary,
    TraderTechnicalSummary,
)

_TECHNICAL_EVIDENCE_LIMIT = 3
_SENTIMENT_EVIDENCE_LIMIT = 3
_STALE_SENTIMENT_HOURS = 72
_LOW_MAPPING_CONFIDENCE = 0.45
_RISK_TAG_KEYWORDS = (
    "breakdown",
    "gap",
    "risk",
    "selloff",
    "volatility",
    "whipsaw",
)


class TraderAgentRecommender(Protocol):
    def recommend(self, agent_input: TraderAgentInput) -> AgentRecommendation:
        """Produce a machine-readable trader opinion from assembled inputs."""


class TraderAgentInputAssembler:
    """Builds a future-LLM-ready input packet from shared domain schemas."""

    def assemble(
        self,
        *,
        symbol: str,
        technical_signals: list[TechnicalSignal] | None = None,
        sentiment_items: list[SentimentItem] | None = None,
        company_matches: list[CompanyMatch] | None = None,
        evaluation_at: datetime | None = None,
    ) -> TraderAgentInput:
        resolved_technical_signals = list(technical_signals or [])
        resolved_sentiment_items = list(sentiment_items or [])
        resolved_company_matches = list(company_matches or [])
        generated_at = self._resolve_evaluation_at(
            evaluation_at=evaluation_at,
            sentiment_items=resolved_sentiment_items,
        )
        technical_summary = self._summarize_technical_signals(resolved_technical_signals)
        sentiment_summary = self._summarize_sentiment_items(
            sentiment_items=resolved_sentiment_items,
            company_matches=resolved_company_matches,
            evaluation_at=generated_at,
        )
        directional_bias = self._determine_directional_bias(
            technical_summary=technical_summary,
            sentiment_summary=sentiment_summary,
        )
        risk_flags = self._build_risk_flags(
            technical_summary=technical_summary,
            sentiment_summary=sentiment_summary,
            generated_at=generated_at,
        )

        prompt_context = {
            "symbol": symbol,
            "generated_at": generated_at.isoformat(),
            "directional_bias": directional_bias.value,
            "technical_summary": asdict(technical_summary),
            "sentiment_summary": asdict(sentiment_summary),
            "risk_flags": list(risk_flags),
            "mapped_companies": [
                {
                    "symbol": match.company.symbol,
                    "company_name": match.company.company_name,
                    "confidence": match.confidence,
                    "evidence": list(match.evidence),
                }
                for match in resolved_company_matches
            ],
        }
        return TraderAgentInput(
            symbol=symbol,
            generated_at=generated_at,
            directional_bias=directional_bias,
            technical_summary=technical_summary,
            sentiment_summary=sentiment_summary,
            technical_signals=resolved_technical_signals,
            sentiment_items=resolved_sentiment_items,
            company_matches=resolved_company_matches,
            risk_flags=risk_flags,
            prompt_context=prompt_context,
        )

    def _resolve_evaluation_at(
        self,
        *,
        evaluation_at: datetime | None,
        sentiment_items: list[SentimentItem],
    ) -> datetime:
        if evaluation_at is not None:
            return self._normalize_datetime(evaluation_at)

        timestamps = [
            self._normalize_datetime(item.published_at)
            for item in sentiment_items
        ]
        if timestamps:
            return max(timestamps)
        return datetime.now(timezone.utc)

    def _summarize_technical_signals(
        self,
        technical_signals: list[TechnicalSignal],
    ) -> TraderTechnicalSummary:
        bullish_signals = self._sorted_signals(
            signal
            for signal in technical_signals
            if signal.direction is SignalDirection.BULLISH
        )
        bearish_signals = self._sorted_signals(
            signal
            for signal in technical_signals
            if signal.direction is SignalDirection.BEARISH
        )
        neutral_signals = self._sorted_signals(
            signal
            for signal in technical_signals
            if signal.direction is SignalDirection.NEUTRAL
        )
        mixed_signals = self._sorted_signals(
            signal
            for signal in technical_signals
            if signal.direction is SignalDirection.MIXED
        )
        bullish_score = round(sum(self._bounded_score(signal.score) for signal in bullish_signals), 3)
        bearish_score = round(sum(self._bounded_score(signal.score) for signal in bearish_signals), 3)
        neutral_score = round(sum(self._bounded_score(signal.score) for signal in neutral_signals), 3)
        mixed_score = round(sum(self._bounded_score(signal.score) for signal in mixed_signals), 3)

        normalizer = max(1.0, bullish_score + bearish_score + neutral_score + mixed_score)
        net_score = round(
            self._clamp((bullish_score - bearish_score) / normalizer),
            3,
        )
        direction = self._resolve_direction_from_score(
            score=net_score,
            positive_total=bullish_score,
            negative_total=bearish_score,
            mixed_total=mixed_score,
        )
        caution_tags = self._unique_strings(
            tag
            for signal in technical_signals
            for tag in signal.tags
            if signal.direction in {SignalDirection.BEARISH, SignalDirection.MIXED}
            or any(keyword in tag.lower() for keyword in _RISK_TAG_KEYWORDS)
        )
        return TraderTechnicalSummary(
            direction=direction,
            bullish_score=bullish_score,
            bearish_score=bearish_score,
            neutral_score=neutral_score,
            mixed_score=mixed_score,
            net_score=net_score,
            strongest_bullish_signal=bullish_signals[0] if bullish_signals else None,
            strongest_bearish_signal=bearish_signals[0] if bearish_signals else None,
            bullish_evidence=[
                self._format_technical_signal(signal)
                for signal in bullish_signals[:_TECHNICAL_EVIDENCE_LIMIT]
            ],
            bearish_evidence=[
                self._format_technical_signal(signal)
                for signal in bearish_signals[:_TECHNICAL_EVIDENCE_LIMIT]
            ],
            caution_tags=caution_tags,
        )

    def _summarize_sentiment_items(
        self,
        *,
        sentiment_items: list[SentimentItem],
        company_matches: list[CompanyMatch],
        evaluation_at: datetime,
    ) -> TraderSentimentSummary:
        if not sentiment_items:
            return TraderSentimentSummary(
                direction=SignalDirection.NEUTRAL,
                average_score=None,
                weighted_score=0.0,
                positive_count=0,
                negative_count=0,
                neutral_count=0,
                coverage_confidence=0.0,
            )

        scored_items: list[tuple[SentimentItem, float, float]] = []
        positive_count = 0
        negative_count = 0
        neutral_count = 0
        raw_scores: list[float] = []

        for item in sentiment_items:
            score = self._coerce_sentiment_score(item.sentiment_score)
            weight = self._recency_weight(
                evaluation_at=evaluation_at,
                published_at=self._normalize_datetime(item.published_at),
            )
            scored_items.append((item, score, weight))
            raw_scores.append(score)
            if score >= 0.15:
                positive_count += 1
            elif score <= -0.15:
                negative_count += 1
            else:
                neutral_count += 1

        weight_total = sum(weight for _, _, weight in scored_items) or 1.0
        weighted_score = round(
            self._clamp(sum(score * weight for _, score, weight in scored_items) / weight_total),
            3,
        )
        average_score = round(sum(raw_scores) / len(raw_scores), 3)
        coverage_confidence = round(
            sum(match.confidence for match in company_matches) / len(company_matches),
            3,
        ) if company_matches else 0.0
        direction = self._resolve_direction_from_sentiment(
            weighted_score=weighted_score,
            positive_count=positive_count,
            negative_count=negative_count,
        )
        ranked_positive = sorted(
            (entry for entry in scored_items if entry[1] >= 0.15),
            key=lambda entry: (-(entry[1] * entry[2]), entry[0].published_at),
        )
        ranked_negative = sorted(
            (entry for entry in scored_items if entry[1] <= -0.15),
            key=lambda entry: (entry[1] * entry[2], entry[0].published_at),
        )
        timestamps = [self._normalize_datetime(item.published_at) for item in sentiment_items]
        attribution_warnings = self._build_attribution_warnings(
            sentiment_items=sentiment_items,
            company_matches=company_matches,
            coverage_confidence=coverage_confidence,
        )
        return TraderSentimentSummary(
            direction=direction,
            average_score=average_score,
            weighted_score=weighted_score,
            positive_count=positive_count,
            negative_count=negative_count,
            neutral_count=neutral_count,
            coverage_confidence=coverage_confidence,
            freshest_published_at=max(timestamps),
            oldest_published_at=min(timestamps),
            bullish_evidence=[
                self._format_sentiment_item(item, score)
                for item, score, _ in ranked_positive[:_SENTIMENT_EVIDENCE_LIMIT]
            ],
            bearish_evidence=[
                self._format_sentiment_item(item, score)
                for item, score, _ in ranked_negative[:_SENTIMENT_EVIDENCE_LIMIT]
            ],
            attribution_warnings=attribution_warnings,
        )

    def _determine_directional_bias(
        self,
        *,
        technical_summary: TraderTechnicalSummary,
        sentiment_summary: TraderSentimentSummary,
    ) -> SignalDirection:
        weighted_sentiment = (
            sentiment_summary.weighted_score
            * max(0.35, sentiment_summary.coverage_confidence)
        )
        combined_score = self._clamp(
            technical_summary.net_score * 0.7 + weighted_sentiment * 0.3,
        )

        if (
            technical_summary.direction in {SignalDirection.BULLISH, SignalDirection.BEARISH}
            and sentiment_summary.direction in {SignalDirection.BULLISH, SignalDirection.BEARISH}
            and technical_summary.direction is not sentiment_summary.direction
        ):
            if abs(combined_score) < 0.25:
                return SignalDirection.MIXED

        return self._resolve_direction_from_score(
            score=combined_score,
            positive_total=technical_summary.bullish_score + max(sentiment_summary.weighted_score, 0.0),
            negative_total=technical_summary.bearish_score + max(-sentiment_summary.weighted_score, 0.0),
            mixed_total=technical_summary.mixed_score,
        )

    def _build_risk_flags(
        self,
        *,
        technical_summary: TraderTechnicalSummary,
        sentiment_summary: TraderSentimentSummary,
        generated_at: datetime,
    ) -> list[str]:
        risk_flags: list[str] = []
        if not technical_summary.bullish_evidence and not technical_summary.bearish_evidence:
            risk_flags.append("technical coverage is unavailable")
        if (
            sentiment_summary.positive_count == 0
            and sentiment_summary.negative_count == 0
            and sentiment_summary.neutral_count == 0
        ):
            risk_flags.append("sentiment coverage is unavailable")

        if (
            technical_summary.direction in {SignalDirection.BULLISH, SignalDirection.BEARISH}
            and sentiment_summary.direction in {SignalDirection.BULLISH, SignalDirection.BEARISH}
            and technical_summary.direction is not sentiment_summary.direction
        ):
            risk_flags.append("technical and sentiment signals point in opposite directions")

        if sentiment_summary.freshest_published_at is not None:
            age_seconds = max(
                0.0,
                (
                    generated_at
                    - self._normalize_datetime(sentiment_summary.freshest_published_at)
                ).total_seconds(),
            )
            if age_seconds >= _STALE_SENTIMENT_HOURS * 3600:
                risk_flags.append("sentiment evidence is stale relative to the decision time")

        if sentiment_summary.attribution_warnings:
            risk_flags.extend(sentiment_summary.attribution_warnings)
        if technical_summary.caution_tags:
            risk_flags.append(
                "technical signals include elevated-risk tags: "
                + ", ".join(technical_summary.caution_tags[:4])
            )

        return self._unique_strings(risk_flags)

    def _build_attribution_warnings(
        self,
        *,
        sentiment_items: list[SentimentItem],
        company_matches: list[CompanyMatch],
        coverage_confidence: float,
    ) -> list[str]:
        warnings: list[str] = []
        if sentiment_items and not company_matches:
            warnings.append("sentiment items have no company-mapping support")
        elif company_matches and coverage_confidence < _LOW_MAPPING_CONFIDENCE:
            warnings.append("company-mapping confidence is weak for the supplied sentiment")
        return warnings

    def _resolve_direction_from_score(
        self,
        *,
        score: float,
        positive_total: float,
        negative_total: float,
        mixed_total: float,
    ) -> SignalDirection:
        if positive_total == 0 and negative_total == 0:
            return SignalDirection.MIXED if mixed_total > 0 else SignalDirection.NEUTRAL
        if abs(score) < 0.12:
            if positive_total > 0 and negative_total > 0:
                return SignalDirection.MIXED
            return SignalDirection.NEUTRAL
        if score > 0:
            return SignalDirection.BULLISH
        return SignalDirection.BEARISH

    def _resolve_direction_from_sentiment(
        self,
        *,
        weighted_score: float,
        positive_count: int,
        negative_count: int,
    ) -> SignalDirection:
        if positive_count == 0 and negative_count == 0:
            return SignalDirection.NEUTRAL
        if positive_count > 0 and negative_count > 0 and abs(weighted_score) < 0.18:
            return SignalDirection.MIXED
        if weighted_score >= 0.15:
            return SignalDirection.BULLISH
        if weighted_score <= -0.15:
            return SignalDirection.BEARISH
        return SignalDirection.NEUTRAL

    def _format_technical_signal(self, signal: TechnicalSignal) -> str:
        evidence = signal.evidence[0] if signal.evidence else signal.summary
        return f"{signal.name}: {signal.summary} ({evidence})"

    def _format_sentiment_item(self, item: SentimentItem, score: float) -> str:
        return f"{item.source}: '{item.title}' scored {score:+.2f}"

    def _recency_weight(self, *, evaluation_at: datetime, published_at: datetime) -> float:
        age_hours = max(0.0, (evaluation_at - published_at).total_seconds() / 3600)
        if age_hours <= 6:
            return 1.0
        if age_hours <= 24:
            return 0.9
        if age_hours <= 72:
            return 0.75
        if age_hours <= 168:
            return 0.55
        return 0.35

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _coerce_sentiment_score(self, value: float | None) -> float:
        if value is None:
            return 0.0
        return self._clamp(float(value))

    def _bounded_score(self, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def _clamp(self, value: float) -> float:
        return max(-1.0, min(1.0, value))

    def _sorted_signals(self, signals: list[TechnicalSignal] | tuple[TechnicalSignal, ...] | object) -> list[TechnicalSignal]:
        return sorted(
            list(signals),
            key=lambda signal: (-self._bounded_score(signal.score), signal.name),
        )

    def _unique_strings(self, values: object) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw_value in values:
            value = str(raw_value).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered


class DeterministicTraderAgentRecommender:
    """Baseline recommender for predictable tests before an LLM is introduced."""

    def recommend(self, agent_input: TraderAgentInput) -> AgentRecommendation:
        sentiment_component = (
            agent_input.sentiment_summary.weighted_score
            * max(0.35, agent_input.sentiment_summary.coverage_confidence)
        )
        combined_score = self._clamp(
            agent_input.technical_summary.net_score * 0.65
            + sentiment_component * 0.35
        )
        if (
            agent_input.technical_summary.direction in {SignalDirection.BULLISH, SignalDirection.BEARISH}
            and agent_input.sentiment_summary.direction in {SignalDirection.BULLISH, SignalDirection.BEARISH}
            and agent_input.technical_summary.direction is not agent_input.sentiment_summary.direction
        ):
            combined_score *= 0.82

        action = self._resolve_action(
            combined_score=combined_score,
            technical_summary=agent_input.technical_summary,
        )
        confidence = self._build_confidence(
            combined_score=combined_score,
            agent_input=agent_input,
        )
        thesis = self._build_thesis(
            symbol=agent_input.symbol,
            action=action,
            technical_direction=agent_input.technical_summary.direction,
            sentiment_direction=agent_input.sentiment_summary.direction,
        )
        trigger_conditions = self._select_conditions(
            preferred=agent_input.technical_summary.bullish_evidence,
            secondary=agent_input.sentiment_summary.bullish_evidence,
            action=action,
            positive=True,
        )
        invalidation_conditions = self._select_conditions(
            preferred=agent_input.technical_summary.bearish_evidence,
            secondary=agent_input.sentiment_summary.bearish_evidence,
            action=action,
            positive=False,
        )
        risks = self._unique_strings(
            list(agent_input.risk_flags)
            + agent_input.technical_summary.caution_tags
        )
        evidence = self._build_evidence(agent_input=agent_input, action=action)
        return AgentRecommendation(
            action=action,
            confidence=confidence,
            thesis=thesis,
            trigger_conditions=trigger_conditions,
            invalidation_conditions=invalidation_conditions,
            risks=risks,
            evidence=evidence,
        )

    def _resolve_action(
        self,
        *,
        combined_score: float,
        technical_summary: TraderTechnicalSummary,
    ) -> RecommendationAction:
        if combined_score >= 0.42 and technical_summary.bullish_score >= technical_summary.bearish_score:
            return RecommendationAction.BUY
        if combined_score <= -0.48 and technical_summary.bearish_score >= technical_summary.bullish_score:
            return RecommendationAction.SELL
        if combined_score <= -0.16:
            return RecommendationAction.AVOID
        return RecommendationAction.WATCH

    def _build_confidence(
        self,
        *,
        combined_score: float,
        agent_input: TraderAgentInput,
    ) -> float:
        technical_coverage = min(1.0, len(agent_input.technical_signals) / 4)
        sentiment_coverage = min(1.0, len(agent_input.sentiment_items) / 4)
        mapping_coverage = agent_input.sentiment_summary.coverage_confidence
        base_confidence = (
            abs(combined_score) * 0.62
            + technical_coverage * 0.18
            + sentiment_coverage * 0.12
            + mapping_coverage * 0.08
        )
        penalties = 0.0
        if "technical coverage is unavailable" in agent_input.risk_flags:
            penalties += 0.14
        if "sentiment coverage is unavailable" in agent_input.risk_flags:
            penalties += 0.08
        if "technical and sentiment signals point in opposite directions" in agent_input.risk_flags:
            penalties += 0.12
        confidence = max(0.05, min(0.95, base_confidence - penalties))
        return round(confidence, 3)

    def _build_thesis(
        self,
        *,
        symbol: str,
        action: RecommendationAction,
        technical_direction: SignalDirection,
        sentiment_direction: SignalDirection,
    ) -> str:
        if action is RecommendationAction.BUY:
            return (
                f"{symbol} has a favorable technical posture and enough supportive sentiment "
                "to justify a buy bias."
            )
        if action is RecommendationAction.SELL:
            return (
                f"{symbol} shows decisive downside pressure, and the combined evidence supports "
                "a sell stance."
            )
        if action is RecommendationAction.AVOID:
            return (
                f"{symbol} does not have enough aligned bullish evidence; the current mix of "
                f"{technical_direction.value} technicals and {sentiment_direction.value} sentiment "
                "supports staying out."
            )
        return (
            f"{symbol} has incomplete or mixed conviction. Monitor confirmation before acting "
            "because the structured evidence is not yet decisive."
        )

    def _select_conditions(
        self,
        *,
        preferred: list[str],
        secondary: list[str],
        action: RecommendationAction,
        positive: bool,
    ) -> list[str]:
        selected = list(preferred[:2]) + list(secondary[:1])
        if not selected:
            if positive:
                return ["await stronger technical or sentiment confirmation"]
            return ["reassess if contrary evidence improves materially"]

        if action in {RecommendationAction.SELL, RecommendationAction.AVOID} and positive:
            return ["bullish recovery signals should appear before reconsidering"] + selected[:2]
        if action is RecommendationAction.BUY and not positive:
            return selected[:3]
        return self._unique_strings(selected[:3])

    def _build_evidence(
        self,
        *,
        agent_input: TraderAgentInput,
        action: RecommendationAction,
    ) -> list[str]:
        if action in {RecommendationAction.BUY, RecommendationAction.WATCH}:
            primary = agent_input.technical_summary.bullish_evidence
            secondary = agent_input.sentiment_summary.bullish_evidence
            opposing = agent_input.technical_summary.bearish_evidence
        else:
            primary = agent_input.technical_summary.bearish_evidence
            secondary = agent_input.sentiment_summary.bearish_evidence
            opposing = agent_input.technical_summary.bullish_evidence

        evidence = list(primary[:2]) + list(secondary[:2])
        if opposing:
            evidence.append(f"counterpoint: {opposing[0]}")
        return self._unique_strings(evidence[:5])

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


class TraderAgentService:
    """Facade for deterministic assembly now and model-based reasoning later."""

    def __init__(
        self,
        *,
        input_assembler: TraderAgentInputAssembler | None = None,
        recommender: TraderAgentRecommender | None = None,
    ):
        self.input_assembler = input_assembler or TraderAgentInputAssembler()
        self.recommender = recommender or DeterministicTraderAgentRecommender()

    def assemble_input(
        self,
        *,
        symbol: str,
        technical_signals: list[TechnicalSignal] | None = None,
        sentiment_items: list[SentimentItem] | None = None,
        company_matches: list[CompanyMatch] | None = None,
        evaluation_at: datetime | None = None,
    ) -> TraderAgentInput:
        return self.input_assembler.assemble(
            symbol=symbol,
            technical_signals=technical_signals,
            sentiment_items=sentiment_items,
            company_matches=company_matches,
            evaluation_at=evaluation_at,
        )

    def generate_recommendation(
        self,
        *,
        symbol: str,
        technical_signals: list[TechnicalSignal] | None = None,
        sentiment_items: list[SentimentItem] | None = None,
        company_matches: list[CompanyMatch] | None = None,
        evaluation_at: datetime | None = None,
    ) -> AgentRecommendation:
        agent_input = self.assemble_input(
            symbol=symbol,
            technical_signals=technical_signals,
            sentiment_items=sentiment_items,
            company_matches=company_matches,
            evaluation_at=evaluation_at,
        )
        return self.generate_recommendation_from_input(agent_input)

    def generate_recommendation_from_input(
        self,
        agent_input: TraderAgentInput,
    ) -> AgentRecommendation:
        return self.recommender.recommend(agent_input)


def build_default_trader_agent_service() -> TraderAgentService:
    return TraderAgentService()
