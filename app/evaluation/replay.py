from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.persistence import RecommendationSnapshotRow


_ACTIONS = ("buy", "sell", "watch", "avoid")


@dataclass(frozen=True, slots=True)
class ReplaySnapshotView:
    symbol: str
    action: str
    regime: str | None
    regime_label: str | None
    confidence: float
    sentiment_count: int
    company_match_count: int
    created_at: str
    source: str


@dataclass(frozen=True, slots=True)
class ReplaySummaryReport:
    generated_at: str
    snapshot_count: int
    average_confidence: float
    action_counts: dict[str, int]
    regime_counts: dict[str, int]
    symbol_coverage_count: int
    latest_snapshot_at: str | None
    snapshots: list[ReplaySnapshotView] = field(default_factory=list)


def build_replay_summary_report(
    *,
    snapshots: list[RecommendationSnapshotRow],
    generated_at: datetime | None = None,
) -> ReplaySummaryReport:
    action_counts = {action: 0 for action in _ACTIONS}
    regime_counts: dict[str, int] = {}
    symbol_set: set[str] = set()
    confidence_total = 0.0

    snapshot_views: list[ReplaySnapshotView] = []
    for snapshot in snapshots:
        action = snapshot.recommendation if snapshot.recommendation in action_counts else "watch"
        action_counts[action] += 1
        regime_key = snapshot.market_regime or "unknown"
        regime_counts[regime_key] = regime_counts.get(regime_key, 0) + 1
        symbol_set.add(snapshot.symbol)
        confidence_total += snapshot.confidence
        snapshot_views.append(
            ReplaySnapshotView(
                symbol=snapshot.symbol,
                action=snapshot.recommendation,
                regime=snapshot.market_regime,
                regime_label=snapshot.market_regime_label,
                confidence=snapshot.confidence,
                sentiment_count=snapshot.sentiment_count,
                company_match_count=snapshot.company_match_count,
                created_at=snapshot.created_at,
                source=snapshot.source,
            )
        )

    timestamp = (generated_at or datetime.utcnow()).isoformat(timespec="minutes")
    latest_snapshot_at = snapshot_views[0].created_at if snapshot_views else None
    average_confidence = round(confidence_total / len(snapshot_views), 3) if snapshot_views else 0.0

    return ReplaySummaryReport(
        generated_at=timestamp,
        snapshot_count=len(snapshot_views),
        average_confidence=average_confidence,
        action_counts=action_counts,
        regime_counts=dict(sorted(regime_counts.items(), key=lambda item: (-item[1], item[0]))),
        symbol_coverage_count=len(symbol_set),
        latest_snapshot_at=latest_snapshot_at,
        snapshots=snapshot_views[:8],
    )
