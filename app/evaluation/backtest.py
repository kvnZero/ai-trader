from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from app.domain import MarketBar
from app.modules.market_data.contracts import MarketDataResult
from app.persistence import RecommendationSnapshotRow


class HistoricalBarProvider(Protocol):
    def get_daily_bars(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        adjust: str = "",
        limit: int | None = None,
    ) -> MarketDataResult[list[MarketBar]]:
        ...


@dataclass(frozen=True, slots=True)
class BacktestEvaluationRow:
    symbol: str
    action: str
    source: str
    snapshot_at: str
    entry_date: str
    exit_date: str
    market_regime: str | None
    market_regime_label: str | None
    confidence: float
    forward_return_pct: float
    max_runup_pct: float
    max_drawdown_pct: float
    directional_hit: bool | None
    conservative_hit: bool | None


@dataclass(frozen=True, slots=True)
class BacktestBreakdownRow:
    key: str
    label: str
    snapshot_count: int
    evaluated_count: int
    hit_count: int
    hit_rate: float
    average_forward_return_pct: float
    average_max_runup_pct: float
    average_max_drawdown_pct: float


@dataclass(frozen=True, slots=True)
class BacktestSummaryReport:
    generated_at: str
    snapshot_count: int
    evaluated_count: int
    skipped_count: int
    buy_sell_evaluated_count: int
    buy_sell_hit_count: int
    buy_sell_hit_rate: float
    conservative_evaluated_count: int
    conservative_hit_count: int
    conservative_hit_rate: float
    average_forward_return_pct: float
    average_max_runup_pct: float
    average_max_drawdown_pct: float
    regime_counts: dict[str, int]
    regime_breakdown: list[BacktestBreakdownRow] = field(default_factory=list)
    action_breakdown: list[BacktestBreakdownRow] = field(default_factory=list)
    evaluations: list[BacktestEvaluationRow] = field(default_factory=list)


