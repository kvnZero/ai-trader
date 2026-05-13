from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
from datetime import UTC, datetime
from typing import Any


_ACTION_PRIORITY = {
    "trim_reduce": 1,
    "buy_add": 2,
    "hold_monitor": 3,
    "no_action": 4,
}


@dataclass(frozen=True, slots=True)
class PortfolioRebalanceAction:
    symbol: str
    action: str
    current_weight: float
    target_delta: float
    reason: str
    priority: int


@dataclass(frozen=True, slots=True)
class PortfolioRebalancePlaybook:
    generated_at: str
    action_counts: dict[str, int]
    actions: list[PortfolioRebalanceAction] = field(default_factory=list)


def build_portfolio_rebalance_playbook(
    *,
    account_state: Any,
    portfolio_summary: Any,
    portfolio_risk_overview: Any,
    generated_at: datetime | None = None,
) -> PortfolioRebalancePlaybook:
    account_payload = _to_mapping(account_state)
    summary_payload = _to_mapping(portfolio_summary)
    risk_payload = _to_mapping(portfolio_risk_overview)

    holdings_by_symbol = {
        str(item.get("symbol")): item
        for item in account_payload.get("holdings", [])
        if isinstance(item, dict) and item.get("symbol")
    }
    plan_by_symbol = {
        str(item.get("symbol")): item
        for item in _coerce_items(summary_payload.get("position_plans", []))
        if item.get("symbol")
    }
    risk_by_symbol = {
        str(item.get("symbol")): item
        for item in _coerce_items(risk_payload.get("items", []))
        if item.get("symbol")
    }

    symbols = sorted(set(holdings_by_symbol) | set(plan_by_symbol) | set(risk_by_symbol))
    actions: list[PortfolioRebalanceAction] = []
    action_counts = {"buy_add": 0, "trim_reduce": 0, "hold_monitor": 0, "no_action": 0}

    for symbol in symbols:
        holding = holdings_by_symbol.get(symbol, {})
        plan = plan_by_symbol.get(symbol, {})
        risk = risk_by_symbol.get(symbol, {})
        current_weight = _coerce_float(holding.get("weight_pct", 0.0))
        plan_add = _coerce_float(plan.get("proposed_weight_pct", 0.0))
        risk_action = str(risk.get("portfolio_action", "")).strip().lower()
        risk_reason = str(risk.get("portfolio_action_reason", "")).strip()
        action, target_delta, reason = _derive_action(
            current_weight=current_weight,
            plan_add=plan_add,
            risk_action=risk_action,
            risk_reason=risk_reason,
            plan_notes=[str(note) for note in plan.get("notes", []) if str(note).strip()],
        )
        priority = _ACTION_PRIORITY[action]
        action_counts[action] += 1
        actions.append(
            PortfolioRebalanceAction(
                symbol=symbol,
                action=action,
                current_weight=round(current_weight, 2),
                target_delta=round(target_delta, 2),
                reason=reason,
                priority=priority,
            )
        )

    actions.sort(key=lambda item: (item.priority, -abs(item.target_delta), item.symbol))
    timestamp = (generated_at or datetime.now(UTC)).isoformat(timespec="minutes")
    return PortfolioRebalancePlaybook(
        generated_at=timestamp,
        action_counts=action_counts,
        actions=actions,
    )


def _derive_action(
    *,
    current_weight: float,
    plan_add: float,
    risk_action: str,
    risk_reason: str,
    plan_notes: list[str],
) -> tuple[str, float, str]:
    if current_weight > 0 and risk_action == "trim":
        return "trim_reduce", -current_weight, risk_reason or "Risk playbook requires a full trim."
    if current_weight > 0 and risk_action == "reduce":
        reduction = min(current_weight, plan_add if plan_add > 0 else round(current_weight * 0.5, 2))
        return "trim_reduce", -reduction, risk_reason or "Risk playbook requires reducing exposure."
    if plan_add > 0:
        if plan_notes:
            return "buy_add", plan_add, " ".join(plan_notes)
        return "buy_add", plan_add, "Position plan suggests adding exposure."
    if current_weight > 0 and risk_action in {"watch", "hold"}:
        reason = risk_reason or "Maintain the holding and continue monitoring."
        return "hold_monitor", 0.0, reason
    return "no_action", 0.0, "No rebalance action is required."


def _to_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return {
            field_name: getattr(value, field_name)
            for field_name in value.__dataclass_fields__
        }
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _coerce_items(items: Any) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return resolved
    for item in items:
        mapping = _to_mapping(item)
        if mapping:
            resolved.append(mapping)
    return resolved


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
