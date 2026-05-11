from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    return int(raw_value)


def _read_str(name: str, default: str) -> str:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    return raw_value.strip() or default


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = os.getenv("TRADER_APP_NAME", "Trader")
    environment: str = os.getenv("TRADER_ENV", "development")
    debug: bool = _read_bool("TRADER_DEBUG", True)
    database_path: str = os.getenv("TRADER_DATABASE_PATH", "instance/trader.db")
    market_timezone: str = _read_str("TRADER_MARKET_TIMEZONE", "Asia/Shanghai")
    market_open_am_start: str = _read_str("TRADER_MARKET_OPEN_AM_START", "09:30")
    market_open_am_end: str = _read_str("TRADER_MARKET_OPEN_AM_END", "11:30")
    market_open_pm_start: str = _read_str("TRADER_MARKET_OPEN_PM_START", "13:00")
    market_open_pm_end: str = _read_str("TRADER_MARKET_OPEN_PM_END", "15:00")
    market_cache_ttl_seconds: int = _read_int("TRADER_MARKET_CACHE_TTL_SECONDS", 60)
    sentiment_cache_ttl_seconds: int = _read_int("TRADER_SENTIMENT_CACHE_TTL_SECONDS", 300)
    recommendation_cache_ttl_seconds: int = _read_int("TRADER_RECOMMENDATION_CACHE_TTL_SECONDS", 120)
    enable_sentiment_ingestion: bool = _read_bool("TRADER_ENABLE_SENTIMENT", True)
    enable_trader_agent: bool = _read_bool("TRADER_ENABLE_TRADER_AGENT", True)
    enable_recommendation_engine: bool = _read_bool("TRADER_ENABLE_RECOMMENDATION_ENGINE", True)

    def to_dict(self) -> dict[str, object]:
        return {
            "app_name": self.app_name,
            "environment": self.environment,
            "debug": self.debug,
            "database_path": self.database_path,
            "market_timezone": self.market_timezone,
            "market_open_am_start": self.market_open_am_start,
            "market_open_am_end": self.market_open_am_end,
            "market_open_pm_start": self.market_open_pm_start,
            "market_open_pm_end": self.market_open_pm_end,
            "market_cache_ttl_seconds": self.market_cache_ttl_seconds,
            "sentiment_cache_ttl_seconds": self.sentiment_cache_ttl_seconds,
            "recommendation_cache_ttl_seconds": self.recommendation_cache_ttl_seconds,
            "enable_sentiment_ingestion": self.enable_sentiment_ingestion,
            "enable_trader_agent": self.enable_trader_agent,
            "enable_recommendation_engine": self.enable_recommendation_engine,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
