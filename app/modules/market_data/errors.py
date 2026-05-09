from __future__ import annotations

from collections.abc import Mapping


class MarketDataError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "market_data_error",
        retryable: bool = False,
        details: Mapping[str, object] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = dict(details or {})
        if cause is not None:
            self.__cause__ = cause


class MarketDataUnavailableError(MarketDataError):
    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(
            message,
            code="market_data_unavailable",
            retryable=True,
            details=details,
            cause=cause,
        )


class MarketDataNotFoundError(MarketDataError):
    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ):
        super().__init__(
            message,
            code="market_data_not_found",
            details=details,
        )


class MarketDataNormalizationError(MarketDataError):
    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(
            message,
            code="market_data_normalization_failed",
            details=details,
            cause=cause,
        )


class MarketDataValidationError(MarketDataError):
    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ):
        super().__init__(
            message,
            code="market_data_validation_failed",
            details=details,
        )
