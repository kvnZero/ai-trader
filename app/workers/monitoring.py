from __future__ import annotations

import argparse
import os
import threading

from app.workers.runtime import (
    build_monitoring_scheduler,
    format_worker_log,
    install_shutdown_handlers,
    now_label,
    run_loop,
)

DEFAULT_INTERVAL_SECONDS = 300


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone monitoring worker.")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.getenv("TRADER_MONITORING_WORKER_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)),
        help="Polling interval for monitoring refresh cycles.",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Execute a single monitoring tick and exit.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    runtime, scheduler = build_monitoring_scheduler(interval_seconds=args.interval_seconds)

    if args.run_once:
        result = scheduler.run_once()
        print(
            format_worker_log(
                "worker.heartbeat",
                worker="monitoring",
                interval_seconds=args.interval_seconds,
                tick_at=result.tick_at,
                market_open=result.market_open,
                processed_symbols=result.processed_symbols,
                processed_count=len(result.processed_symbols),
                timezone=runtime.settings.market_timezone,
            ),
            flush=True,
        )
        return 0

    stop_event = threading.Event()
    install_shutdown_handlers(stop_event)

    def _tick(_iteration: int) -> dict[str, object]:
        result = scheduler.run_once()
        return {
            "tick_at": result.tick_at,
            "market_open": result.market_open,
            "processed_symbols": result.processed_symbols,
            "processed_count": len(result.processed_symbols),
            "timezone": runtime.settings.market_timezone,
            "wall_clock": now_label(runtime.settings.market_timezone),
        }

    return run_loop(
        worker_name="monitoring",
        interval_seconds=args.interval_seconds,
        stop_event=stop_event,
        tick=_tick,
    )


if __name__ == "__main__":
    raise SystemExit(main())
