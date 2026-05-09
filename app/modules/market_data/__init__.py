"""Independent market data capability package."""

from app.modules.market_data.adapters import AKShareMarketDataAdapter, MarketDataAdapter
from app.modules.market_data.contracts import MarketDataIssue, MarketDataResult
from app.modules.market_data.errors import (
    MarketDataError,
    MarketDataNormalizationError,
    MarketDataNotFoundError,
    MarketDataUnavailableError,
    MarketDataValidationError,
)
from app.modules.market_data.service import (
    MarketDataService,
    build_default_market_data_service,
)

__all__ = [
    "AKShareMarketDataAdapter",
    "MarketDataAdapter",
    "MarketDataError",
    "MarketDataIssue",
    "MarketDataNormalizationError",
    "MarketDataNotFoundError",
    "MarketDataResult",
    "MarketDataService",
    "MarketDataUnavailableError",
    "MarketDataValidationError",
    "build_default_market_data_service",
]
