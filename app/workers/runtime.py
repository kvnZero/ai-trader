from __future__ import annotations

import json
import os
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings, get_settings
from app.monitoring import MarketHoursMonitoringScheduler, WatchlistRefreshService
from app.persistence import (
    AlertRepository,
    RecommendationEventRepository,
    RecommendationSnapshotRepository,
    SentimentRepository,
    WatchlistRepository,
    init_database,
)

_EMBEDDED_MONITORING_ENV = "TRADER_ENABLE_EMBEDDED_MONITORING"


@dataclass(frozen=True, slots=True)
class WorkerRuntime:
    settings: Settings
    watchlist_repository: WatchlistRepository
    alert_repository: AlertRepository
    recommendation_event_repository: RecommendationEventRepository
    refresh_service: WatchlistRefreshService


class InactiveMonitoringScheduler:
    """Status-compatible placeholder when monitoring runs outside the web process."""

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def status_snapshot(self) -> dict[str, object]:
        return {
            "has_tick": False,
            "tick_at": None,
            "market_open": None,
            "processed_symbols": [],
        }


def embedded_monitoring_enabled() -> bool:
    raw_value = os.getenv(_EMBEDDED_MONITORING_ENV)
    if raw_value is None:
        return True
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def build_worker_runtime(*, settings: Settings | None = None) -> WorkerRuntime:
    resolved_settings = settings or get_settings()
    database = init_database(resolved_settings.database_path)
    watchlist_repository = WatchlistRepository(database)
    alert_repository = AlertRepository(database)
    recommendation_event_repository = RecommendationEventRepository(database)
    recommendation_snapshot_repository = RecommendationSnapshotRepository(database)
    sentiment_repository = SentimentRepository(database)
    refresh_service = WatchlistRefreshService(
        settings=resolved_settings,
        watchlist_repository=watchlist_repository,
        alert_repository=alert_repository,
        recommendation_event_repository=recommendation_event_repository,
        recommendation_snapshot_repository=recommendation_snapshot_repository,
        sentiment_cache_reader=sentiment_repository,
    )

    watchlist_repository.seed_defaults()
    alert_repository.seed_defaults()

    return WorkerRuntime(
        settings=resolved_settings,
        watchlist_repository=watchlist_repository,
        alert_repository=alert_repository,
        recommendation_event_repository=recommendation_event_repository,
        refresh_service=refresh_service,
    )


def build_monitoring_scheduler(
    *,
    settings: Settings | None = None,
    interval_seconds: int = 300,
) -> tuple[WorkerRuntime, MarketHoursMonitoringScheduler]:
    runtime = build_worker_runtime(settings=settings)
    scheduler = MarketHoursMonitoringScheduler(
        settings=runtime.settings,
        refresh_service=runtime.refresh_service,
        interval_seconds=interval_seconds,
    )
    return runtime, scheduler


def install_shutdown_handlers(stop_event: threading.Event) -> None:
    def _handle_shutdown(signum: int, _frame: object) -> None:
        print(
            format_worker_log(
                "worker.signal",
                signal=signal.Signals(signum).name,
                action="shutdown_requested",
            ),
            flush=True,
        )
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _handle_shutdown)


def format_worker_log(event: str, **fields: object) -> str:
    payload = {"event": event, **fields}
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def now_label(timezone_name: str) -> str:
    timezone = ZoneInfo(timezone_name)
    return datetime.now(timezone).strftime("%Y-%m-%d %H:%M:%S %Z")


def run_loop(
    *,
    worker_name: str,
    interval_seconds: int,
    stop_event: threading.Event,
    tick: Callable[[int], dict[str, object]],
) -> int:
    print(
        format_worker_log(
            "worker.started",
            worker=worker_name,
            interval_seconds=interval_seconds,
        ),
        flush=True,
    )
    iteration = 0
    while not stop_event.is_set():
        iteration += 1
        try:
            payload = tick(iteration)
            print(
                format_worker_log(
                    "worker.heartbeat",
                    worker=worker_name,
                    iteration=iteration,
                    interval_seconds=interval_seconds,
                    **payload,
                ),
                flush=True,
            )
        except Exception as exc:
            print(
                format_worker_log(
                    "worker.error",
                    worker=worker_name,
                    iteration=iteration,
                    interval_seconds=interval_seconds,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                ),
                flush=True,
            )
        if stop_event.wait(interval_seconds):
            break

    print(
        format_worker_log(
            "worker.stopped",
            worker=worker_name,
            iterations=iteration,
        ),
        flush=True,
    )
    return 0
