from __future__ import annotations

import hashlib

from app.persistence import AlertRepository, IssueLedgerRepository, PortfolioHoldingRepository
from app.portfolio import build_portfolio_rebalance_playbook


def is_held_symbol(
    *,
    holding_repository: PortfolioHoldingRepository,
    symbol: str | None,
) -> bool:
    normalized_symbol = (symbol or "").strip()
    if not normalized_symbol:
        return False
    return holding_repository.get_row(normalized_symbol) is not None


def create_portfolio_risk_alert(
    *,
    alert_repository: AlertRepository,
    symbol: str,
    title: str,
    summary: str,
    risk_type: str,
    source: str,
    level: str = "high",
) -> bool:
    return alert_repository.create_alert(
        symbol=symbol,
        title=title,
        summary=summary,
        level=level,
        dedupe_key=_build_portfolio_risk_dedupe_key(
            symbol=symbol,
            title=title,
            risk_type=risk_type,
            source=source,
        ),
    )


def create_portfolio_risk_issue(
    *,
    issue_repository: IssueLedgerRepository | None,
    symbol: str,
    issue_type: str,
    message: str,
    source: str,
    origin_worker: str,
    details: dict[str, object] | None = None,
    severity: str = "high",
) -> bool:
    if issue_repository is None:
        return False
    return issue_repository.create_issue(
        issue_type=issue_type,
        severity=severity,
        status="open",
        symbol=symbol,
        source=source,
        origin_worker=origin_worker,
        message=message,
        details=details or {},
    )


def emit_portfolio_rebalance_risk(
    *,
    alert_repository: AlertRepository,
    issue_repository: IssueLedgerRepository | None,
    symbol: str,
    name: str,
    account_state: object,
    portfolio_summary: object,
    portfolio_risk_overview: object,
    source: str,
    origin_worker: str,
) -> bool:
    playbook = build_portfolio_rebalance_playbook(
        account_state=account_state,
        portfolio_summary=portfolio_summary,
        portfolio_risk_overview=portfolio_risk_overview,
    )
    for action in playbook.actions:
        if action.symbol != symbol:
            continue
        if action.action != "trim_reduce" or action.priority > 1:
            return False
        summary = (
            f"持仓调仓动作已升级为高优：{name} 需要减仓/去风险 "
            f"{abs(action.target_delta):.2f}% 。{action.reason}"
        )
        created = create_portfolio_risk_alert(
            alert_repository=alert_repository,
            symbol=symbol,
            title=f"{name} 持仓调仓提醒",
            summary=summary,
            risk_type=f"portfolio_rebalance:{action.action}:{action.target_delta:.2f}",
            source=source,
            level="high",
        )
        create_portfolio_risk_issue(
            issue_repository=issue_repository,
            symbol=symbol,
            issue_type="portfolio_rebalance_high_priority",
            message=summary,
            source=source,
            origin_worker=origin_worker,
            details={
                "rebalance_action": action.action,
                "target_delta": action.target_delta,
                "priority": action.priority,
                "reason": action.reason,
            },
            severity="high",
        )
        return created
    return False


def _build_portfolio_risk_dedupe_key(
    *,
    symbol: str,
    title: str,
    risk_type: str,
    source: str,
) -> str:
    return hashlib.sha256(
        "|".join([symbol, title, risk_type, source]).encode("utf-8")
    ).hexdigest()
