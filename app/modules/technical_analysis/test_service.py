from __future__ import annotations

from datetime import date, timedelta
import unittest

from app.domain import MarketBar
from app.modules.technical_analysis import MarketRegime, TechnicalAnalysisService


def _build_bars(
    closes: list[float],
    *,
    symbol: str = "000001",
    volumes: list[float] | None = None,
    overrides: dict[int, dict[str, float]] | None = None,
) -> list[MarketBar]:
    bars: list[MarketBar] = []
    for index, close_price in enumerate(closes):
        previous_close = closes[index - 1] if index > 0 else close_price
        upward_bias = close_price >= previous_close
        open_price = close_price * (0.996 if upward_bias else 1.004)
        high_price = max(open_price, close_price) * 1.006
        low_price = min(open_price, close_price) * 0.994
        volume = volumes[index] if volumes is not None else 1000.0

        if overrides and index in overrides:
            override = overrides[index]
            open_price = override.get("open_price", open_price)
            high_price = override.get("high_price", high_price)
            low_price = override.get("low_price", low_price)
            volume = override.get("volume", volume)
            close_price = override.get("close_price", close_price)

        bars.append(
            MarketBar(
                symbol=symbol,
                trade_date=date(2024, 1, 1) + timedelta(days=index),
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=volume,
            )
        )
    return bars


class TechnicalAnalysisServiceRegimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = TechnicalAnalysisService()

    def test_detects_trend_regime(self) -> None:
        closes = [50 + (index * 0.5) for index in range(60)]
        bars = _build_bars(closes)

        result = self.service.analyze_bars(bars)

        self.assertEqual(result.market_regime, MarketRegime.TREND.value)
        self.assertEqual(result.market_regime_assessment.regime, MarketRegime.TREND)
        self.assertGreater(result.confirmation_score, 0.55)

    def test_detects_range_regime(self) -> None:
        closes = [
            100.0 + (0.25 if index % 2 == 0 else -0.25)
            for index in range(60)
        ]
        bars = _build_bars(closes)

        result = self.service.analyze_bars(bars)

        self.assertEqual(result.market_regime, MarketRegime.RANGE.value)
        self.assertEqual(result.market_regime_assessment.regime, MarketRegime.RANGE)
        self.assertGreater(result.confirmation_score, 0.2)

    def test_detects_panic_regime(self) -> None:
        closes = [100.0] * 54 + [98.0, 96.0, 94.0, 91.0, 88.0, 84.0]
        volumes = [1000.0] * 59 + [6000.0]
        bars = _build_bars(
            closes,
            volumes=volumes,
            overrides={
                59: {
                    "open_price": 90.0,
                    "high_price": 91.0,
                    "low_price": 82.0,
                    "close_price": 84.0,
                    "volume": 6000.0,
                }
            },
        )

        result = self.service.analyze_bars(bars)

        self.assertEqual(result.market_regime, MarketRegime.PANIC.value)
        self.assertEqual(result.market_regime_assessment.regime, MarketRegime.PANIC)
        self.assertGreater(result.confirmation_score, 0.45)

    def test_detects_rebound_regime(self) -> None:
        closes = [100.0] * 54 + [98.0, 96.0, 94.0, 92.0, 90.0, 92.0]
        volumes = [1000.0] * 59 + [4500.0]
        bars = _build_bars(
            closes,
            volumes=volumes,
            overrides={
                59: {
                    "open_price": 89.0,
                    "high_price": 93.0,
                    "low_price": 80.0,
                    "close_price": 92.0,
                    "volume": 4500.0,
                }
            },
        )

        result = self.service.analyze_bars(bars)

        self.assertEqual(result.market_regime, MarketRegime.REBOUND.value)
        self.assertEqual(result.market_regime_assessment.regime, MarketRegime.REBOUND)
        self.assertGreater(result.confirmation_score, 0.45)


if __name__ == "__main__":
    unittest.main()
