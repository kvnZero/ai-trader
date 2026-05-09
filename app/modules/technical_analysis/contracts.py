from __future__ import annotations

from dataclasses import dataclass, field

from app.domain import MarketBar, SignalDirection, TechnicalSignal


@dataclass(frozen=True, slots=True)
class TechnicalIndicatorSnapshot:
    symbol: str
    sma_5: float | None = None
    sma_10: float | None = None
    sma_20: float | None = None
    sma_60: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    change_1d: float | None = None
    change_5d: float | None = None
    change_10d: float | None = None
    momentum_acceleration_5d: float | None = None
    volume_ratio_5d: float | None = None
    volume_ratio_20d: float | None = None
    intraday_range_percent: float | None = None
    breakout_level: float | None = None
    breakdown_level: float | None = None


@dataclass(frozen=True, slots=True)
class TechnicalAnalysisResult:
    symbol: str
    latest_bar: MarketBar
    analyzed_bar_count: int
    trend_direction: SignalDirection
    indicator_snapshot: TechnicalIndicatorSnapshot
    signals: list[TechnicalSignal] = field(default_factory=list)
    bullish_score: float = 0.0
    bearish_score: float = 0.0
    warnings: list[str] = field(default_factory=list)
