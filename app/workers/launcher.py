from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

from app.workers.runtime import format_worker_log


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch web plus standalone workers.")
    parser.add_argument("--host", default=os.getenv("TRADER_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", default=os.getenv("TRADER_WEB_PORT", "5000"))
    parser.add_argument(
        "--monitoring-interval-seconds",
        type=int,
        default=int(os.getenv("TRADER_MONITORING_WORKER_INTERVAL_SECONDS", 300)),
    )
    parser.add_argument(
        "--sentiment-interval-seconds",
        type=int,
        default=int(os.getenv("TRADER_SENTIMENT_WORKER_INTERVAL_SECONDS", 300)),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env = dict(os.environ)
    env["TRADER_ENABLE_EMBEDDED_MONITORING"] = "0"

    commands = [
        [
            sys.executable,
            "-m",
            "main",
        ],
        [
            sys.executable,
            "-m",
            "app.workers.monitoring",
            "--interval-seconds",
            str(args.monitoring_interval_seconds),
        ],
        [
            sys.executable,
            "-m",
            "app.workers.sentiment",
            "--interval-seconds",
            str(args.sentiment_interval_seconds),
        ],
    ]
    env["TRADER_WEB_HOST"] = str(args.host)
    env["TRADER_WEB_PORT"] = str(args.port)

    processes = [subprocess.Popen(command, env=env) for command in commands]
    print(
        format_worker_log(
            "launcher.started",
            process_count=len(processes),
            embedded_monitoring=False,
        ),
        flush=True,
    )

    try:
        while True:
            for process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    print(
                        format_worker_log(
                            "launcher.child_exited",
                            pid=process.pid,
                            exit_code=exit_code,
                        ),
                        flush=True,
                    )
                    for sibling in processes:
                        if sibling.poll() is None:
                            sibling.terminate()
                    return exit_code
            time.sleep(1)
    except KeyboardInterrupt:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
