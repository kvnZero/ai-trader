from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.entity_mapping import CompanyDictionary
from app.persistence import PortfolioSettingsRow, WatchlistRow


_ACTION_SCORES = {
    "buy": 1.0,
    "sell": -1.0,
    "watch": 0.2,
    "avoid": 0.0,
}


@dataclass(frozen=True, slots=True)
class PortfolioPositionPlan:
    symbol: str
    name: str
    recommendation: str
    confidence: float
    proposed_weight_pct: float
    industry: str | None
    themes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PortfolioSummary:
    total_watchlist_count: int
    active_buy_count: int
    high_conviction_count: int
    total_risk_budget_pct: float
    remaining_risk_budget_pct: float
    industry_exposure: dict[str, float]
    theme_exposure: dict[str, float]
    position_plans: list[PortfolioPositionPlan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PortfolioHolding:
    symbol: str
    weight_pct: float
    name: str | None = None


@dataclass(frozen=True, slots=True)
class PortfolioAccountState:
    cash_pct: float = 100.0
    holdings: list[PortfolioHolding] = field(default_factory=list)


def build_portfolio_summary(
    *,
    watchlist_rows: list[WatchlistRow],
    company_dictionary: CompanyDictionary,
    settings: PortfolioSettingsRow,
    account_state: PortfolioAccountState | dict[str, Any] | None = None,
) -> PortfolioSummary:
    resolved_account_state = _coerce_account_state(account_state)
    company_lookup = {
        entry.company.symbol: entry.company
        for entry in company_dictionary.entries
    }

    candidate_rows = [
        row
        for row in watchlist_rows
        if row.monitoring_enabled and row.latest_recommendation in {"buy", "watch"}
    ]
    ranked_rows = sorted(
        candidate_rows,
        key=lambda row: (
            -_ACTION_SCORES.get(row.latest_recommendation, 0.0),
            -row.latest_confidence,
            row.symbol,
        ),
    )

    industry_exposure: dict[str, float] = {}
    theme_exposure: dict[str, float] = {}
    position_plans: list[PortfolioPositionPlan] = []
    warnings: list[str] = []
    consumed_budget = 0.0
    cash_capacity_pct = max(0.0, min(100.0, resolved_account_state.cash_pct))

    holding_symbols = {holding.symbol for holding in resolved_account_state.holdings}
    current_holding_weight = 0.0
    for holding in resolved_account_state.holdings:
        current_weight = round(max(0.0, holding.weight_pct), 2)
        if current_weight <= 0:
            continue
        current_holding_weight += current_weight
        company = company_lookup.get(holding.symbol)
        if company is None:
            continue
        if company.industry:
            industry_exposure[company.industry] = round(
                industry_exposure.get(company.industry, 0.0) + current_weight,
                2,
            )
        for theme in company.themes:
            theme_exposure[theme] = round(
                theme_exposure.get(theme, 0.0) + current_weight,
                2,
            )

    consumed_budget = min(settings.max_total_risk_budget_pct, round(current_holding_weight, 2))

    for row in ranked_rows:
        company = company_lookup.get(row.symbol)
        industry = company.industry if company is not None else None
        themes = list(company.themes) if company is not None else []
        base_weight = _base_weight_for_row(
            recommendation=row.latest_recommendation,
            confidence=row.latest_confidence,
            max_single_position_pct=settings.max_single_position_pct,
        )
        notes: list[str] = []
        adjusted_weight = base_weight
        existing_holding_weight = _holding_weight_for_symbol(
            resolved_account_state.holdings,
            symbol=row.symbol,
        )

        if existing_holding_weight > 0:
            adjusted_weight = max(0.0, adjusted_weight - existing_holding_weight)
            notes.append("已存在持仓，建议仓位按当前持仓占比净额计算。")

        if industry:
            current_industry_exposure = industry_exposure.get(industry, 0.0)
            if current_industry_exposure + adjusted_weight > settings.max_industry_exposure_pct:
                adjusted_weight = max(0.0, settings.max_industry_exposure_pct - current_industry_exposure)
                notes.append("行业暴露受限，已压缩建议仓位。")

        overlapping_themes = [
            theme
            for theme in themes
            if theme_exposure.get(theme, 0.0) + adjusted_weight > settings.max_theme_overlap_pct
        ]
        if overlapping_themes:
            adjusted_weight = min(adjusted_weight, settings.max_single_position_pct * 0.5)
            notes.append("主题重叠偏高，已降低建议仓位。")

        if consumed_budget + adjusted_weight > settings.max_total_risk_budget_pct:
            adjusted_weight = max(0.0, settings.max_total_risk_budget_pct - consumed_budget)
            notes.append("组合风险预算不足，已截断新增仓位。")

        if adjusted_weight > cash_capacity_pct:
            adjusted_weight = cash_capacity_pct
            notes.append("可用现金不足，已按现金上限压缩新增仓位。")

        adjusted_weight = round(adjusted_weight, 2)
        if adjusted_weight <= 0:
            if row.symbol in holding_symbols:
                warnings.append(f"{row.symbol} 已有持仓已覆盖目标仓位，本次不新增。")
            else:
                warnings.append(f"{row.symbol} 因组合约束未分配新增仓位。")
            continue

        consumed_budget += adjusted_weight
        cash_capacity_pct = round(max(0.0, cash_capacity_pct - adjusted_weight), 2)
        if industry:
            industry_exposure[industry] = round(industry_exposure.get(industry, 0.0) + adjusted_weight, 2)
        for theme in themes:
            theme_exposure[theme] = round(theme_exposure.get(theme, 0.0) + adjusted_weight, 2)

        position_plans.append(
            PortfolioPositionPlan(
                symbol=row.symbol,
                name=row.name,
                recommendation=row.latest_recommendation,
                confidence=row.latest_confidence,
                proposed_weight_pct=adjusted_weight,
                industry=industry,
                themes=themes[:4],
                notes=notes,
            )
        )

    if any(weight > settings.max_industry_exposure_pct for weight in industry_exposure.values()):
        warnings.append("存在行业暴露超过建议上限的情况。")
    if current_holding_weight > settings.max_total_risk_budget_pct:
        warnings.append("当前持仓已超过组合风险预算上限，新建议仅供减仓或调仓参考。")
    if resolved_account_state.cash_pct <= 0:
        warnings.append("当前无可用现金，新建议仓位已全部受现金约束。")

    return PortfolioSummary(
        total_watchlist_count=len(watchlist_rows),
        active_buy_count=len([row for row in watchlist_rows if row.latest_recommendation == "buy"]),
        high_conviction_count=len([row for row in watchlist_rows if row.latest_confidence >= 0.7]),
        total_risk_budget_pct=settings.max_total_risk_budget_pct,
        remaining_risk_budget_pct=round(
            min(
                max(0.0, settings.max_total_risk_budget_pct - consumed_budget),
                cash_capacity_pct,
            ),
            2,
        ),
        industry_exposure=dict(sorted(industry_exposure.items(), key=lambda item: (-item[1], item[0]))),
        theme_exposure=dict(sorted(theme_exposure.items(), key=lambda item: (-item[1], item[0]))),
        position_plans=position_plans,
        warnings=warnings,
    )


def _base_weight_for_row(
    *,
    recommendation: str,
    confidence: float,
    max_single_position_pct: float,
) -> float:
    action_score = _ACTION_SCORES.get(recommendation, 0.0)
    if action_score <= 0:
        return 0.0
    confidence_factor = max(0.2, min(1.0, confidence))
    return round(max_single_position_pct * action_score * confidence_factor, 2)


def _coerce_account_state(
    account_state: PortfolioAccountState | dict[str, Any] | None,
) -> PortfolioAccountState:
    if account_state is None:
        return PortfolioAccountState()
    if isinstance(account_state, PortfolioAccountState):
        return account_state

    raw_cash_pct = account_state.get("cash_pct", account_state.get("cash_balance_pct", 100.0))
    try:
        cash_pct = float(raw_cash_pct)
    except (TypeError, ValueError):
        cash_pct = 100.0

    holdings: list[PortfolioHolding] = []
    for item in account_state.get("holdings", []):
        if isinstance(item, PortfolioHolding):
            holdings.append(item)
            continue
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip()
        if not symbol:
            continue
        raw_weight = item.get("weight_pct", item.get("market_value_pct", item.get("position_pct", 0.0)))
        try:
            weight_pct = float(raw_weight)
        except (TypeError, ValueError):
            continue
        holdings.append(
            PortfolioHolding(
                symbol=symbol,
                weight_pct=weight_pct,
                name=str(item.get("name")).strip() if item.get("name") else None,
            )
        )

    return PortfolioAccountState(
        cash_pct=max(0.0, min(100.0, cash_pct)),
        holdings=holdings,
    )


def _holding_weight_for_symbol(holdings: list[PortfolioHolding], *, symbol: str) -> float:
    total = 0.0
    for holding in holdings:
        if holding.symbol == symbol:
            total += max(0.0, holding.weight_pct)
    return round(total, 2)
