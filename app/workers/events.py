from __future__ import annotations

import argparse
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.persistence import MarketEventRepository, init_database
from app.workers.runtime import format_worker_log, install_shutdown_handlers, run_loop

DEFAULT_INTERVAL_SECONDS = 1800


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone market event worker.")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.getenv("TRADER_EVENT_WORKER_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)),
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
    )
    return parser


def _collect_events() -> list[dict[str, object]]:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.market_timezone))
    events: list[dict[str, object]] = []

    if now.day >= 25:
        events.append(
            {
                "symbol": None,
                "title": "月末资金再平衡窗口",
                "event_type": "rebalance_window",
                "severity": "medium",
                "event_date": now.date().isoformat(),
                "source": "event_worker",
                "details": {"rule": "month_end_rebalance"},
            }
        )

    if now.month in {1, 4, 7, 10}:
        events.append(
            {
                "symbol": None,
                "title": "财报 / 业绩预告季",
                "event_type": "earnings_window",
                "severity": "high",
                "event_date": now.date().isoformat(),
                "source": "event_worker",
                "details": {"rule": "quarterly_earnings_window"},
            }
        )

    if now.weekday() >= 3:
        events.append(
            {
                "symbol": None,
                "title": "临近周末风险窗口",
                "event_type": "weekend_risk_window",
                "severity": "medium",
                "event_date": now.date().isoformat(),
                "source": "event_worker",
                "details": {"rule": "weekend_risk_window"},
            }
        )

    if now.weekday() == 0:
        events.append(
            {
                "symbol": None,
                "title": "周初重新定价",
                "event_type": "weekly_repricing",
                "severity": "low",
                "event_date": now.date().isoformat(),
                "source": "event_worker",
                "details": {"rule": "weekly_repricing"},
            }
        )

    return events


def _run_once() -> dict[str, object]:
    settings = get_settings()
    database = init_database(settings.database_path)
    repository = MarketEventRepository(database)
    events = _collect_events()
    for event in events:
        repository.upsert_event(**event)
    return {
        "event_count": len(events),
        "event_types": [event["event_type"] for event in events],
        "tick_at": datetime.now(ZoneInfo(settings.market_timezone)).strftime("%Y-%m-%d %H:%M:%S"),
    }


def main() -> int:
    args = build_parser().parse_args()
    if args.run_once:
        print(format_worker_log("worker.heartbeat", worker="events", **_run_once()), flush=True)
        return 0

    stop_event = threading.Event()
    install_shutdown_handlers(stop_event)
    return run_loop(
        worker_name="events",
        interval_seconds=args.interval_seconds,
        stop_event=stop_event,
        tick=lambda _iteration: _run_once(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