def build_backtest_summary_report(
    *,
    snapshots: list[RecommendationSnapshotRow],
    market_data_service: HistoricalBarProvider,
    horizon_bars: int = 5,
    neutral_band_pct: float = 2.0,
    generated_at: datetime | None = None,
) -> BacktestSummaryReport:
    evaluations: list[BacktestEvaluationRow] = []
    skipped_count = 0
    regime_counts: dict[str, int] = {}
    forward_returns: list[float] = []
    max_runups: list[float] = []
    max_drawdowns: list[float] = []
    buy_sell_evaluated_count = 0
    buy_sell_hit_count = 0
    conservative_evaluated_count = 0
    conservative_hit_count = 0
    regime_groups: dict[str, list[BacktestEvaluationRow]] = {}
    action_groups: dict[str, list[BacktestEvaluationRow]] = {}

    for snapshot in snapshots:
        snapshot_dt = _parse_snapshot_datetime(snapshot.created_at)
        date_window_end = snapshot_dt.date() + timedelta(days=max(horizon_bars * 4, 20))
        result = market_data_service.get_daily_bars(
            snapshot.symbol,
            start_date=snapshot_dt.date(),
            end_date=date_window_end,
            limit=max(horizon_bars + 5, 12),
        )
        bars = list(result.data or [])
        if not bars:
            skipped_count += 1
            continue

        entry_index = _find_entry_index(bars, snapshot_dt.date())
        if entry_index is None:
            skipped_count += 1
            continue

        future_bars = bars[entry_index : entry_index + horizon_bars]
        if len(future_bars) < 2:
            skipped_count += 1
            continue

        entry_bar = future_bars[0]
        exit_bar = future_bars[-1]
        entry_close = entry_bar.close_price
        exit_close = exit_bar.close_price
        forward_return_pct = _pct_change(entry_close, exit_close)
        max_runup_pct = max(_pct_change(entry_close, bar.high_price) for bar in future_bars)
        max_drawdown_pct = min(_pct_change(entry_close, bar.low_price) for bar in future_bars)

        directional_hit: bool | None = None
        conservative_hit: bool | None = None
        if snapshot.recommendation in {"buy", "sell"}:
            buy_sell_evaluated_count += 1
            directional_hit = (
                forward_return_pct > 0
                if snapshot.recommendation == "buy"
                else forward_return_pct < 0
            )
            if directional_hit:
                buy_sell_hit_count += 1
        else:
            conservative_evaluated_count += 1
            if snapshot.recommendation == "watch":
                conservative_hit = abs(forward_return_pct) <= neutral_band_pct
            else:
                conservative_hit = forward_return_pct <= neutral_band_pct
            if conservative_hit:
                conservative_hit_count += 1

        regime_key = snapshot.market_regime or "unknown"
        regime_counts[regime_key] = regime_counts.get(regime_key, 0) + 1
        forward_returns.append(forward_return_pct)
        max_runups.append(max_runup_pct)
        max_drawdowns.append(max_drawdown_pct)
        evaluations.append(
            BacktestEvaluationRow(
                symbol=snapshot.symbol,
                action=snapshot.recommendation,
                source=snapshot.source,
                snapshot_at=snapshot.created_at,
                entry_date=entry_bar.trade_date.isoformat(),
                exit_date=exit_bar.trade_date.isoformat(),
                market_regime=snapshot.market_regime,
                market_regime_label=snapshot.market_regime_label,
                confidence=snapshot.confidence,
                forward_return_pct=round(forward_return_pct, 3),
                max_runup_pct=round(max_runup_pct, 3),
                max_drawdown_pct=round(max_drawdown_pct, 3),
                directional_hit=directional_hit,
                conservative_hit=conservative_hit,
            )
        )
        current_evaluation = evaluations[-1]
        regime_groups.setdefault(regime_key, []).append(current_evaluation)
        action_groups.setdefault(snapshot.recommendation, []).append(current_evaluation)

    timestamp = (generated_at or datetime.now(UTC)).isoformat(timespec="minutes")
    return BacktestSummaryReport(
        generated_at=timestamp,
        snapshot_count=len(snapshots),
        evaluated_count=len(evaluations),
        skipped_count=skipped_count,
        buy_sell_evaluated_count=buy_sell_evaluated_count,
        buy_sell_hit_count=buy_sell_hit_count,
        buy_sell_hit_rate=(
            round(buy_sell_hit_count / buy_sell_evaluated_count, 3)
            if buy_sell_evaluated_count
            else 0.0
        ),
        conservative_evaluated_count=conservative_evaluated_count,
        conservative_hit_count=conservative_hit_count,
        conservative_hit_rate=(
            round(conservative_hit_count / conservative_evaluated_count, 3)
            if conservative_evaluated_count
            else 0.0
        ),
        average_forward_return_pct=round(_average(forward_returns), 3),
        average_max_runup_pct=round(_average(max_runups), 3),
        average_max_drawdown_pct=round(_average(max_drawdowns), 3),
        regime_counts=dict(sorted(regime_counts.items(), key=lambda item: (-item[1], item[0]))),
        regime_breakdown=_build_breakdown_rows(regime_groups),
        action_breakdown=_build_breakdown_rows(action_groups),
        evaluations=evaluations[:8],
    )


def _parse_snapshot_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _find_entry_index(bars: list[MarketBar], snapshot_date: date) -> int | None:
    for index, bar in enumerate(bars):
        if bar.trade_date >= snapshot_date:
            return index
    return None


def _pct_change(base: float, target: float) -> float:
    if base == 0:
        return 0.0
    return ((target - base) / base) * 100


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _build_breakdown_rows(groups: dict[str, list[BacktestEvaluationRow]]) -> list[BacktestBreakdownRow]:
    rows: list[BacktestBreakdownRow] = []
    for key, evaluations in groups.items():
        hits = 0
        for evaluation in evaluations:
            if evaluation.directional_hit is True or evaluation.conservative_hit is True:
                hits += 1
        rows.append(
            BacktestBreakdownRow(
                key=key,
                label=key,
                snapshot_count=len(evaluations),
                evaluated_count=len(evaluations),
                hit_count=hits,
                hit_rate=round(hits / len(evaluations), 3) if evaluations else 0.0,
                average_forward_return_pct=round(
                    _average([evaluation.forward_return_pct for evaluation in evaluations]),
                    3,
                ),
                average_max_runup_pct=round(
                    _average([evaluation.max_runup_pct for evaluation in evaluations]),
                    3,
                ),
                average_max_drawdown_pct=round(
                    _average([evaluation.max_drawdown_pct for evaluation in evaluations]),
                    3,
                ),
            )
        )
    return sorted(rows, key=lambda row: (-row.snapshot_count, row.key))
