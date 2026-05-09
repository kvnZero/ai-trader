from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
import re
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd

from app.domain import CompanyReference, MarketBar, MarketSnapshot
from app.modules.market_data.errors import (
    MarketDataNormalizationError,
    MarketDataNotFoundError,
    MarketDataUnavailableError,
    MarketDataValidationError,
)

_MARKET_TZ = ZoneInfo("Asia/Shanghai")
_SYMBOL_PATTERN = re.compile(r"(\d{6})")
_SSE_PREFIXES = ("5", "6", "9")
_SZSE_PREFIXES = ("0", "2", "3")
_BSE_PREFIXES = ("4", "8")
_STOCK_CODE_COLUMNS = ("code", "代码", "证券代码", "A股代码", "股票代码")
_STOCK_NAME_COLUMNS = ("name", "名称", "证券简称", "A股简称", "股票简称")
_SNAPSHOT_LAST_PRICE_COLUMNS = ("最新价", "last_price", "最新", "现价")
_SNAPSHOT_CHANGE_PERCENT_COLUMNS = ("涨跌幅", "change_percent", "涨幅")
_SNAPSHOT_VOLUME_COLUMNS = ("成交量", "volume")
_SNAPSHOT_TURNOVER_COLUMNS = ("成交额", "turnover")
_SNAPSHOT_CAPTURED_AT_COLUMNS = ("更新时间", "时间", "日期时间")
_BAR_DATE_COLUMNS = ("日期", "date", "交易日期")
_BAR_OPEN_COLUMNS = ("开盘", "open")
_BAR_HIGH_COLUMNS = ("最高", "high")
_BAR_LOW_COLUMNS = ("最低", "low")
_BAR_CLOSE_COLUMNS = ("收盘", "close")
_BAR_VOLUME_COLUMNS = ("成交量", "volume")
_BAR_TURNOVER_COLUMNS = ("成交额", "turnover")
_BAR_AMPLITUDE_COLUMNS = ("振幅", "amplitude")
_BAR_CHANGE_PERCENT_COLUMNS = ("涨跌幅", "change_percent")


class MarketDataAdapter(Protocol):
    source_name: str

    def fetch_stock_list_sample(self, *, limit: int) -> list[CompanyReference]:
        ...

    def fetch_latest_snapshot(self, symbol: str) -> MarketSnapshot:
        ...

    def fetch_daily_bars(
        self,
        symbol: str,
        *,
        start_date: date,
        end_date: date,
        adjust: str = "",
    ) -> list[MarketBar]:
        ...


