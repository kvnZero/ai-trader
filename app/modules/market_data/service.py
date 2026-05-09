from __future__ import annotations

from datetime import date, timedelta

from app.domain import CompanyReference, MarketBar, MarketSnapshot
from app.modules.market_data.adapters import AKShareMarketDataAdapter, MarketDataAdapter
from app.modules.market_data.contracts import MarketDataIssue, MarketDataResult
from app.modules.market_data.errors import (
    MarketDataError,
    MarketDataUnavailableError,
    MarketDataValidationError,
)
from app.modules.market_data.fallbacks import get_fallback_stock_sample


class MarketDataService:
    DEFAULT_SAMPLE_LIMIT = 8
    DEFAULT_HISTORY_WINDOW_DAYS = 120

    def __init__(self, adapter: MarketDataAdapter | None = None):
        self.adapter = adapter or AKShareMarketDataAdapter()

    def get_stock_list_sample(
        self,
        *,
        limit: int = DEFAULT_SAMPLE_LIMIT,
    ) -> MarketDataResult[list[CompanyReference]]:
        if limit <= 0:
            return self._result_with_issue(
                data=[],
                error=MarketDataValidationError("stock list sample limit must be positive"),
                fallback_used=True,
            )

        try:
            sample = self.adapter.fetch_stock_list_sample(limit=limit)
        except Exception as exc:
            return self._result_with_issue(
                data=get_fallback_stock_sample(limit=limit),
                error=self._coerce_error(exc, action="stock list sample"),
                fallback_used=True,
            )

        return MarketDataResult(data=sample, source=self.adapter.source_name)

    def get_latest_snapshot(self, symbol: str) -> MarketDataResult[MarketSnapshot | None]:
        try:
            snapshot = self.adapter.fetch_latest_snapshot(symbol)
        except Exception as exc:
            return self._result_with_issue(
                data=None,
                error=self._coerce_error(exc, action="latest market snapshot"),
                fallback_used=True,
            )

        return MarketDataResult(data=snapshot, source=self.adapter.source_name)

    def get_daily_bars(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        adjust: str = "",
        limit: int | None = None,
    ) -> MarketDataResult[list[MarketBar]]:
        if limit is not None and limit <= 0:
            return self._result_with_issue(
                data=[],
                error=MarketDataValidationError("historical bar limit must be positive when provided"),
                fallback_used=True,
            )

        resolved_end_date = end_date or date.today()
        resolved_start_date = start_date or (
            resolved_end_date - timedelta(days=self.DEFAULT_HISTORY_WINDOW_DAYS)
        )
        if resolved_start_date > resolved_end_date:
            return self._result_with_issue(
                data=[],
                error=MarketDataValidationError(
                    "historical bar start_date must not be after end_date",
                    details={
                        "start_date": resolved_start_date.isoformat(),
                        "end_date": resolved_end_date.isoformat(),
                    },
                ),
                fallback_used=True,
            )

        try:
            bars = self.adapter.fetch_daily_bars(
                symbol,
                start_date=resolved_start_date,
                end_date=resolved_end_date,
                adjust=adjust,
            )
        except Exception as exc:
            return self._result_with_issue(
                data=[],
                error=self._coerce_error(exc, action="historical daily bars"),
                fallback_used=True,
            )

        if limit is not None:
            bars = bars[-limit:]
        return MarketDataResult(data=bars, source=self.adapter.source_name)

    def _coerce_error(self, exc: Exception, *, action: str) -> MarketDataError:
        if isinstance(exc, MarketDataError):
            return exc
        return MarketDataUnavailableError(
            f"unexpected error while fetching {action}",
            details={"action": action},
            cause=exc,
        )

    def _result_with_issue(
        self,
        *,
        data: object,
        error: MarketDataError,
        fallback_used: bool,
    ) -> MarketDataResult[object]:
        return MarketDataResult(
            data=data,
            source=self.adapter.source_name,
            fallback_used=fallback_used,
            issues=(
                MarketDataIssue(
                    code=error.code,
                    message=str(error),
                    retryable=error.retryable,
                    details=dict(error.details),
                ),
            ),
        )


def build_default_market_data_service() -> MarketDataService:
    return MarketDataService(adapter=AKShareMarketDataAdapter())
