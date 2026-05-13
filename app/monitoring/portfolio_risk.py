from __future__ import annotations

import hashlib

from app.persistence import AlertRepository, IssueLedgerRepository, PortfolioHoldingRepository


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
