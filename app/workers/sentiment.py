from __future__ import annotations

import argparse
import os

from app.config import get_settings
from app.workers.sentiment_worker import SentimentWorker

DEFAULT_INTERVAL_SECONDS = 300


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone sentiment worker.")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.getenv("TRADER_SENTIMENT_WORKER_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)),
        help="Polling interval for sentiment ingestion cycles.",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Execute a single ingestion cycle and exit.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()
    worker = SentimentWorker(
        settings=settings,
        interval_seconds=max(60, args.interval_seconds),
    )

    if args.run_once:
        worker.run_once()
        return 0

    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
