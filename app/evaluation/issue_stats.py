from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.persistence import IssueLedgerRow


@dataclass(frozen=True, slots=True)
class IssueTrendPoint:
    day: str
    count: int


@dataclass(frozen=True, slots=True)
class IssueStatsRow:
    key: str
    count: int


@dataclass(frozen=True, slots=True)
class IssueStatsReport:
    generated_at: str
    total_count: int
    open_count: int
    high_count: int
    status_counts: list[IssueStatsRow] = field(default_factory=list)
    severity_counts: list[IssueStatsRow] = field(default_factory=list)
    type_counts: list[IssueStatsRow] = field(default_factory=list)
    top_symbols: list[IssueStatsRow] = field(default_factory=list)
    trend: list[IssueTrendPoint] = field(default_factory=list)


def build_issue_stats_report(
    *,
    issue_rows: list[IssueLedgerRow],
    generated_at: datetime | None = None,
) -> IssueStatsReport:
    status_counts = _count_rows(issue_rows, key_fn=lambda row: row.status)
    severity_counts = _count_rows(issue_rows, key_fn=lambda row: row.severity)
    type_counts = _count_rows(issue_rows, key_fn=lambda row: row.issue_type)
    top_symbols = _count_rows(
        [row for row in issue_rows if row.symbol],
        key_fn=lambda row: row.symbol or "unknown",
    )[:8]
    trend_counts: dict[str, int] = {}
    for row in issue_rows:
        day = row.created_at[:10]
        trend_counts[day] = trend_counts.get(day, 0) + 1

    timestamp = (generated_at or datetime.now(UTC)).isoformat(timespec="minutes")
    return IssueStatsReport(
        generated_at=timestamp,
        total_count=len(issue_rows),
        open_count=len([row for row in issue_rows if row.status == "open"]),
        high_count=len([row for row in issue_rows if row.severity == "high"]),
        status_counts=status_counts,
        severity_counts=severity_counts,
        type_counts=type_counts,
        top_symbols=top_symbols,
        trend=[
            IssueTrendPoint(day=day, count=count)
            for day, count in sorted(trend_counts.items())
        ],
    )


def _count_rows(
    rows: list[IssueLedgerRow],
    *,
    key_fn,
) -> list[IssueStatsRow]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(key_fn(row))
        counts[key] = counts.get(key, 0) + 1
    return [
        IssueStatsRow(key=key, count=count)
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