class AKShareMarketDataAdapter:
    source_name = "akshare"

    def __init__(self, *, clock: Callable[[], datetime] | None = None):
        self._clock = clock or _current_market_time

    def fetch_stock_list_sample(self, *, limit: int) -> list[CompanyReference]:
        if limit <= 0:
            raise MarketDataValidationError("stock list sample limit must be positive")

        frame = self._execute_query("stock list sample", ak.stock_info_a_code_name)
        references: list[CompanyReference] = []

        for row in frame.to_dict("records"):
            symbol = _extract_symbol(row, _STOCK_CODE_COLUMNS)
            name = _extract_string(row, _STOCK_NAME_COLUMNS)
            if not symbol or not name:
                continue

            references.append(
                CompanyReference(
                    symbol=symbol,
                    company_name=name,
                    exchange=_infer_exchange(symbol),
                )
            )
            if len(references) >= limit:
                break

        if not references:
            raise MarketDataNormalizationError(
                "AKShare stock list sample could not be normalized",
                details={"operation": "stock_info_a_code_name"},
            )
        return references

    def fetch_latest_snapshot(self, symbol: str) -> MarketSnapshot:
        normalized_symbol = normalize_symbol(symbol)
        frame = self._execute_query("latest market snapshot", ak.stock_zh_a_spot_em)

        row = _find_row_for_symbol(frame, normalized_symbol)
        if row is None:
            raise MarketDataNotFoundError(
                f"no market snapshot found for symbol {normalized_symbol}",
                details={"symbol": normalized_symbol},
            )

        captured_at = _extract_datetime(row, _SNAPSHOT_CAPTURED_AT_COLUMNS) or self._clock()
        return MarketSnapshot(
            symbol=normalized_symbol,
            name=_require_string(row, _STOCK_NAME_COLUMNS, "snapshot name", normalized_symbol),
            last_price=_require_float(
                row,
                _SNAPSHOT_LAST_PRICE_COLUMNS,
                "snapshot last price",
                normalized_symbol,
            ),
            change_percent=_require_float(
                row,
                _SNAPSHOT_CHANGE_PERCENT_COLUMNS,
                "snapshot change percent",
                normalized_symbol,
            ),
            volume=_require_float(
                row,
                _SNAPSHOT_VOLUME_COLUMNS,
                "snapshot volume",
                normalized_symbol,
            ),
            turnover=_optional_float(row, _SNAPSHOT_TURNOVER_COLUMNS, normalized_symbol),
            captured_at=captured_at,
        )

    def fetch_daily_bars(
        self,
        symbol: str,
        *,
        start_date: date,
        end_date: date,
        adjust: str = "",
    ) -> list[MarketBar]:
        normalized_symbol = normalize_symbol(symbol)
        if start_date > end_date:
            raise MarketDataValidationError(
                "historical bar start_date must not be after end_date",
                details={
                    "symbol": normalized_symbol,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
            )

        frame = self._execute_query(
            "daily bar history",
            lambda: ak.stock_zh_a_hist(
                symbol=normalized_symbol,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust=adjust,
            ),
            allow_empty=True,
        )
        if frame.empty:
            raise MarketDataNotFoundError(
                f"no daily bars found for symbol {normalized_symbol}",
                details={
                    "symbol": normalized_symbol,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "adjust": adjust,
                },
            )

        bars: list[MarketBar] = []
        for row in frame.to_dict("records"):
            trade_date = _require_date(row, _BAR_DATE_COLUMNS, "bar trade date", normalized_symbol)
            bars.append(
                MarketBar(
                    symbol=normalized_symbol,
                    trade_date=trade_date,
                    open_price=_require_float(row, _BAR_OPEN_COLUMNS, "bar open price", normalized_symbol),
                    high_price=_require_float(row, _BAR_HIGH_COLUMNS, "bar high price", normalized_symbol),
                    low_price=_require_float(row, _BAR_LOW_COLUMNS, "bar low price", normalized_symbol),
                    close_price=_require_float(row, _BAR_CLOSE_COLUMNS, "bar close price", normalized_symbol),
                    volume=_require_float(row, _BAR_VOLUME_COLUMNS, "bar volume", normalized_symbol),
                    turnover=_optional_float(row, _BAR_TURNOVER_COLUMNS, normalized_symbol),
                    amplitude=_optional_float(row, _BAR_AMPLITUDE_COLUMNS, normalized_symbol),
                    change_percent=_optional_float(row, _BAR_CHANGE_PERCENT_COLUMNS, normalized_symbol),
                )
            )

        bars.sort(key=lambda bar: bar.trade_date)
        return bars

    def _execute_query(
        self,
        operation: str,
        fetcher: Callable[[], pd.DataFrame],
        *,
        allow_empty: bool = False,
    ) -> pd.DataFrame:
        try:
            frame = fetcher()
        except Exception as exc:
            raise MarketDataUnavailableError(
                f"AKShare request failed for {operation}",
                details={"operation": operation},
                cause=exc,
            ) from exc

        if not isinstance(frame, pd.DataFrame):
            raise MarketDataNormalizationError(
                "AKShare response was not a pandas DataFrame",
                details={"operation": operation, "type": type(frame).__name__},
            )
        if frame.empty and not allow_empty:
            raise MarketDataUnavailableError(
                f"AKShare returned no rows for {operation}",
                details={"operation": operation},
            )
        return frame


def normalize_symbol(symbol: str) -> str:
    raw = str(symbol).strip()
    if not raw:
        raise MarketDataValidationError("symbol must not be empty")

    match = _SYMBOL_PATTERN.search(raw)
    if match:
        return match.group(1)

    digits = "".join(character for character in raw if character.isdigit())
    if 1 <= len(digits) <= 6:
        return digits.zfill(6)

    raise MarketDataValidationError(
        f"symbol '{symbol}' is not a valid A-share stock code",
        details={"symbol": raw},
    )


def _current_market_time() -> datetime:
    return datetime.now(tz=_MARKET_TZ)


def _find_row_for_symbol(frame: pd.DataFrame, symbol: str) -> dict[str, Any] | None:
    for row in frame.to_dict("records"):
        try:
            row_symbol = _extract_symbol(row, _STOCK_CODE_COLUMNS)
        except MarketDataValidationError:
            continue
        if row_symbol == symbol:
            return row
    return None


def _extract_symbol(row: dict[str, Any], candidates: tuple[str, ...]) -> str:
    value = _pick_value(row, candidates)
    if value is None:
        raise MarketDataValidationError("stock code column is missing")
    return normalize_symbol(_stringify_symbol(value))


def _extract_string(row: dict[str, Any], candidates: tuple[str, ...]) -> str | None:
    value = _pick_value(row, candidates)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_string(
    row: dict[str, Any],
    candidates: tuple[str, ...],
    field_name: str,
    symbol: str,
) -> str:
    value = _extract_string(row, candidates)
    if value is None:
        raise MarketDataNormalizationError(
            f"{field_name} is missing from AKShare data",
            details={"symbol": symbol, "field": field_name},
        )
    return value


def _optional_float(row: dict[str, Any], candidates: tuple[str, ...], symbol: str) -> float | None:
    value = _pick_value(row, candidates)
    if value is None:
        return None
    return _coerce_float(value, symbol=symbol, field_name="/".join(candidates))


def _require_float(
    row: dict[str, Any],
    candidates: tuple[str, ...],
    field_name: str,
    symbol: str,
) -> float:
    value = _pick_value(row, candidates)
    if value is None:
        raise MarketDataNormalizationError(
            f"{field_name} is missing from AKShare data",
            details={"symbol": symbol, "field": field_name},
        )
    return _coerce_float(value, symbol=symbol, field_name=field_name)


def _require_date(
    row: dict[str, Any],
    candidates: tuple[str, ...],
    field_name: str,
    symbol: str,
) -> date:
    value = _pick_value(row, candidates)
    if value is None:
        raise MarketDataNormalizationError(
            f"{field_name} is missing from AKShare data",
            details={"symbol": symbol, "field": field_name},
        )

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue

    raise MarketDataNormalizationError(
        f"{field_name} could not be parsed as a date",
        details={"symbol": symbol, "field": field_name, "value": value},
    )


def _extract_datetime(row: dict[str, Any], candidates: tuple[str, ...]) -> datetime | None:
    value = _pick_value(row, candidates)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=_MARKET_TZ)
    if isinstance(value, str):
        text = value.strip()
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M",
        ):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=_MARKET_TZ)
            except ValueError:
                continue
    return None


def _coerce_float(value: Any, *, symbol: str, field_name: str) -> float:
    try:
        if isinstance(value, str):
            normalized = value.replace(",", "").replace("%", "").strip()
            if not normalized:
                raise ValueError("empty string")
            return float(normalized)
        return float(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataNormalizationError(
            f"{field_name} could not be parsed as a float",
            details={"symbol": symbol, "field": field_name, "value": value},
            cause=exc,
        ) from exc


def _pick_value(row: dict[str, Any], candidates: tuple[str, ...]) -> Any | None:
    for candidate in candidates:
        if candidate not in row:
            continue
        value = row[candidate]
        if value is None or pd.isna(value):
            continue
        return value
    return None


def _stringify_symbol(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return f"{value:06d}"
    if isinstance(value, float):
        if pd.isna(value):
            return ""
        return f"{int(value):06d}"
    return str(value)


def _infer_exchange(symbol: str) -> str:
    if symbol.startswith(_SSE_PREFIXES):
        return "SSE"
    if symbol.startswith(_SZSE_PREFIXES):
        return "SZSE"
    if symbol.startswith(_BSE_PREFIXES):
        return "BSE"
    return "SZSE/SSE"
