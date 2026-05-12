from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.entity_mapping import CompanyDictionary
from app.persistence import WatchlistRow


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


def build_portfolio_summary(
    *,
    watchlist_rows: list[WatchlistRow],
    company_dictionary: CompanyDictionary,
    max_total_risk_budget_pct: float = 100.0,
    max_single_position_pct: float = 20.0,
    max_industry_exposure_pct: float = 35.0,
    max_theme_overlap_pct: float = 45.0,
) -> PortfolioSummary:
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

    for row in ranked_rows:
        company = company_lookup.get(row.symbol)
        industry = company.industry if company is not None else None
        themes = list(company.themes) if company is not None else []
        base_weight = _base_weight_for_row(
            recommendation=row.latest_recommendation,
            confidence=row.latest_confidence,
            max_single_position_pct=max_single_position_pct,
        )
        notes: list[str] = []
        adjusted_weight = base_weight

        if industry:
            current_industry_exposure = industry_exposure.get(industry, 0.0)
            if current_industry_exposure + adjusted_weight > max_industry_exposure_pct:
                adjusted_weight = max(0.0, max_industry_exposure_pct - current_industry_exposure)
                notes.append("行业暴露受限，已压缩建议仓位。")

        overlapping_themes = [
            theme
            for theme in themes
            if theme_exposure.get(theme, 0.0) + adjusted_weight > max_theme_overlap_pct
        ]
        if overlapping_themes:
            adjusted_weight = min(adjusted_weight, max_single_position_pct * 0.5)
            notes.append("主题重叠偏高，已降低建议仓位。")

        if consumed_budget + adjusted_weight > max_total_risk_budget_pct:
            adjusted_weight = max(0.0, max_total_risk_budget_pct - consumed_budget)
            notes.append("组合风险预算不足，已截断新增仓位。")

        adjusted_weight = round(adjusted_weight, 2)
        if adjusted_weight <= 0:
            warnings.append(f"{row.symbol} 因组合约束未分配新增仓位。")
            continue

        consumed_budget += adjusted_weight
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

    if any(weight > max_industry_exposure_pct for weight in industry_exposure.values()):
        warnings.append("存在行业暴露超过建议上限的情况。")

    return PortfolioSummary(
        total_watchlist_count=len(watchlist_rows),
        active_buy_count=len([row for row in watchlist_rows if row.latest_recommendation == "buy"]),
        high_conviction_count=len([row for row in watchlist_rows if row.latest_confidence >= 0.7]),
        total_risk_budget_pct=max_total_risk_budget_pct,
        remaining_risk_budget_pct=round(max_total_risk_budget_pct - consumed_budget, 2),
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
