from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Sequence

from app.domain import MarketBar, SignalDirection, TechnicalSignal
from app.modules.technical_analysis.contracts import (
    TechnicalAnalysisResult,
    TechnicalIndicatorSnapshot,
)
from app.modules.technical_analysis.errors import TechnicalAnalysisValidationError


@dataclass(frozen=True, slots=True)
class _PreparedBars:
    bars: tuple[MarketBar, ...]
    warnings: tuple[str, ...]

    @property
    def symbol(self) -> str:
        return self.bars[-1].symbol

    @property
    def latest_bar(self) -> MarketBar:
        return self.bars[-1]


@dataclass(frozen=True, slots=True)
class _SignalAssessment:
    name: str
    direction: SignalDirection
    score: float
    bullish_score: float
    bearish_score: float
    summary: str
    evidence: tuple[str, ...]
    tags: tuple[str, ...]


class TechnicalAnalysisService:
    MA_PERIODS = (5, 10, 20, 60)
    EMA_PERIODS = (12, 26)
    BREAKOUT_LOOKBACK = 20
    BREAKOUT_BUFFER = 0.003
    STRONG_VOLUME_RATIO = 1.6
    EXPANSION_VOLUME_RATIO = 1.25
    CONTRACTION_VOLUME_RATIO = 0.75

    def analyze_bars(self, bars: Sequence[MarketBar]) -> TechnicalAnalysisResult:
        prepared = self._prepare_bars(bars)
        close_values = [bar.close_price for bar in prepared.bars]
        high_values = [bar.high_price for bar in prepared.bars]
        low_values = [bar.low_price for bar in prepared.bars]
        volume_values = [bar.volume for bar in prepared.bars]

        sma_series = {
            period: self._sma_series(close_values, period)
            for period in self.MA_PERIODS
        }
        ema_series = {
            period: self._ema_series(close_values, period)
            for period in self.EMA_PERIODS
        }

        sma_5 = sma_series[5][-1]
        sma_10 = sma_series[10][-1]
        sma_20 = sma_series[20][-1]
        sma_60 = sma_series[60][-1]
        ema_12 = ema_series[12][-1]
        ema_26 = ema_series[26][-1]

        change_1d = self._percent_change(close_values, 1)
        change_5d = self._percent_change(close_values, 5)
        change_10d = self._percent_change(close_values, 10)
        momentum_acceleration_5d = self._momentum_acceleration(close_values, 5)
        volume_ratio_5d = self._ratio_to_previous_average(volume_values, 5)
        volume_ratio_20d = self._ratio_to_previous_average(volume_values, 20)

        latest_bar = prepared.latest_bar
        reference_price = self._first_non_zero(
            self._value_or_none(close_values, -2),
            latest_bar.close_price,
        )
        intraday_range_percent = self._safe_ratio(
            latest_bar.high_price - latest_bar.low_price,
            reference_price,
        )

        breakout_level, breakdown_level = self._breakout_levels(high_values, low_values)
        indicator_snapshot = TechnicalIndicatorSnapshot(
            symbol=prepared.symbol,
            sma_5=sma_5,
            sma_10=sma_10,
            sma_20=sma_20,
            sma_60=sma_60,
            ema_12=ema_12,
            ema_26=ema_26,
            change_1d=change_1d,
            change_5d=change_5d,
            change_10d=change_10d,
            momentum_acceleration_5d=momentum_acceleration_5d,
            volume_ratio_5d=volume_ratio_5d,
            volume_ratio_20d=volume_ratio_20d,
            intraday_range_percent=intraday_range_percent,
            breakout_level=breakout_level,
            breakdown_level=breakdown_level,
        )

        trend_assessment = self._assess_trend(
            latest_bar=latest_bar,
            sma_20_series=sma_series[20],
            sma_5=sma_5,
            sma_10=sma_10,
            sma_20=sma_20,
            sma_60=sma_60,
            ema_12=ema_12,
            ema_26=ema_26,
            change_10d=change_10d,
        )
        moving_average_assessment = self._assess_moving_averages(
            latest_close=latest_bar.close_price,
            sma_5=sma_5,
            sma_10=sma_10,
            sma_20=sma_20,
            sma_60=sma_60,
        )
        momentum_assessment = self._assess_momentum(
            change_1d=change_1d,
            change_5d=change_5d,
            change_10d=change_10d,
            momentum_acceleration_5d=momentum_acceleration_5d,
        )
        volume_assessment = self._assess_volume(
            latest_bar=latest_bar,
            change_1d=change_1d,
            volume_ratio_5d=volume_ratio_5d,
            volume_ratio_20d=volume_ratio_20d,
            trend_direction=trend_assessment.direction,
        )
        pattern_assessment = self._assess_patterns(
            latest_bar=latest_bar,
            change_5d=change_5d,
            volume_ratio_20d=volume_ratio_20d,
            breakout_level=breakout_level,
            breakdown_level=breakdown_level,
        )

        assessments = (
            trend_assessment,
            moving_average_assessment,
            momentum_assessment,
            volume_assessment,
            pattern_assessment,
        )
        signals = [
            TechnicalSignal(
                name=assessment.name,
                direction=assessment.direction,
                score=assessment.score,
                summary=assessment.summary,
                evidence=list(assessment.evidence),
                tags=list(assessment.tags),
            )
            for assessment in assessments
        ]

        bullish_score = round(
            sum(assessment.bullish_score for assessment in assessments) / len(assessments),
            3,
        )
        bearish_score = round(
            sum(assessment.bearish_score for assessment in assessments) / len(assessments),
            3,
        )
        trend_direction = self._resolve_direction(
            bullish_score=bullish_score,
            bearish_score=bearish_score,
        )
        return TechnicalAnalysisResult(
            symbol=prepared.symbol,
            latest_bar=latest_bar,
            analyzed_bar_count=len(prepared.bars),
            trend_direction=trend_direction,
            indicator_snapshot=indicator_snapshot,
            signals=signals,
            bullish_score=bullish_score,
            bearish_score=bearish_score,
            warnings=list(prepared.warnings),
        )

    def _prepare_bars(self, bars: Sequence[MarketBar]) -> _PreparedBars:
        if not bars:
            raise TechnicalAnalysisValidationError(
                "at least one normalized market bar is required"
            )

        warnings: list[str] = []
        normalized_by_date: dict[object, MarketBar] = {}
        symbol: str | None = None
        duplicate_trade_date_detected = False

        for bar in bars:
            candidate_symbol = bar.symbol.strip()
            if not candidate_symbol:
                raise TechnicalAnalysisValidationError("market bar symbol cannot be empty")
            if symbol is None:
                symbol = candidate_symbol
            elif candidate_symbol != symbol:
                raise TechnicalAnalysisValidationError(
                    "technical analysis requires bars for exactly one symbol"
                )

            if min(bar.open_price, bar.high_price, bar.low_price, bar.close_price) <= 0:
                raise TechnicalAnalysisValidationError(
                    "market bar prices must be strictly positive"
                )
            if bar.low_price > bar.high_price:
                raise TechnicalAnalysisValidationError(
                    "market bar low_price cannot exceed high_price"
                )
            if bar.volume < 0:
                raise TechnicalAnalysisValidationError(
                    "market bar volume cannot be negative"
                )

            if bar.trade_date in normalized_by_date:
                duplicate_trade_date_detected = True
            normalized_by_date[bar.trade_date] = bar

        normalized_bars = tuple(
            sorted(normalized_by_date.values(), key=lambda item: item.trade_date)
        )
        if duplicate_trade_date_detected:
            warnings.append(
                "duplicate trade dates were supplied; the latest bar was kept for each date"
            )
        if len(normalized_bars) < 20:
            warnings.append(
                "fewer than 20 bars supplied; medium-term averages and breakout levels use a shortened lookback"
            )
        if len(normalized_bars) < 60:
            warnings.append(
                "fewer than 60 bars supplied; long-term moving-average alignment is unavailable"
            )

        return _PreparedBars(bars=normalized_bars, warnings=tuple(warnings))

    def _assess_trend(
        self,
        *,
        latest_bar: MarketBar,
        sma_20_series: Sequence[float | None],
        sma_5: float | None,
        sma_10: float | None,
        sma_20: float | None,
        sma_60: float | None,
        ema_12: float | None,
        ema_26: float | None,
        change_10d: float | None,
    ) -> _SignalAssessment:
        bullish_score = 0.0
        bearish_score = 0.0
        evidence: list[str] = []

        if sma_20 is not None:
            price_to_sma20 = self._safe_ratio(latest_bar.close_price - sma_20, sma_20)
            if price_to_sma20 is not None:
                if price_to_sma20 >= 0.01:
                    bullish_score += 0.30
                    evidence.append(
                        f"close is {price_to_sma20:.1%} above the 20-day average"
                    )
                elif price_to_sma20 <= -0.01:
                    bearish_score += 0.30
                    evidence.append(
                        f"close is {abs(price_to_sma20):.1%} below the 20-day average"
                    )
                else:
                    evidence.append("close is trading near the 20-day average")

        ma_stack = self._stack_direction([sma_5, sma_10, sma_20, sma_60])
        if ma_stack == SignalDirection.BULLISH:
            bullish_score += 0.30
            evidence.append("short and medium moving averages are stacked upward")
        elif ma_stack == SignalDirection.BEARISH:
            bearish_score += 0.30
            evidence.append("short and medium moving averages are stacked downward")

        if ema_12 is not None and ema_26 is not None:
            if ema_12 > ema_26:
                bullish_score += 0.18
                evidence.append("12-day EMA remains above the 26-day EMA")
            elif ema_12 < ema_26:
                bearish_score += 0.18
                evidence.append("12-day EMA remains below the 26-day EMA")

        sma_20_slope = self._series_change(sma_20_series, 5)
        if sma_20_slope is not None:
            if sma_20_slope >= 0.01:
                bullish_score += 0.12
                evidence.append(f"20-day average is rising by {sma_20_slope:.1%} over five bars")
            elif sma_20_slope <= -0.01:
                bearish_score += 0.12
                evidence.append(
                    f"20-day average is falling by {abs(sma_20_slope):.1%} over five bars"
                )

        if change_10d is not None:
            if change_10d >= 0.04:
                bullish_score += 0.10
                evidence.append(f"10-bar price change is positive at {change_10d:.1%}")
            elif change_10d <= -0.04:
                bearish_score += 0.10
                evidence.append(f"10-bar price change is negative at {change_10d:.1%}")

        direction = self._resolve_direction(
            bullish_score=bullish_score,
            bearish_score=bearish_score,
        )
        summary = self._summarize_trend(direction=direction)
        return self._assessment(
            name="trend_direction",
            direction=direction,
            bullish_score=bullish_score,
            bearish_score=bearish_score,
            summary=summary,
            evidence=evidence or ("trend is inconclusive with the supplied history",),
            tags=("trend", "direction"),
        )

    def _assess_moving_averages(
        self,
        *,
        latest_close: float,
        sma_5: float | None,
        sma_10: float | None,
        sma_20: float | None,
        sma_60: float | None,
    ) -> _SignalAssessment:
        averages = [
            ("SMA5", sma_5),
            ("SMA10", sma_10),
            ("SMA20", sma_20),
            ("SMA60", sma_60),
        ]
        available_averages = [
            (label, value)
            for label, value in averages
            if value is not None
        ]
        if not available_averages:
            return self._assessment(
                name="moving_averages",
                direction=SignalDirection.NEUTRAL,
                bullish_score=0.0,
                bearish_score=0.0,
                summary="Moving-average alignment is unavailable without enough price history.",
                evidence=("no moving averages could be computed from the supplied bars",),
                tags=("moving-average",),
            )

        above_labels = [
            label
            for label, value in available_averages
            if latest_close > value
        ]
        below_labels = [
            label
            for label, value in available_averages
            if latest_close < value
        ]
        bullish_score = 0.65 * (len(above_labels) / len(available_averages))
        bearish_score = 0.65 * (len(below_labels) / len(available_averages))

        stack_direction = self._stack_direction([value for _, value in available_averages])
        evidence: list[str] = []
        if above_labels:
            evidence.append(f"close is above {', '.join(above_labels)}")
        if below_labels:
            evidence.append(f"close is below {', '.join(below_labels)}")

        if stack_direction == SignalDirection.BULLISH:
            bullish_score += 0.35
            evidence.append("available averages are ordered from shortest to longest in bullish alignment")
        elif stack_direction == SignalDirection.BEARISH:
            bearish_score += 0.35
            evidence.append("available averages are ordered from shortest to longest in bearish alignment")
        else:
            evidence.append("moving averages are not fully aligned")

        direction = self._resolve_direction(
            bullish_score=bullish_score,
            bearish_score=bearish_score,
        )
        if direction == SignalDirection.BULLISH:
            summary = "Price is holding above most moving averages with constructive alignment."
        elif direction == SignalDirection.BEARISH:
            summary = "Price is trading below most moving averages with weak alignment."
        elif direction == SignalDirection.MIXED:
            summary = "Moving averages are mixed, with price caught between support and resistance bands."
        else:
            summary = "Moving averages are flat or compressed without a directional edge."

        return self._assessment(
            name="moving_averages",
            direction=direction,
            bullish_score=bullish_score,
            bearish_score=bearish_score,
            summary=summary,
            evidence=evidence,
            tags=("moving-average", "trend-confirmation"),
        )

    def _assess_momentum(
        self,
        *,
        change_1d: float | None,
        change_5d: float | None,
        change_10d: float | None,
        momentum_acceleration_5d: float | None,
    ) -> _SignalAssessment:
        changes = [
            ("1-bar", change_1d),
            ("5-bar", change_5d),
            ("10-bar", change_10d),
        ]
        available_changes = [
            (label, value)
            for label, value in changes
            if value is not None
        ]
        if not available_changes:
            return self._assessment(
                name="momentum_change",
                direction=SignalDirection.NEUTRAL,
                bullish_score=0.0,
                bearish_score=0.0,
                summary="Momentum cannot be evaluated from a single bar.",
                evidence=("at least two bars are required to calculate price change",),
                tags=("momentum",),
            )

        positive_count = sum(1 for _, value in available_changes if value > 0)
        negative_count = sum(1 for _, value in available_changes if value < 0)
        strongest_magnitude = max(abs(value) for _, value in available_changes)
        magnitude_bonus = min(0.25, strongest_magnitude / 0.12 * 0.25)

        bullish_score = 0.55 * (positive_count / len(available_changes))
        bearish_score = 0.55 * (negative_count / len(available_changes))
        evidence = [
            f"{label} change is {value:.1%}"
            for label, value in available_changes
        ]

        if momentum_acceleration_5d is not None:
            if momentum_acceleration_5d >= 0.02:
                bullish_score += 0.20
                evidence.append(
                    f"5-bar momentum improved by {momentum_acceleration_5d:.1%} versus the prior window"
                )
            elif momentum_acceleration_5d <= -0.02:
                bearish_score += 0.20
                evidence.append(
                    f"5-bar momentum deteriorated by {abs(momentum_acceleration_5d):.1%} versus the prior window"
                )

        if positive_count > negative_count:
            bullish_score += magnitude_bonus
        elif negative_count > positive_count:
            bearish_score += magnitude_bonus

        direction = self._resolve_direction(
            bullish_score=bullish_score,
            bearish_score=bearish_score,
        )
        if direction == SignalDirection.BULLISH:
            summary = "Momentum is strengthening across the available lookback windows."
        elif direction == SignalDirection.BEARISH:
            summary = "Momentum is weakening across the available lookback windows."
        elif direction == SignalDirection.MIXED:
            summary = "Momentum is mixed, suggesting a pullback or early countertrend rebound."
        else:
            summary = "Momentum is flat without a meaningful rate-of-change edge."

        return self._assessment(
            name="momentum_change",
            direction=direction,
            bullish_score=bullish_score,
            bearish_score=bearish_score,
            summary=summary,
            evidence=evidence,
            tags=("momentum", "rate-of-change"),
        )

    def _assess_volume(
        self,
        *,
        latest_bar: MarketBar,
        change_1d: float | None,
        volume_ratio_5d: float | None,
        volume_ratio_20d: float | None,
        trend_direction: SignalDirection,
    ) -> _SignalAssessment:
        ratios = [
            ("5-bar", volume_ratio_5d),
            ("20-bar", volume_ratio_20d),
        ]
        available_ratios = [
            (label, value)
            for label, value in ratios
            if value is not None
        ]
        if not available_ratios:
            return self._assessment(
                name="volume_participation",
                direction=SignalDirection.NEUTRAL,
                bullish_score=0.0,
                bearish_score=0.0,
                summary="Volume participation is unavailable without prior bars.",
                evidence=("at least two bars are required to compare current volume",),
                tags=("volume",),
            )

        representative_ratio = max(value for _, value in available_ratios)
        evidence = [
            f"volume is {value:.2f}x the {label} average"
            for label, value in available_ratios
        ]
        bullish_score = 0.0
        bearish_score = 0.0

        if representative_ratio >= self.STRONG_VOLUME_RATIO:
            if change_1d is not None and change_1d > 0.01:
                bullish_score = 0.85
                evidence.append("strong upside participation confirms the latest advance")
            elif change_1d is not None and change_1d < -0.01:
                bearish_score = 0.85
                evidence.append("heavy turnover on a down move suggests distribution pressure")
            else:
                bullish_score = 0.25
                bearish_score = 0.25
                evidence.append("turnover expanded sharply without a decisive price close")
        elif representative_ratio >= self.EXPANSION_VOLUME_RATIO:
            if change_1d is not None and change_1d > 0:
                bullish_score = 0.65
                evidence.append("volume expansion supports the latest price push")
            elif change_1d is not None and change_1d < 0:
                bearish_score = 0.65
                evidence.append("volume expansion accompanied a negative price session")
            else:
                bullish_score = 0.18
                bearish_score = 0.18
                evidence.append("volume expanded modestly without directional price confirmation")
        elif representative_ratio <= self.CONTRACTION_VOLUME_RATIO:
            if change_1d is not None and change_1d < 0 and trend_direction == SignalDirection.BULLISH:
                bullish_score = 0.45
                evidence.append("the latest pullback happened on lighter volume than recent trading")
            elif change_1d is not None and change_1d > 0 and trend_direction == SignalDirection.BEARISH:
                bearish_score = 0.45
                evidence.append("the rebound lacks broad participation versus recent declines")
            else:
                bullish_score = 0.15
                bearish_score = 0.15
                evidence.append("volume contracted, reducing conviction behind the latest move")
        else:
            bullish_score = 0.15
            bearish_score = 0.15
            evidence.append("volume is close to recent norms")

        direction = self._resolve_direction(
            bullish_score=bullish_score,
            bearish_score=bearish_score,
        )
        if direction == SignalDirection.BULLISH:
            summary = "Volume behavior is supportive of the prevailing bullish move."
        elif direction == SignalDirection.BEARISH:
            summary = "Volume behavior is consistent with bearish pressure or weak demand."
        elif direction == SignalDirection.MIXED:
            summary = "Volume expanded, but the price response was not decisive."
        else:
            summary = "Volume is near normal or contracting, so participation is not directional."

        return self._assessment(
            name="volume_participation",
            direction=direction,
            bullish_score=bullish_score,
            bearish_score=bearish_score,
            summary=summary,
            evidence=evidence,
            tags=("volume", "participation"),
        )

    def _assess_patterns(
        self,
        *,
        latest_bar: MarketBar,
        change_5d: float | None,
        volume_ratio_20d: float | None,
        breakout_level: float | None,
        breakdown_level: float | None,
    ) -> _SignalAssessment:
        bullish_score = 0.0
        bearish_score = 0.0
        evidence: list[str] = []
        tags = {"pattern"}

        if breakout_level is not None and latest_bar.close_price > breakout_level * (
            1 + self.BREAKOUT_BUFFER
        ):
            tags.add("breakout")
            bullish_score += 0.60
            evidence.append(
                f"close cleared the prior breakout level of {breakout_level:.2f}"
            )
            if volume_ratio_20d is not None and volume_ratio_20d >= 1.10:
                bullish_score += 0.15
                evidence.append("the upside break is accompanied by above-average volume")

        if breakdown_level is not None and latest_bar.close_price < breakdown_level * (
            1 - self.BREAKOUT_BUFFER
        ):
            tags.add("breakdown")
            bearish_score += 0.60
            evidence.append(
                f"close broke below the prior support zone near {breakdown_level:.2f}"
            )
            if volume_ratio_20d is not None and volume_ratio_20d >= 1.10:
                bearish_score += 0.15
                evidence.append("the downside break is accompanied by above-average volume")

        bullish_reversal, bearish_reversal = self._reversal_signal(
            latest_bar=latest_bar,
            change_5d=change_5d,
        )
        if bullish_reversal is not None:
            tags.add("reversal")
            bullish_score += bullish_reversal[0]
            evidence.append(bullish_reversal[1])
        if bearish_reversal is not None:
            tags.add("reversal")
            bearish_score += bearish_reversal[0]
            evidence.append(bearish_reversal[1])

        direction = self._resolve_direction(
            bullish_score=bullish_score,
            bearish_score=bearish_score,
        )
        if direction == SignalDirection.BULLISH:
            summary = "Price patterns are constructive, showing breakout or reversal support."
        elif direction == SignalDirection.BEARISH:
            summary = "Price patterns are weak, showing breakdown or reversal risk."
        elif direction == SignalDirection.MIXED:
            summary = "Pattern signals conflict, suggesting a possible false break or unstable reversal."
        else:
            summary = "No decisive breakout or reversal pattern is present in the latest bar."

        return self._assessment(
            name="reversal_breakout",
            direction=direction,
            bullish_score=bullish_score,
            bearish_score=bearish_score,
            summary=summary,
            evidence=evidence or ("latest price action did not trigger a simple breakout or reversal rule",),
            tags=tuple(sorted(tags)),
        )

    def _reversal_signal(
        self,
        *,
        latest_bar: MarketBar,
        change_5d: float | None,
    ) -> tuple[tuple[float, str] | None, tuple[float, str] | None]:
        trading_range = latest_bar.high_price - latest_bar.low_price
        if trading_range <= 0:
            return None, None

        body = abs(latest_bar.close_price - latest_bar.open_price)
        upper_shadow = latest_bar.high_price - max(
            latest_bar.open_price,
            latest_bar.close_price,
        )
        lower_shadow = min(
            latest_bar.open_price,
            latest_bar.close_price,
        ) - latest_bar.low_price
        close_position = (latest_bar.close_price - latest_bar.low_price) / trading_range
        open_position = (latest_bar.open_price - latest_bar.low_price) / trading_range

        bullish_reversal: tuple[float, str] | None = None
        bearish_reversal: tuple[float, str] | None = None

        if (
            change_5d is not None
            and change_5d <= -0.03
            and lower_shadow >= max(body * 2.5, trading_range * 0.45)
            and upper_shadow <= trading_range * 0.25
            and close_position >= 0.60
        ):
            bullish_reversal = (
                0.50,
                "latest candle resembles a hammer after a multi-bar decline",
            )

        if (
            change_5d is not None
            and change_5d >= 0.03
            and upper_shadow >= max(body * 2.5, trading_range * 0.45)
            and lower_shadow <= trading_range * 0.25
            and max(close_position, open_position) <= 0.45
        ):
            bearish_reversal = (
                0.50,
                "latest candle resembles a shooting star after a multi-bar advance",
            )

        return bullish_reversal, bearish_reversal

    def _assessment(
        self,
        *,
        name: str,
        direction: SignalDirection,
        bullish_score: float,
        bearish_score: float,
        summary: str,
        evidence: Sequence[str],
        tags: Sequence[str],
    ) -> _SignalAssessment:
        clamped_bullish = self._clamp_score(bullish_score)
        clamped_bearish = self._clamp_score(bearish_score)
        score = self._signal_score(
            direction=direction,
            bullish_score=clamped_bullish,
            bearish_score=clamped_bearish,
        )
        return _SignalAssessment(
            name=name,
            direction=direction,
            score=score,
            bullish_score=clamped_bullish,
            bearish_score=clamped_bearish,
            summary=summary,
            evidence=tuple(evidence),
            tags=tuple(tags),
        )

    def _summarize_trend(self, *, direction: SignalDirection) -> str:
        if direction == SignalDirection.BULLISH:
            return "Trend direction is bullish across recent bars and moving-average structure."
        if direction == SignalDirection.BEARISH:
            return "Trend direction is bearish across recent bars and moving-average structure."
        if direction == SignalDirection.MIXED:
            return "Trend direction is mixed, with bullish and bearish structure offsetting each other."
        return "Trend direction is neutral because the supplied history does not show a clear slope."

    def _breakout_levels(
        self,
        high_values: Sequence[float],
        low_values: Sequence[float],
    ) -> tuple[float | None, float | None]:
        if len(high_values) < 2 or len(low_values) < 2:
            return None, None

        lookback = min(self.BREAKOUT_LOOKBACK, len(high_values) - 1)
        prior_highs = high_values[-lookback - 1:-1]
        prior_lows = low_values[-lookback - 1:-1]
        return max(prior_highs), min(prior_lows)

    def _stack_direction(self, values: Sequence[float | None]) -> SignalDirection:
        available_values = [value for value in values if value is not None]
        if len(available_values) < 2:
            return SignalDirection.NEUTRAL
        if all(left > right for left, right in zip(available_values, available_values[1:])):
            return SignalDirection.BULLISH
        if all(left < right for left, right in zip(available_values, available_values[1:])):
            return SignalDirection.BEARISH
        return SignalDirection.MIXED

    def _resolve_direction(
        self,
        *,
        bullish_score: float,
        bearish_score: float,
    ) -> SignalDirection:
        dominant_score = max(bullish_score, bearish_score)
        if dominant_score < 0.18:
            return SignalDirection.NEUTRAL
        if bullish_score >= 0.18 and bearish_score >= 0.18 and abs(bullish_score - bearish_score) <= 0.15:
            return SignalDirection.MIXED
        return SignalDirection.BULLISH if bullish_score > bearish_score else SignalDirection.BEARISH

    def _signal_score(
        self,
        *,
        direction: SignalDirection,
        bullish_score: float,
        bearish_score: float,
    ) -> float:
        if direction == SignalDirection.MIXED:
            return round(min(1.0, (bullish_score + bearish_score) / 2), 3)
        if direction == SignalDirection.NEUTRAL:
            return round(max(bullish_score, bearish_score), 3)
        return round(max(bullish_score, bearish_score), 3)

    def _sma_series(self, values: Sequence[float], period: int) -> list[float | None]:
        if period <= 0:
            raise TechnicalAnalysisValidationError("moving-average period must be positive")

        series: list[float | None] = []
        running_sum = 0.0
        for index, value in enumerate(values):
            running_sum += value
            if index >= period:
                running_sum -= values[index - period]
            if index + 1 >= period:
                series.append(running_sum / period)
            else:
                series.append(None)
        return series

    def _ema_series(self, values: Sequence[float], period: int) -> list[float | None]:
        if period <= 0:
            raise TechnicalAnalysisValidationError("EMA period must be positive")

        if len(values) < period:
            return [None] * len(values)

        multiplier = 2 / (period + 1)
        seed = mean(values[:period])
        series: list[float | None] = [None] * (period - 1)
        previous_ema = seed
        series.append(previous_ema)
        for value in values[period:]:
            previous_ema = ((value - previous_ema) * multiplier) + previous_ema
            series.append(previous_ema)
        return series

    def _percent_change(self, values: Sequence[float], lookback: int) -> float | None:
        if lookback <= 0 or len(values) <= lookback:
            return None
        base_value = values[-lookback - 1]
        if base_value <= 0:
            return None
        return (values[-1] / base_value) - 1

    def _momentum_acceleration(self, values: Sequence[float], lookback: int) -> float | None:
        current_change = self._percent_change(values, lookback)
        if current_change is None or len(values) <= lookback + 1:
            return None

        previous_end_index = len(values) - 2
        previous_base_index = previous_end_index - lookback
        if previous_base_index < 0:
            return None

        previous_base = values[previous_base_index]
        if previous_base <= 0:
            return None
        previous_change = (values[previous_end_index] / previous_base) - 1
        return current_change - previous_change

    def _ratio_to_previous_average(self, values: Sequence[float], lookback: int) -> float | None:
        if len(values) < 2:
            return None
        prior_values = values[max(0, len(values) - lookback - 1):-1]
        if not prior_values:
            return None
        baseline = mean(prior_values)
        if baseline <= 0:
            return None
        return values[-1] / baseline

    def _series_change(self, values: Sequence[float | None], lookback: int) -> float | None:
        if len(values) <= lookback:
            return None
        current_value = values[-1]
        previous_value = values[-lookback - 1]
        if current_value is None or previous_value is None or previous_value <= 0:
            return None
        return (current_value / previous_value) - 1

    def _safe_ratio(self, numerator: float, denominator: float | None) -> float | None:
        if denominator is None or denominator == 0:
            return None
        return numerator / denominator

    def _clamp_score(self, value: float) -> float:
        return round(max(0.0, min(value, 1.0)), 3)

    def _first_non_zero(self, *values: float | None) -> float | None:
        for value in values:
            if value is not None and value != 0:
                return value
        return None

    def _value_or_none(self, values: Sequence[object], index: int) -> object | None:
        try:
            return values[index]
        except IndexError:
            return None


def build_default_technical_analysis_service() -> TechnicalAnalysisService:
    return TechnicalAnalysisService()
