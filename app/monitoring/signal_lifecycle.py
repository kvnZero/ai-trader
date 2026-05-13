from __future__ import annotations

from dataclasses import dataclass

from app.persistence.recommendation_snapshots import RecommendationSnapshotRow


_NO_TRADE_ACTIONS = {"watch", "avoid"}
_TRADE_ACTIONS = {"buy", "sell"}


@dataclass(frozen=True, slots=True)
class LifecycleAssessment:
    state: str
    reason: str


def assess_signal_lifecycle(
    *,
    previous_snapshot: RecommendationSnapshotRow | None,
    previous_recommendation: str | None,
    current_recommendation: str,
    confidence: float,
    confirmation_score: float | None,
    source: str,
    reason: str,
) -> LifecycleAssessment:
    normalized_previous = (previous_recommendation or "").strip().lower() or None
    normalized_current = current_recommendation.strip().lower()
    confirmation = confirmation_score or 0.0

    if normalized_current in _NO_TRADE_ACTIONS:
        return _assess_no_trade_lifecycle(
            previous_snapshot=previous_snapshot,
            previous_recommendation=normalized_previous,
            current_recommendation=normalized_current,
            confidence=confidence,
            confirmation_score=confirmation,
            source=source,
            reason=reason,
        )

    if normalized_previous is None:
        return LifecycleAssessment(
            state="created",
            reason=f"首次形成{normalized_current}信号，来源 {source}，置信度 {confidence:.0%}。",
        )

    if normalized_previous in _NO_TRADE_ACTIONS:
        return LifecycleAssessment(
            state="created",
            reason=(
                f"建议由 {normalized_previous} 切换为 {normalized_current}，"
                f"从无交易/观望进入可执行信号。"
            ),
        )

    if normalized_previous != normalized_current:
        return LifecycleAssessment(
            state="invalidated",
            reason=f"原 {normalized_previous} 信号被新的 {normalized_current} 信号替代。",
        )

    if confidence >= 0.72 and confirmation >= 0.58:
        return LifecycleAssessment(
            state="confirmed",
            reason=f"{normalized_current} 信号连续成立，确认度 {confirmation:.2f}，置信度 {confidence:.0%}。",
        )

    if confidence >= 0.48:
        return LifecycleAssessment(
            state="active",
            reason=f"{normalized_current} 信号仍然有效，当前维持活跃状态。",
        )

    return LifecycleAssessment(
        state="weakened",
        reason=f"{normalized_current} 信号方向未变，但置信度回落至 {confidence:.0%}。",
    )


def _assess_no_trade_lifecycle(
    *,
    previous_snapshot: RecommendationSnapshotRow | None,
    previous_recommendation: str | None,
    current_recommendation: str,
    confidence: float,
    confirmation_score: float,
    source: str,
    reason: str,
) -> LifecycleAssessment:
    if previous_recommendation in _TRADE_ACTIONS:
        if current_recommendation == "avoid":
            return LifecycleAssessment(
                state="invalidated",
                reason=f"原交易信号被回避建议否定，来源 {source}。",
            )
        return LifecycleAssessment(
            state="expired",
            reason=f"原交易信号已退化为观察状态，来源 {source}。",
        )

    if previous_recommendation is None and current_recommendation == "avoid":
        return LifecycleAssessment(
            state="invalidated",
            reason=f"首次评估即判定为 avoid，说明当前不形成有效交易信号。置信度 {confidence:.0%}。",
        )

    previous_confidence = previous_snapshot.confidence if previous_snapshot is not None else None
    if current_recommendation == "avoid":
        return LifecycleAssessment(
            state="invalidated",
            reason=f"当前输出为 avoid，信号无效。{_trim_reason(reason)}",
        )

    if previous_confidence is not None and confidence > previous_confidence and confirmation_score >= 0.35:
        return LifecycleAssessment(
            state="active",
            reason="仍为观察状态，但信号质量较上次改善，保持活跃跟踪。",
        )

    if confidence < 0.2 or "不执行交易" in reason or "信号质量不足" in reason:
        return LifecycleAssessment(
            state="expired",
            reason=f"观察信号缺乏足够质量，暂按过期处理。{_trim_reason(reason)}",
        )

    return LifecycleAssessment(
        state="weakened",
        reason=f"当前维持 {current_recommendation}，暂不形成更强交易信号。",
    )


def _trim_reason(reason: str, limit: int = 72) -> str:
    compact = " ".join(reason.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"
