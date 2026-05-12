from __future__ import annotations

import argparse
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import akshare as ak

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
    events.extend(_collect_trade_calendar_events(now))
    events.extend(_collect_fallback_rule_events(now))
    return events


def _collect_trade_calendar_events(now: datetime) -> list[dict[str, object]]:
    date_key = now.strftime("%Y%m%d")
    events: list[dict[str, object]] = []

    try:
        suspend_df = ak.news_trade_notify_suspend_baidu(date=date_key)
        for row in suspend_df.to_dict("records"):
            if str(row.get("证券类型", "")).lower() != "stock":
                continue
            if str(row.get("市场类型", "")).lower() != "ab":
                continue
            symbol = str(row.get("股票代码", "")).strip() or None
            title = f"{row.get('股票简称', symbol or '未知标的')} 停复牌提醒"
            detail = str(row.get("停牌事项说明", "停复牌事项")).strip() or "停复牌事项"
            event_date = str(row.get("公告日期", "")).strip() or now.date().isoformat()
            events.append(
                {
                    "symbol": symbol,
                    "title": title,
                    "event_type": "suspension_resume",
                    "severity": "high" if "重大事项" in detail else "medium",
                    "event_date": event_date,
                    "source": "baidu_trade_calendar",
                    "details": {
                        "resume_date": str(row.get("复牌时间", "")).strip(),
                        "suspend_date": str(row.get("停牌时间", "")).strip(),
                        "detail": detail,
                    },
                }
            )
    except Exception:
        pass

    try:
        dividend_df = ak.news_trade_notify_dividend_baidu(date=date_key)
        for row in dividend_df.to_dict("records"):
            exchange = str(row.get("交易所", "")).strip().upper()
            if exchange not in {"SH", "SZ"}:
                continue
            symbol = str(row.get("股票代码", "")).strip() or None
            title = f"{row.get('股票简称', symbol or '未知标的')} 分红派息提醒"
            event_date = _normalize_event_date(row.get("除权日"), now)
            events.append(
                {
                    "symbol": symbol,
                    "title": title,
                    "event_type": "dividend_ex_date",
                    "severity": "medium",
                    "event_date": event_date,
                    "source": "baidu_trade_calendar",
                    "details": {
                        "cash_dividend": str(row.get("分红", "")).strip(),
                        "bonus_share": str(row.get("送股", "")).strip(),
                        "capitalization": str(row.get("转增", "")).strip(),
                        "report_period": _normalize_event_date(row.get("报告期"), now),
                    },
                }
            )
    except Exception:
        pass

    return events


def _collect_fallback_rule_events(now: datetime) -> list[dict[str, object]]:
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


def _normalize_event_date(value: object, now: datetime) -> str:
    if value is None:
        return now.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or now.date().isoformat()


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
