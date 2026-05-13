from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.persistence import (
    IssueLedgerRepository,
    MarketEventRepository,
    PortfolioHoldingRepository,
    RecommendationSnapshotRepository,
    SignalLifecycleRepository,
)


_RISK_ACTION_PRIORITY = {
    "trim": 0,
    "reduce": 1,
    "watch": 2,
    "hold": 3,
}


@dataclass(frozen=True, slots=True)
class HoldingRiskItem:
    symbol: str
    name: str
    current_action: str | None
    current_confidence: float | None
    portfolio_action: str
    portfolio_action_reason: str
    high_severity_event_count: int
    open_high_issue_count: int
    lifecycle_status: str | None
    lifecycle_reason: str | None
    risk_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PortfolioRiskOverviewReport:
    generated_at: str
    held_symbol_count: int
    action_counts: dict[str, int]
    high_risk_count: int
    items: list[HoldingRiskItem] = field(default_factory=list)


def build_portfolio_risk_overview(
    *,
    holding_repository: PortfolioHoldingRepository,
    market_event_repository: MarketEventRepository,
    signal_lifecycle_repository: SignalLifecycleRepository | None,
    issue_repository: IssueLedgerRepository | None,
    recommendation_snapshot_repository: RecommendationSnapshotRepository | None,
    generated_at: datetime | None = None,
) -> PortfolioRiskOverviewReport:
    holdings = holding_repository.list_rows()
    items: list[HoldingRiskItem] = []
    action_counts = {"trim": 0, "reduce": 0, "watch": 0, "hold": 0}

    for holding in holdings:
        recent_events = market_event_repository.list_recent(limit=12, symbol=holding.symbol)
        high_events = [row for row in recent_events if row.severity == "high"]
        lifecycle = (
            signal_lifecycle_repository.get(holding.symbol)
            if signal_lifecycle_repository is not None
            else None
        )
        open_high_issues = (
            issue_repository.list_recent(
                limit=20,
                symbol=holding.symbol,
                severity="high",
                status="open",
            )
            if issue_repository is not None
            else []
        )
        latest_snapshot = None
        if recommendation_snapshot_repository is not None:
            snapshot_rows = recommendation_snapshot_repository.list_recent(limit=1, symbol=holding.symbol)
            latest_snapshot = snapshot_rows[0] if snapshot_rows else None

        risk_flags: list[str] = []
        if high_events:
            risk_flags.append(f"{len(high_events)} high severity market events")
        if lifecycle is not None and lifecycle.status in {"invalidated", "expired"}:
            risk_flags.append(f"signal lifecycle is {lifecycle.status}")
        if open_high_issues:
            risk_flags.append(f"{len(open_high_issues)} open high severity issues")
        if latest_snapshot is not None and latest_snapshot.recommendation in {"sell", "avoid"}:
            risk_flags.append(f"recommendation is {latest_snapshot.recommendation}")

        portfolio_action, reason = _derive_portfolio_action(
            high_event_count=len(high_events),
            lifecycle_status=lifecycle.status if lifecycle is not None else None,
            open_high_issue_count=len(open_high_issues),
            recommendation=latest_snapshot.recommendation if latest_snapshot is not None else None,
            confidence=latest_snapshot.confidence if latest_snapshot is not None else None,
        )
        action_counts[portfolio_action] += 1
        items.append(
            HoldingRiskItem(
                symbol=holding.symbol,
                name=holding.name,
                current_action=latest_snapshot.recommendation if latest_snapshot is not None else None,
                current_confidence=latest_snapshot.confidence if latest_snapshot is not None else None,
                portfolio_action=portfolio_action,
                portfolio_action_reason=reason,
                high_severity_event_count=len(high_events),
                open_high_issue_count=len(open_high_issues),
                lifecycle_status=lifecycle.status if lifecycle is not None else None,
                lifecycle_reason=lifecycle.reason if lifecycle is not None else None,
                risk_flags=risk_flags,
            )
        )

    items.sort(
        key=lambda item: (
            _RISK_ACTION_PRIORITY.get(item.portfolio_action, 99),
            -item.high_severity_event_count,
            -item.open_high_issue_count,
            item.symbol,
        )
    )
    timestamp = (generated_at or datetime.now(UTC)).isoformat(timespec="minutes")
    return PortfolioRiskOverviewReport(
        generated_at=timestamp,
        held_symbol_count=len(holdings),
        action_counts=action_counts,
        high_risk_count=len([item for item in items if item.portfolio_action in {"trim", "reduce"}]),
        items=items,
    )


def _derive_portfolio_action(
    *,
    high_event_count: int,
    lifecycle_status: str | None,
    open_high_issue_count: int,
    recommendation: str | None,
    confidence: float | None,
) -> tuple[str, str]:
    if lifecycle_status == "invalidated":
        return "trim", "Signal lifecycle is invalidated for an active holding."
    if recommendation == "sell":
        return "trim", "Latest recommendation is sell."
    if high_event_count > 0 and open_high_issue_count > 0:
        return "reduce", "High severity events and unresolved high issues are stacked."
    if lifecycle_status == "expired":
        return "reduce", "Signal lifecycle expired and requires position de-risking."
    if recommendation == "avoid":
        return "reduce", "Latest recommendation is avoid."
    if high_event_count > 0:
        return "watch", "High severity event risk exists but not enough for forced reduction."
    if open_high_issue_count > 0:
        return "watch", "Open high severity issues require closer monitoring."
    if confidence is not None and confidence < 0.45:
        return "watch", "Recommendation confidence is weak for an existing holding."
    return "hold", "No immediate portfolio-level risk override detected."
