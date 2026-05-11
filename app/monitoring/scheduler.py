from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.monitoring.refresh import WatchlistRefreshService


@dataclass(frozen=True, slots=True)
class MonitoringTickResult:
    processed_symbols: list[str]
    market_open: bool
    tick_at: str


class MarketHoursMonitoringScheduler:
    def __init__(
        self,
        *,
        settings: Settings,
        refresh_service: WatchlistRefreshService,
        interval_seconds: int = 300,
    ):
        self.settings = settings
        self.refresh_service = refresh_service
        self.interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_tick: MonitoringTickResult | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="market-hours-monitoring", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def run_once(self) -> MonitoringTickResult:
        timezone = ZoneInfo(self.settings.market_timezone)
        now = datetime.now(timezone)
        market_open = self._is_market_open(now)
        processed_symbols: list[str] = []
        if market_open:
            outcomes = self.refresh_service.refresh_enabled(source="scheduled")
            processed_symbols = [outcome.symbol for outcome in outcomes]
        result = MonitoringTickResult(
            processed_symbols=processed_symbols,
            market_open=market_open,
            tick_at=now.strftime("%Y-%m-%d %H:%M"),
        )
        self._last_tick = result
        return result

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            self._stop_event.wait(self.interval_seconds)

    def _is_market_open(self, now: datetime) -> bool:
        if now.weekday() >= 5:
            return False

        am_start = self._parse_time(self.settings.market_open_am_start)
        am_end = self._parse_time(self.settings.market_open_am_end)
        pm_start = self._parse_time(self.settings.market_open_pm_start)
        pm_end = self._parse_time(self.settings.market_open_pm_end)
        current = now.time()
        return (am_start <= current <= am_end) or (pm_start <= current <= pm_end)

    def _parse_time(self, value: str) -> dtime:
        return datetime.strptime(value, "%H:%M").time()

    def status_snapshot(self) -> dict[str, object]:
        tick = self._last_tick
        if tick is None:
            return {
                "has_tick": False,
                "tick_at": None,
                "market_open": None,
                "processed_symbols": [],
            }

        return {
            "has_tick": True,
            "tick_at": tick.tick_at,
            "market_open": tick.market_open,
            "processed_symbols": list(tick.processed_symbols),
        }
