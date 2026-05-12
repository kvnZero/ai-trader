from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.persistence import (
    AlertRow,
    IssueLedgerRow,
    RecommendationSnapshotRow,
    SentimentSourceFailureRow,
    SentimentWorkerStateRow,
)


@dataclass(frozen=True, slots=True)
class IssueTimelineEntry:
    issue_id: int | None
    issue_type: str
    severity: str
    status: str
    symbol: str | None
    source: str
    message: str
    created_at: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IssueTimelineReport:
    generated_at: str
    issue_count: int
    open_count: int
    high_count: int
    severity_counts: dict[str, int]
    type_counts: dict[str, int]
    latest_issue_at: str | None
    items: list[IssueTimelineEntry] = field(default_factory=list)


def build_issue_timeline_report(
    *,
    ledger_rows: list[IssueLedgerRow] | None = None,
    worker_state: SentimentWorkerStateRow | None,
    source_failures: list[SentimentSourceFailureRow],
    snapshots: list[RecommendationSnapshotRow],
    unread_alerts: list[AlertRow],
    symbol: str | None = None,
    issue_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    generated_at: datetime | None = None,
    limit: int = 12,
) -> IssueTimelineReport:
    items: list[IssueTimelineEntry] = []

    if ledger_rows:
        items.extend(_ledger_row_to_entry(row) for row in ledger_rows)
    else:
        if worker_state is not None and worker_state.status in {"failed", "degraded"}:
            worker_severity = "high" if worker_state.status == "failed" else "medium"
            items.append(
                IssueTimelineEntry(
                    issue_id=None,
                    issue_type="sentiment_worker_state",
                    severity=worker_severity,
                    status="open",
                    symbol=None,
                    source=worker_state.worker_name,
                    message=f"sentiment worker status is {worker_state.status}",
                    created_at=(
                        worker_state.last_completed_at
                        or worker_state.last_heartbeat_at
                        or worker_state.last_started_at
                        or ""
                    ),
                    details={
                        "failure_count": worker_state.failure_count,
                        "item_count": worker_state.item_count,
                        "source_run_count": worker_state.source_run_count,
                    },
                )
            )

        for failure in source_failures:
            items.append(
                IssueTimelineEntry(
                    issue_id=None,
                    issue_type="sentiment_source_failure",
                    severity="high" if not failure.retryable else "medium",
                    status="open",
                    symbol=None,
                    source=failure.source_name,
                    message=failure.error_message,
                    created_at=failure.failed_at,
                    details={
                        "source_id": failure.source_id,
                        "error_code": failure.error_code,
                        "retryable": failure.retryable,
                    },
                )
            )

        for snapshot in snapshots:
            if snapshot.recommendation not in {"watch", "avoid"} and snapshot.confidence >= 0.4:
                continue
            snapshot_issue_type = (
                "low_quality_signal"
                if snapshot.confidence < 0.4
                else "conservative_signal"
            )
            snapshot_severity = "medium" if snapshot.confidence < 0.4 else "low"
            items.append(
                IssueTimelineEntry(
                    issue_id=None,
                    issue_type=snapshot_issue_type,
                    severity=snapshot_severity,
                    status="open",
                    symbol=snapshot.symbol,
                    source=snapshot.source,
                    message=snapshot.reason,
                    created_at=snapshot.created_at,
                    details={
                        "recommendation": snapshot.recommendation,
                        "market_regime": snapshot.market_regime,
                        "market_regime_label": snapshot.market_regime_label,
                        "confidence": snapshot.confidence,
                        "sentiment_count": snapshot.sentiment_count,
                        "company_match_count": snapshot.company_match_count,
                    },
                )
            )

    for alert in unread_alerts:
        if not alert.unread:
            continue
        items.append(
            IssueTimelineEntry(
                issue_id=None,
                issue_type="unread_alert",
                severity="high" if alert.level == "high" else "medium",
                status="open",
                symbol=alert.symbol,
                source="alert_center",
                message=alert.title,
                created_at=alert.created_at,
                details={"summary": alert.summary, "level": alert.level},
            )
        )

    if symbol:
        items = [item for item in items if item.symbol == symbol]
    if issue_type:
        items = [item for item in items if item.issue_type == issue_type]
    if severity:
        items = [item for item in items if item.severity == severity]
    if status:
        items = [item for item in items if item.status == status]

    items.sort(key=lambda item: item.created_at, reverse=True)
    limited_items = items[:limit]
    severity_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    open_count = 0
    high_count = 0
    for item in limited_items:
        severity_counts[item.severity] = severity_counts.get(item.severity, 0) + 1
        type_counts[item.issue_type] = type_counts.get(item.issue_type, 0) + 1
        if item.status == "open":
            open_count += 1
        if item.severity == "high":
            high_count += 1

    timestamp = (generated_at or datetime.now(UTC)).isoformat(timespec="minutes")
    latest_issue_at = limited_items[0].created_at if limited_items else None
    return IssueTimelineReport(
        generated_at=timestamp,
        issue_count=len(limited_items),
        open_count=open_count,
        high_count=high_count,
        severity_counts=dict(sorted(severity_counts.items(), key=lambda item: (-item[1], item[0]))),
        type_counts=dict(sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))),
        latest_issue_at=latest_issue_at,
        items=limited_items,
    )


def _ledger_row_to_entry(row: IssueLedgerRow) -> IssueTimelineEntry:
    return IssueTimelineEntry(
        issue_id=row.id,
        issue_type=row.issue_type,
        severity=row.severity,
        status=row.status,
        symbol=row.symbol,
        source=row.source or row.origin_worker or "ledger",
        message=row.message,
        created_at=row.last_seen_at or row.created_at,
        details={**dict(row.details), "occurrence_count": row.occurrence_count},
    )
