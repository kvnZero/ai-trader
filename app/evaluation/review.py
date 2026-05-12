from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.persistence import AlertRow, RecommendationEventRow, SentimentSourceFailureRow, SentimentWorkerStateRow, WatchlistRow


_ACTIONS = ("buy", "sell", "watch", "avoid")


@dataclass(frozen=True, slots=True)
class ReviewEvent:
    symbol: str
    previous_action: str | None
    current_action: str
    confidence: float
    summary: str
    created_at: str


@dataclass(frozen=True, slots=True)
class RecommendationReviewReport:
    generated_at: str
    watchlist_count: int
    action_counts: dict[str, int]
    conservative_count: int
    conservative_ratio: float
    recent_event_count: int
    stale_run_count: int
    unread_high_alert_count: int
    sentiment_worker_status: str
    sentiment_latest_update: str | None
    sentiment_failure_count: int
    sentiment_failure_summary: list[str] = field(default_factory=list)
    latest_event: ReviewEvent | None = None
    recent_events: list[ReviewEvent] = field(default_factory=list)


def build_recommendation_review_report(
    *,
    watchlist_rows: list[WatchlistRow],
    recommendation_events: list[RecommendationEventRow],
    recent_runs: list[dict[str, object]],
    unread_alerts: list[AlertRow],
    sentiment_worker_state: SentimentWorkerStateRow | None,
    latest_source_failures: list[SentimentSourceFailureRow],
    generated_at: datetime | None = None,
) -> RecommendationReviewReport:
    action_counts = {action: 0 for action in _ACTIONS}
    conservative_count = 0
    for row in watchlist_rows:
        action = row.latest_recommendation if row.latest_recommendation in action_counts else "watch"
        action_counts[action] += 1
        if action in {"watch", "avoid"} or row.latest_confidence < 0.4:
            conservative_count += 1

    recent_review_events = [
        ReviewEvent(
            symbol=event.symbol,
            previous_action=event.previous_action,
            current_action=event.current_action,
            confidence=event.confidence,
            summary=event.summary,
            created_at=event.created_at,
        )
        for event in recommendation_events[:6]
    ]
    latest_event = recent_review_events[0] if recent_review_events else None
    stale_run_count = len([run for run in recent_runs if bool(run.get("stale"))])
    unread_high_alert_count = len(
        [alert for alert in unread_alerts if alert.unread and alert.level == "high"]
    )

    if sentiment_worker_state is None:
        sentiment_worker_status = "idle"
        sentiment_latest_update = None
        sentiment_failure_count = 0
    else:
        sentiment_worker_status = sentiment_worker_state.status
        sentiment_latest_update = (
            sentiment_worker_state.last_completed_at
            or sentiment_worker_state.last_heartbeat_at
            or sentiment_worker_state.last_started_at
        )
        sentiment_failure_count = sentiment_worker_state.failure_count

    failure_summary = [
        f"{failure.source_name} · {failure.error_code}"
        for failure in latest_source_failures[:3]
    ]
    timestamp = (generated_at or datetime.now(UTC)).isoformat(timespec="minutes")

    return RecommendationReviewReport(
        generated_at=timestamp,
        watchlist_count=len(watchlist_rows),
        action_counts=action_counts,
        conservative_count=conservative_count,
        conservative_ratio=(
            round(conservative_count / len(watchlist_rows), 3)
            if watchlist_rows
            else 0.0
        ),
        recent_event_count=len(recommendation_events),
        stale_run_count=stale_run_count,
        unread_high_alert_count=unread_high_alert_count,
        sentiment_worker_status=sentiment_worker_status,
        sentiment_latest_update=sentiment_latest_update,
        sentiment_failure_count=sentiment_failure_count,
        sentiment_failure_summary=failure_summary,
        latest_event=latest_event,
        recent_events=recent_review_events,
    )
