from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from statistics import mean
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for

from app.config import Settings
from app.domain import CompanyReference, MarketSnapshot, SentimentItem
from app.domain.serialization import to_json_ready
from app.evaluation import build_recommendation_review_report
from app.modules import build_capability_catalog
from app.modules.entity_mapping import CompanyDictionary, CompanyDictionaryEntry, build_default_entity_mapping_service
from app.modules.entity_mapping.normalization import normalize_lookup_key
from app.modules.market_data import build_default_market_data_service
from app.modules.market_data.adapters import normalize_symbol
from app.modules.market_data.contracts import MarketDataResult
from app.modules.market_data.errors import MarketDataValidationError
from app.modules.recommendation_engine import RecommendationBundle, build_default_recommendation_engine_service
from app.modules.sentiment_ingestion import build_default_sample_sources, build_default_sentiment_service
from app.modules.technical_analysis import (
    TechnicalAnalysisValidationError,
    build_default_technical_analysis_service,
)
from app.modules.technical_analysis.contracts import TechnicalAnalysisResult
from app.modules.trader_agent import build_default_trader_agent_service
from app.persistence import AlertRepository, AlertRow, RecommendationEventRepository, WatchlistRepository

bp = Blueprint("core", __name__)

_ACTION_LABELS = {
    "buy": "买入",
    "sell": "卖出",
    "watch": "观察",
    "avoid": "回避",
}
_DIRECTION_LABELS = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "中性",
    "mixed": "分歧",
}
_ACTIVITY_KIND_LABELS = {
    "scheduled": "自动刷新",
    "research": "研究动作",
    "other": "其他历史",
}

_WEB_NAVIGATION = (
    {"endpoint": "core.dashboard", "label": "总览", "description": "Dashboard"},
    {"endpoint": "core.research", "label": "个股研究", "description": "Research"},
    {"endpoint": "core.sentiment", "label": "舆情监控", "description": "Sentiment"},
    {"endpoint": "core.recommendations", "label": "交易员建议", "description": "Agent"},
    {"endpoint": "core.system_capabilities", "label": "系统能力", "description": "System"},
)


def _settings() -> Settings:
    return current_app.config["TRADER_SETTINGS"]


def _watchlist_repository() -> WatchlistRepository:
    return current_app.config["TRADER_WATCHLIST_REPOSITORY"]


def _alert_repository() -> AlertRepository:
    return current_app.config["TRADER_ALERT_REPOSITORY"]


def _recommendation_event_repository() -> RecommendationEventRepository:
    return current_app.config["TRADER_RECOMMENDATION_EVENT_REPOSITORY"]


def _monitoring_scheduler():
    return current_app.config["TRADER_MONITORING_SCHEDULER"]


def _embedded_monitoring_enabled() -> bool:
    return bool(current_app.config.get("TRADER_EMBEDDED_MONITORING_ENABLED", False))


def _build_sentiment_sources(symbols: list[str] | None = None):
    sources = build_default_sample_sources()
    live_symbols = _normalize_sentiment_symbols(symbols)
    if not live_symbols:
        return sources

    return [
        replace(
            source,
            parameters={
                **source.parameters,
                "symbols": live_symbols,
            },
        )
        if source.adapter_name == "akshare_stock_news_em"
        else source
        for source in sources
    ]


def _build_sentiment_source_health_summary() -> dict[str, object]:
    sources = _build_sentiment_sources()
    checked_at = datetime.now(ZoneInfo(_settings().market_timezone)).strftime("%Y-%m-%d %H:%M")
    try:
        ingestion_result = build_default_sentiment_service().ingest(sources)
    except Exception as exc:
        return {
            "status": "unavailable",
            "label": "不可用",
            "message": f"舆情来源健康检查暂时不可用：{exc}",
            "failed_source_count": 0,
            "total_source_count": len(sources),
            "checked_at": checked_at,
            "reason_summary": [],
            "failures": [],
        }

    source_runs = [
        {
            "source": run.source_metadata.source_name,
            "category": run.source_metadata.category.value,
            "fetched": run.fetched_count,
            "emitted": run.emitted_count,
            "duplicate": run.duplicate_count,
            "stale": run.stale_count,
        }
        for run in ingestion_result.source_runs
    ]
    return _build_sentiment_failure_summary(
        ingestion_result=ingestion_result,
        source_runs=source_runs,
        checked_at=checked_at,
    )


def _normalize_sentiment_symbols(symbols: list[str] | None, *, limit: int | None = 8) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for symbol in symbols or []:
        try:
            code = normalize_symbol(symbol)
        except MarketDataValidationError:
            continue
        if code in seen:
            continue
        seen.add(code)
        normalized.append(code)
        if limit is not None and len(normalized) >= limit:
            break
    return normalized


@bp.get("/")
def index() -> str:
    return dashboard()


@bp.get("/dashboard")
def dashboard() -> str:
    settings = _settings()
    capabilities = build_capability_catalog(settings)
    watchlist = _build_watchlist_view_models()
    alerts, alert_summary = _build_alert_view_models()
    recent_activity = _build_recent_activity(limit=5)
    recommendation_events = _build_recommendation_event_history(limit=5)
    event_watch = _build_market_event_watch()
    sentiment_source_health = _build_sentiment_source_health_summary()
    worker_health = _build_worker_health_summary(
        sentiment_latest_update=sentiment_source_health.get("checked_at"),
        sentiment_mode="request",
        sentiment_status=sentiment_source_health.get("status", "healthy"),
    )
    recent_scheduled = [item for item in recent_activity if item["status"] == "scheduled"]
    recent_research = [item for item in recent_activity if item["status"] == "research"]
    return render_template(
        "dashboard.html",
        capabilities=capabilities,
        settings=settings,
        watchlist=watchlist,
        alerts=alerts,
        alert_summary=alert_summary,
        recent_activity=recent_activity,
        recommendation_events=recommendation_events,
        event_watch=event_watch,
        sentiment_source_health=sentiment_source_health,
        worker_health=worker_health,
        recent_scheduled=recent_scheduled,
        recent_research=recent_research,
        alerts_for_title=alerts,
        navigation=_WEB_NAVIGATION,
        active_nav="core.dashboard",
    )


@bp.post("/watchlist")
def add_watchlist_stock() -> str:
    symbol = request.form.get("symbol", "").strip()
    name = request.form.get("name", "").strip()
    if symbol and name:
        _watchlist_repository().create_stock(symbol, name)
    return redirect(url_for("core.dashboard"))


@bp.post("/watchlist/<symbol>/toggle")
def toggle_watchlist_stock(symbol: str) -> str:
    _watchlist_repository().toggle_stock_monitoring(symbol)
    return redirect(url_for("core.dashboard"))


@bp.post("/watchlist/<symbol>/delete")
def delete_watchlist_stock(symbol: str) -> str:
    _watchlist_repository().delete_stock(symbol)
    return redirect(url_for("core.dashboard"))


@bp.post("/watchlist/<symbol>/refresh")
def refresh_watchlist_stock(symbol: str) -> str:
    _refresh_watchlist_item(symbol)
    return redirect(url_for("core.dashboard"))


@bp.get("/research")
def research() -> str:
    query = request.args.get("query", "").strip()
    workspace = _build_research_workspace(query)
    watchlist_action = _build_research_watchlist_action(workspace)
    event_watch = _build_market_event_watch()
    worker_health = _build_worker_health_summary(
        sentiment_latest_update=workspace["sentiment_runtime"]["latest_update"],
        sentiment_mode=workspace["sentiment_runtime"]["mode"],
        sentiment_status=workspace["sentiment_runtime"]["status"],
        research_symbol=workspace["target"]["symbol"],
    )
    return render_template(
        "research.html",
        query=query,
        workspace=workspace,
        watchlist_action=watchlist_action,
        event_watch=event_watch,
        worker_health=worker_health,
        navigation=_WEB_NAVIGATION,
        active_nav="core.research",
    )


@bp.post("/research/watchlist")
def research_add_watchlist_stock() -> str:
    symbol = request.form.get("symbol", "").strip()
    name = request.form.get("name", "").strip()
    if symbol and name:
        _watchlist_repository().create_stock(symbol, name)
        _watchlist_repository().record_research_note(symbol, f"从研究页加入关注：{name}")
    return redirect(url_for("core.system_capabilities", symbol=symbol or ""))


@bp.get("/sentiment")
def sentiment() -> str:
    workspace = _build_sentiment_workspace()
    worker_health = _build_worker_health_summary(
        sentiment_latest_update=workspace["runtime"]["latest_update"],
        sentiment_mode=workspace["runtime"]["mode"],
        sentiment_status=workspace["runtime"]["status"],
    )
    return render_template(
        "sentiment.html",
        workspace=workspace,
        worker_health=worker_health,
        navigation=_WEB_NAVIGATION,
        active_nav="core.sentiment",
    )


@bp.get("/recommendations")
def recommendations() -> str:
    workspace = _build_recommendations_workspace()
    return render_template(
        "recommendations.html",
        workspace=workspace,
        event_watch=_build_market_event_watch(),
        navigation=_WEB_NAVIGATION,
        active_nav="core.recommendations",
    )


@bp.get("/system")
def system_capabilities() -> str:
    settings = _settings()
    capabilities = build_capability_catalog(settings)
    sentiment_source_health = _build_sentiment_source_health_summary()
    selected_symbol = request.args.get("symbol", "").strip()
    selected_kind = request.args.get("kind", "").strip()
    selected_limit = _get_positive_int_arg("limit", default=8)
    recent_runs = _build_recent_activity(selected_symbol or None, limit=selected_limit)
    if selected_kind in {"scheduled", "research", "other"}:
        recent_runs = [item for item in recent_runs if _normalize_activity_kind(item["status"]) == selected_kind]
    recommendation_events = _build_recommendation_event_history(
        selected_symbol or None,
        limit=selected_limit,
    )
    monitoring_status = _safe_monitoring_status_snapshot()
    grouped_activity = _group_activity_by_kind(recent_runs)
    activity_summary = _build_activity_summary(recent_runs)
    quick_symbols = _build_quick_filter_symbols()
    worker_health = _build_worker_health_summary(
        sentiment_latest_update=sentiment_source_health.get("checked_at"),
        sentiment_mode="request",
        sentiment_status=sentiment_source_health.get("status", "healthy"),
    )
    evaluation_report = _build_evaluation_report(
        symbol=selected_symbol or None,
        recent_runs=recent_runs,
    )
    return render_template(
        "system.html",
        capabilities=capabilities,
        settings=settings,
        recent_runs=recent_runs,
        recommendation_events=recommendation_events,
        grouped_activity=grouped_activity,
        activity_summary=activity_summary,
        monitoring_status=monitoring_status,
        sentiment_source_health=sentiment_source_health,
        worker_health=worker_health,
        evaluation_report=evaluation_report,
        selected_symbol=selected_symbol,
        selected_kind=selected_kind,
        selected_limit=selected_limit,
        quick_symbols=quick_symbols,
        navigation=_WEB_NAVIGATION,
        active_nav="core.system_capabilities",
    )


@bp.get("/api/health")
def health() -> tuple[dict[str, object], int]:
    settings = _settings()
    return {
        "status": "ok",
        "application": settings.app_name,
        "environment": settings.environment,
    }, 200


@bp.post("/api/alerts/mark-all-read")
def mark_all_alerts_read() -> tuple[object, int]:
    marked_count = _alert_repository().mark_all_read()
    return jsonify({"status": "ok", "marked_count": marked_count}), 200


@bp.post("/api/alerts/<int:alert_id>/mark-read")
def mark_alert_read(alert_id: int) -> tuple[object, int]:
    marked = _alert_repository().mark_read(alert_id)
    return jsonify({"status": "ok", "alert_id": alert_id, "marked": marked}), 200


@bp.get("/api/capabilities")
def capabilities() -> tuple[object, int]:
    settings = _settings()
    payload = build_capability_catalog(settings)
    return jsonify(to_json_ready(payload)), 200


@bp.get("/api/system/workers")
def system_workers_api() -> tuple[object, int]:
    sentiment_source_health = _build_sentiment_source_health_summary()
    payload = {
        "worker_health": _build_worker_health_summary(
            sentiment_latest_update=sentiment_source_health.get("checked_at"),
            sentiment_mode="request",
            sentiment_status=sentiment_source_health.get("status", "healthy"),
        ),
        "sentiment_source_health": sentiment_source_health,
        "monitoring_status": _safe_monitoring_status_snapshot(),
    }
    return jsonify(to_json_ready(payload)), 200


@bp.get("/api/system/review")
def system_review_api() -> tuple[object, int]:
    payload = _build_evaluation_report(recent_runs=_build_recent_activity(limit=12))
    return jsonify(to_json_ready(payload)), 200


@bp.get("/api/market/sample")
def market_sample() -> tuple[object, int]:
    limit = _get_positive_int_arg("limit", default=6)
    result = build_default_market_data_service().get_stock_list_sample(limit=limit)
    return jsonify(to_json_ready(result)), _status_from_market_result(result)


@bp.get("/api/market/snapshot/<symbol>")
def market_snapshot(symbol: str) -> tuple[object, int]:
    result = build_default_market_data_service().get_latest_snapshot(symbol)
    return jsonify(to_json_ready(result)), _status_from_market_result(result)


@bp.get("/api/market/bars/<symbol>")
def market_bars(symbol: str) -> tuple[object, int]:
    limit = _get_positive_int_arg("limit", default=60)
    end_date = date.today()
    start_date = end_date - timedelta(days=max(limit * 3, 30))
    result = build_default_market_data_service().get_daily_bars(
        symbol,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    return jsonify(to_json_ready(result)), _status_from_market_result(result)


@bp.get("/api/technical/<symbol>")
def technical_analysis(symbol: str) -> tuple[object, int]:
    limit = _get_positive_int_arg("limit", default=90)
    end_date = date.today()
    start_date = end_date - timedelta(days=max(limit * 3, 90))

    market_result = build_default_market_data_service().get_daily_bars(
        symbol,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    if not market_result.data:
        return jsonify(to_json_ready(market_result)), _status_from_market_result(market_result)

    try:
        analysis_result = build_default_technical_analysis_service().analyze_bars(market_result.data)
    except TechnicalAnalysisValidationError as exc:
        return jsonify({"error": str(exc), "symbol": symbol}), 400

    payload = {
        "market_data": market_result,
        "technical_analysis": analysis_result,
    }
    return jsonify(to_json_ready(payload)), 200


def _get_positive_int_arg(name: str, *, default: int) -> int:
    value = request.args.get(name, default=default, type=int)
    if value is None or value <= 0:
        return default
    return value


def _status_from_market_result(result: MarketDataResult[object]) -> int:
    if result.ok:
        return 200

    issue = result.issues[0]
    if issue.code == "market_data_validation_failed":
        return 400
    if issue.code == "market_data_not_found":
        return 404
    if issue.code == "market_data_unavailable":
        return 503 if result.data in (None, [], ()) else 200
    return 200 if result.data not in (None, [], ()) else 500


def _build_watchlist_view_models() -> list[dict[str, object]]:
    monitoring_context = _build_monitoring_context()
    unread_symbols = {alert.symbol for alert in _alert_repository().list_unread()}
    rows = _watchlist_repository().list_rows()
    return [
        {
            "symbol": row.symbol,
            "name": row.name,
            "monitoring_enabled": row.monitoring_enabled,
            "market_window": row.schedule_label,
            "status": _resolve_watchlist_status(row=row, monitoring_context=monitoring_context)["status"],
            "status_label": _resolve_watchlist_status(row=row, monitoring_context=monitoring_context)["status_label"],
            "status_reason": _resolve_watchlist_status(row=row, monitoring_context=monitoring_context)["reason"],
            "context_label": _resolve_watchlist_status(row=row, monitoring_context=monitoring_context)["context_label"],
            "last_analysis_at": row.last_analysis_at or "--",
            "recommendation": row.latest_recommendation,
            "confidence": row.latest_confidence,
            "reason": row.latest_reason,
            "unread": row.symbol in unread_symbols,
            "monitoring_now": _resolve_watchlist_status(row=row, monitoring_context=monitoring_context)["monitoring_now"],
        }
        for row in rows
    ]


def _build_alert_view_models() -> tuple[list[dict[str, object]], dict[str, object]]:
    rows = _alert_repository().list_unread()
    alerts = [
        {
            "id": row.id,
            "symbol": row.symbol,
            "title": row.title,
            "summary": row.summary,
            "time": row.created_at,
            "level": row.level,
        }
        for row in rows
    ]
    return alerts, _build_alert_summary_view_model(rows, alerts)


def _build_alert_summary_view_model(
    rows: list[AlertRow], alerts: list[dict[str, object]]
) -> dict[str, object]:
    high_count = 0
    medium_count = 0
    for row in rows:
        if row.level == "high":
            high_count += 1
        elif row.level == "medium":
            medium_count += 1

    top_alert = alerts[0] if alerts else None
    return {
        "total": len(rows),
        "high_count": high_count,
        "medium_count": medium_count,
        "other_count": len(rows) - high_count - medium_count,
        "top_alert": top_alert,
    }


def _safe_monitoring_status_snapshot() -> dict[str, object]:
    scheduler = _monitoring_scheduler()
    if scheduler is None:
        return {
            "has_tick": False,
            "tick_at": None,
            "market_open": None,
            "processed_symbols": [],
            "mode": "external",
            "label": "外部或未启用",
        }

    snapshot = scheduler.status_snapshot()
    snapshot["mode"] = "embedded"
    snapshot["label"] = "内嵌常驻调度"
    return snapshot


def _build_recent_activity(symbol: str | None = None, *, limit: int = 8) -> list[dict[str, object]]:
    recent_runs = _watchlist_repository().list_recent_analysis_runs(symbol=symbol, limit=limit)
    return [
        {
            "symbol": item["symbol"],
            "detail": item["detail"],
            "status": item["status"],
            "created_at": item["created_at"],
            "stale": item["stale"],
        }
        for item in recent_runs
    ]


def _build_recommendations_workspace() -> dict[str, object]:
    watchlist_rows = _watchlist_repository().list_rows()
    alerts, alert_summary = _build_alert_view_models()
    recommendation_events = _build_recommendation_event_history(limit=6)
    recent_activity = _build_recent_activity(limit=6)
    no_trade_queue = [
        row
        for row in watchlist_rows
        if row.latest_recommendation in {"watch", "avoid"} or row.latest_confidence < 0.4
    ]
    action_counts = {
        "buy": len([row for row in watchlist_rows if row.latest_recommendation == "buy"]),
        "sell": len([row for row in watchlist_rows if row.latest_recommendation == "sell"]),
        "watch": len([row for row in watchlist_rows if row.latest_recommendation == "watch"]),
        "avoid": len([row for row in watchlist_rows if row.latest_recommendation == "avoid"]),
    }
    return {
        "watchlist_count": len(watchlist_rows),
        "enabled_count": len([row for row in watchlist_rows if row.monitoring_enabled]),
        "high_alert_count": alert_summary["high_count"],
        "recommendation_event_count": len(recommendation_events),
        "recent_activity_count": len(recent_activity),
        "action_counts": action_counts,
        "no_trade_queue": no_trade_queue,
        "top_watchlist": watchlist_rows[:4],
        "top_alert": alert_summary["top_alert"],
        "recent_recommendation_events": recommendation_events,
        "recent_activity": recent_activity,
        "alerts": alerts,
    }


def _load_sentiment_snapshot(*, symbols: list[str]) -> dict[str, object]:
    cache_reader = current_app.config.get("TRADER_SENTIMENT_CACHE_READER")
    checked_at = datetime.now(ZoneInfo(_settings().market_timezone)).strftime("%Y-%m-%d %H:%M")
    if cache_reader is not None and hasattr(cache_reader, "read_latest"):
        try:
            cached_payload = cache_reader.read_latest(symbols=symbols)
        except TypeError:
            cached_payload = cache_reader.read_latest()
        except Exception:
            cached_payload = None
        if cached_payload:
            return {
                "mode": "persistent",
                "latest_update": _extract_sentiment_snapshot_timestamp(cached_payload) or checked_at,
                "status": "healthy",
                "fallback_used": False,
                "ingestion_result": cached_payload,
            }

    ingestion_result = build_default_sentiment_service().ingest(
        _build_sentiment_sources(symbols)
    )
    return {
        "mode": "request",
        "latest_update": checked_at,
        "status": "healthy",
        "fallback_used": cache_reader is not None,
        "ingestion_result": ingestion_result,
    }


def _extract_sentiment_snapshot_timestamp(payload: object) -> str | None:
    if isinstance(payload, dict):
        for key in ("updated_at", "last_updated_at", "latest_update", "captured_at", "created_at"):
            value = payload.get(key)
            if value:
                return str(value).replace("T", " ")
    for key in ("updated_at", "last_updated_at", "latest_update", "captured_at", "created_at"):
        value = getattr(payload, key, None)
        if value:
            return str(value).replace("T", " ")
    return None


def _snapshot_items(snapshot_payload: object) -> list[SentimentItem]:
    if isinstance(snapshot_payload, dict):
        items = snapshot_payload.get("items")
        return list(items) if isinstance(items, list) else []
    return list(getattr(snapshot_payload, "items", []) or [])


def _snapshot_source_runs(snapshot_payload: object) -> list[object]:
    if isinstance(snapshot_payload, dict):
        runs = snapshot_payload.get("source_runs")
        return list(runs) if isinstance(runs, list) else []
    return list(getattr(snapshot_payload, "source_runs", []) or [])


def _snapshot_duplicate_records(snapshot_payload: object) -> list[object]:
    if isinstance(snapshot_payload, dict):
        records = snapshot_payload.get("duplicate_records")
        return list(records) if isinstance(records, list) else []
    return list(getattr(snapshot_payload, "duplicate_records", []) or [])


def _snapshot_stale_records(snapshot_payload: object) -> list[object]:
    if isinstance(snapshot_payload, dict):
        records = snapshot_payload.get("stale_records")
        return list(records) if isinstance(records, list) else []
    return list(getattr(snapshot_payload, "stale_records", []) or [])


def _normalize_snapshot_source_run(run: object) -> dict[str, object]:
    if isinstance(run, dict):
        metadata = run.get("source_metadata")
        return {
            "source": run.get("source") or getattr(metadata, "source_name", None) or "未知来源",
            "category": run.get("category") or getattr(metadata, "category", None) or "--",
            "fetched": run.get("fetched") or run.get("fetched_count") or 0,
            "emitted": run.get("emitted") or run.get("emitted_count") or 0,
            "duplicate": run.get("duplicate") or run.get("duplicate_count") or 0,
            "stale": run.get("stale") or run.get("stale_count") or 0,
        }

    metadata = getattr(run, "source_metadata", None)
    category = getattr(metadata, "category", None)
    return {
        "source": getattr(metadata, "source_name", None) or "未知来源",
        "category": getattr(category, "value", None) or "--",
        "fetched": getattr(run, "fetched_count", 0),
        "emitted": getattr(run, "emitted_count", 0),
        "duplicate": getattr(run, "duplicate_count", 0),
        "stale": getattr(run, "stale_count", 0),
    }


def _build_sentiment_workspace_from_snapshot(
    *,
    snapshot: dict[str, object],
    watchlist_rows: list[object],
) -> dict[str, object]:
    ingestion_result = snapshot["ingestion_result"]
    entity_mapping_service = build_default_entity_mapping_service()
    watchlist_symbol_set = set(
        _normalize_sentiment_symbols([row.symbol for row in watchlist_rows if row.monitoring_enabled], limit=None)
    )
    company_lookup = {
        entry.company.symbol: entry.company
        for entry in entity_mapping_service.company_dictionary.entries
    }

    items = _snapshot_items(ingestion_result)
    mapped_items: list[dict[str, object]] = []
    company_counter: dict[str, int] = {}
    tag_counter: dict[str, int] = {}
    watchlist_hits: list[dict[str, object]] = []
    positive_count = 0
    negative_count = 0
    neutral_count = 0

    for item in items:
        score = item.sentiment_score or 0.0
        if score >= 0.15:
            positive_count += 1
        elif score <= -0.15:
            negative_count += 1
        else:
            neutral_count += 1

        matches = entity_mapping_service.map_sentiment_item(item, min_confidence=0.18, max_matches=3)
        for match in matches:
            company_counter[match.company.symbol] = company_counter.get(match.company.symbol, 0) + 1
            if match.company.symbol in watchlist_symbol_set:
                watchlist_hits.append(
                    {
                        "symbol": match.company.symbol,
                        "name": match.company.company_name,
                        "title": item.title,
                        "source": item.source,
                        "score": f"{score:+.2f}",
                        "confidence": f"{match.confidence:.0%}",
                        "published_at": item.published_at.strftime("%m-%d %H:%M"),
                    }
                )

        for tag in item.tags:
            tag_counter[tag] = tag_counter.get(tag, 0) + 1

        mapped_items.append(
            {
                "title": item.title,
                "source": item.source,
                "published_at": item.published_at.strftime("%m-%d %H:%M"),
                "score": f"{score:+.2f}",
                "summary": item.content[:120],
                "tags": list(item.tags[:3]),
                "matches": [
                    {
                        "symbol": match.company.symbol,
                        "name": match.company.company_name,
                        "confidence": f"{match.confidence:.0%}",
                    }
                    for match in matches[:2]
                ],
            }
        )

    top_companies = sorted(
        (
            {
                "symbol": symbol,
                "name": company_lookup[symbol].company_name if symbol in company_lookup else symbol,
                "count": count,
            }
            for symbol, count in company_counter.items()
        ),
        key=lambda item: (-item["count"], item["symbol"]),
    )[:4]
    top_tags = sorted(tag_counter.items(), key=lambda item: (-item[1], item[0]))[:6]
    source_runs = [_normalize_snapshot_source_run(run) for run in _snapshot_source_runs(ingestion_result)]
    source_failure_summary = _build_sentiment_failure_summary(
        ingestion_result=ingestion_result,
        source_runs=source_runs,
        checked_at=str(snapshot["latest_update"]),
    )

    return {
        "total_items": len(items),
        "source_count": len(source_runs),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "neutral_count": neutral_count,
        "duplicate_count": len(_snapshot_duplicate_records(ingestion_result)),
        "stale_count": len(_snapshot_stale_records(ingestion_result)),
        "watchlist_count": len(watchlist_rows),
        "watchlist_hit_count": len(watchlist_hits),
        "watchlist_hits": watchlist_hits[:6],
        "latest_published_at": max((item.published_at for item in items), default=None),
        "recent_items": mapped_items[:8],
        "top_companies": top_companies,
        "top_tags": top_tags,
        "source_runs": source_runs,
        "source_failure_summary": source_failure_summary,
        "source_names": [run["source"] for run in source_runs],
        "runtime": {
            "mode": snapshot["mode"],
            "latest_update": snapshot["latest_update"],
            "fallback_used": snapshot["fallback_used"],
            "status": source_failure_summary["status"],
        },
    }


def _build_sentiment_workspace() -> dict[str, object]:
    watchlist_rows = _watchlist_repository().list_rows()
    watchlist_symbols = [row.symbol for row in watchlist_rows if row.monitoring_enabled]
    snapshot = _load_sentiment_snapshot(symbols=watchlist_symbols)
    return _build_sentiment_workspace_from_snapshot(snapshot=snapshot, watchlist_rows=watchlist_rows)


def _build_sentiment_failure_summary(
    *,
    ingestion_result: object,
    source_runs: list[dict[str, object]],
    checked_at: str | None = None,
) -> dict[str, object]:
    raw_failures = list(getattr(ingestion_result, "source_failures", []) or [])
    failures = [_normalize_sentiment_failure(failure) for failure in raw_failures]
    reason_counts: dict[str, int] = {}
    for failure in failures:
        reason = failure["reason"]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    reason_summary = [
        f"{reason} ×{count}" if count > 1 else reason
        for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    failed_sources = list(dict.fromkeys(failure["source"] for failure in failures if failure["source"]))

    if not failures:
        return {
            "status": "healthy",
            "label": "正常",
            "message": "全部来源运行正常，未发现失败项。",
            "failed_source_count": 0,
            "total_source_count": len(source_runs),
            "checked_at": checked_at,
            "reason_summary": [],
            "failures": [],
        }

    return {
        "status": "degraded",
        "label": "异常",
        "message": f"{len(failed_sources) or len(failures)} 个来源失败，需检查抓取或解析链路。",
        "failed_source_count": len(failed_sources) or len(failures),
        "total_source_count": len(source_runs),
        "checked_at": checked_at,
        "reason_summary": reason_summary[:3],
        "failures": failures[:3],
    }


def _normalize_sentiment_failure(failure: object) -> dict[str, object]:
    def _mapping_value(value: object, key: str) -> object | None:
        if isinstance(value, dict):
            return value.get(key)
        return getattr(value, key, None)

    if isinstance(failure, dict):
        source = (
            failure.get("source_name")
            or failure.get("source")
            or failure.get("source_id")
            or _mapping_value(failure.get("source_metadata"), "source_name")
            or _mapping_value(failure.get("source_metadata"), "source_id")
        )
        reason = (
            failure.get("reason")
            or failure.get("error_code")
            or failure.get("code")
            or failure.get("type")
        )
        message = (
            failure.get("error_message")
            or failure.get("message")
            or failure.get("detail")
            or str(failure)
        )
    else:
        source_metadata = getattr(failure, "source_metadata", None)
        source = (
            getattr(source_metadata, "source_name", None)
            or getattr(source_metadata, "source_id", None)
            or getattr(failure, "source_name", None)
            or getattr(failure, "source", None)
        )
        reason = (
            getattr(failure, "reason", None)
            or getattr(failure, "error_code", None)
            or getattr(failure, "code", None)
            or type(failure).__name__
        )
        message = (
            getattr(failure, "error_message", None)
            or getattr(failure, "message", None)
            or str(failure)
        )

    return {
        "source": source or "未知来源",
        "reason": str(reason or "未分类"),
        "message": message,
    }


def _build_market_event_watch() -> list[dict[str, object]]:
    settings = _settings()
    now = datetime.now(ZoneInfo(settings.market_timezone))
    events: list[dict[str, object]] = []

    if now.day >= 25:
        events.append(
            {
                "title": "月末资金再平衡窗口",
                "detail": "月底附近容易出现仓位调整和资金再平衡，追价需更谨慎。",
                "level": "medium",
            }
        )

    if now.month in {1, 4, 7, 10}:
        events.append(
            {
                "title": "财报 / 业绩预告季",
                "detail": "季度披露窗口，关注业绩预告、公告和预期差。",
                "level": "high",
            }
        )

    if now.weekday() >= 3:
        events.append(
            {
                "title": "临近周末风险窗口",
                "detail": "周末前后容易出现消息面和公告扰动，建议收敛仓位。",
                "level": "medium",
            }
        )

    if now.weekday() == 0:
        events.append(
            {
                "title": "周初重新定价",
                "detail": "周初资金重新定价，短线追涨需结合确认度。",
                "level": "low",
            }
        )

    return events[:4]


def _build_recommendation_event_history(
    symbol: str | None = None,
    *,
    limit: int = 8,
) -> list[dict[str, object]]:
    rows = _recommendation_event_repository().list_recent(limit=limit, symbol=symbol)
    return [
        {
            "symbol": row.symbol,
            "previous_action": row.previous_action,
            "current_action": row.current_action,
            "confidence": f"{row.confidence:.0%}",
            "summary": row.summary,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _build_activity_summary(recent_runs: list[dict[str, object]]) -> dict[str, object]:
    counts = {kind: 0 for kind in _ACTIVITY_KIND_LABELS}
    for item in recent_runs:
        counts[_normalize_activity_kind(item["status"])] += 1

    latest_run = recent_runs[0] if recent_runs else None
    latest_kind = _normalize_activity_kind(latest_run["status"]) if latest_run else None
    return {
        "total_count": len(recent_runs),
        "latest_label": _ACTIVITY_KIND_LABELS[latest_kind] if latest_kind else "暂无记录",
        "latest_symbol": latest_run["symbol"] if latest_run else None,
        "latest_created_at": latest_run["created_at"] if latest_run else None,
        "counts": counts,
    }


def _group_activity_by_kind(recent_runs: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    groups = {"scheduled": [], "research": [], "other": []}
    for item in recent_runs:
        kind = _normalize_activity_kind(item["status"])
        if kind in groups:
            groups[kind].append(item)
        else:
            groups["other"].append(item)
    return groups


def _normalize_activity_kind(status: object) -> str:
    kind = str(status)
    return kind if kind in {"scheduled", "research"} else "other"


def _build_quick_filter_symbols() -> list[str]:
    rows = _watchlist_repository().list_rows()
    return [row.symbol for row in rows[:4]]


def _build_research_recent_activity_summary(target: dict[str, object]) -> dict[str, object]:
    symbol = target["symbol"]
    if symbol is None:
        return _empty_research_recent_activity_summary()

    symbol_str = str(symbol)
    watchlist_row = _watchlist_repository().get_row(symbol_str)
    recent_runs = _build_recent_activity(symbol_str, limit=3)
    latest_run = recent_runs[0] if recent_runs else None
    recent_research_note = next((item for item in recent_runs if item["status"] == "research"), None)
    display_name = watchlist_row.name if watchlist_row is not None else target["display_name"]

    if watchlist_row is None:
        status_label = "未加入关注"
        summary = "当前标的还不在关注列表中，但这里会保留最近的研究和分析记录。"
    elif watchlist_row.monitoring_enabled:
        status_label = watchlist_row.status_label
        summary = "当前标的已在关注列表中，监控开启时会持续写入新的分析历史。"
    else:
        status_label = watchlist_row.status_label
        summary = "当前标的已在关注列表中，但监控已关闭，仍可查看最近的研究历史。"

    latest_focus_item = recent_research_note or latest_run
    latest_focus_label = "最近加入关注" if recent_research_note is not None else "最近分析"
    latest_focus_detail = latest_focus_item["detail"] if latest_focus_item is not None else "暂无分析或加入关注记录。"

    return {
        "available": True,
        "symbol": symbol_str,
        "display_name": display_name,
        "status_label": status_label,
        "summary": summary,
        "latest_focus_label": latest_focus_label,
        "latest_focus_detail": latest_focus_detail,
        "last_analysis_at": watchlist_row.last_analysis_at if watchlist_row is not None else None,
        "recent_count": len(recent_runs),
        "recent_items": [
            {
                "status": item["status"],
                "status_label": _ACTIVITY_KIND_LABELS[_normalize_activity_kind(item["status"])],
                "detail": item["detail"],
                "created_at": str(item["created_at"]).replace("T", " "),
                "stale": item["stale"],
            }
            for item in recent_runs
        ],
        "has_watchlist_entry": watchlist_row is not None,
    }


def _empty_research_recent_activity_summary() -> dict[str, object]:
    return {
        "available": False,
        "symbol": None,
        "display_name": "未选择标的",
        "status_label": None,
        "summary": "解析出股票后，这里会显示最近是否加入关注，以及最近的分析记录。",
        "latest_focus_label": None,
        "latest_focus_detail": None,
        "last_analysis_at": None,
        "recent_count": 0,
        "recent_items": [],
        "has_watchlist_entry": False,
    }


def _build_research_watchlist_action(workspace: dict[str, object]) -> dict[str, object]:
    target = workspace["target"]
    company = target["company"]
    symbol = target["symbol"]
    if company is None or symbol is None:
        return {
            "available": False,
            "symbol": None,
            "name": None,
            "reason": "解析出股票后可一键加入关注列表并开始监控。",
        }

    return {
        "available": True,
        "symbol": symbol,
        "name": company.company_name,
        "reason": "可将当前研究标的加入监控列表，并沿用默认交易时段自动刷新建议。",
    }


def _refresh_watchlist_item(symbol: str) -> bool:
    target = _resolve_research_target(symbol)
    resolved_symbol = target["symbol"]
    if resolved_symbol is None:
        return False

    market_service = build_default_market_data_service()
    snapshot_result = market_service.get_latest_snapshot(str(resolved_symbol))
    market_state = "active" if snapshot_result.data is not None else "paused"
    market_label = "监控中" if snapshot_result.data is not None else "等待开市"

    if snapshot_result.data is None:
        recommendation = "watch"
        confidence = 0.0
        reason = "实时行情暂时不可用，保留最近一次建议。"
    else:
        bars_result = market_service.get_daily_bars(
            str(resolved_symbol),
            start_date=date.today() - timedelta(days=180),
            end_date=date.today(),
            limit=90,
        )
        technical_result = None
        if bars_result.data:
            try:
                technical_result = build_default_technical_analysis_service().analyze_bars(bars_result.data)
            except TechnicalAnalysisValidationError:
                technical_result = None

        if technical_result is None:
            recommendation = "watch"
            confidence = 0.35
            reason = "技术分析不可用，建议继续观察。"
        else:
            recommendation = "buy" if technical_result.bullish_score >= technical_result.bearish_score else "watch"
            confidence = max(technical_result.bullish_score, technical_result.bearish_score)
            reason = (
                technical_result.signals[0].summary
                if technical_result.signals
                else "基于当前技术结构的默认刷新结果。"
            )

    return _watchlist_repository().record_refresh(
        str(resolved_symbol),
        latest_recommendation=recommendation,
        latest_confidence=confidence,
        latest_reason=reason,
        status=market_state,
        status_label=market_label,
        last_analysis_at=datetime.now(ZoneInfo(_settings().market_timezone)).strftime("%H:%M"),
    )


def _build_monitoring_context() -> dict[str, object]:
    settings = _settings()
    timezone = ZoneInfo(settings.market_timezone)
    now = datetime.now(timezone)
    am_start = _parse_market_time(settings.market_open_am_start)
    am_end = _parse_market_time(settings.market_open_am_end)
    pm_start = _parse_market_time(settings.market_open_pm_start)
    pm_end = _parse_market_time(settings.market_open_pm_end)
    current_time = now.time()
    is_weekday = now.weekday() < 5
    within_am = am_start <= current_time <= am_end
    within_pm = pm_start <= current_time <= pm_end
    market_open = is_weekday and (within_am or within_pm)
    return {
        "market_open": market_open,
        "now_label": now.strftime("%Y-%m-%d %H:%M"),
        "session_label": (
            f"{settings.market_open_am_start}-{settings.market_open_am_end} / "
            f"{settings.market_open_pm_start}-{settings.market_open_pm_end}"
        ),
        "is_weekday": is_weekday,
        "timezone": settings.market_timezone,
    }


def _resolve_watchlist_status(*, row: object, monitoring_context: dict[str, object]) -> dict[str, object]:
    if not row.monitoring_enabled:
        return {
            "status": "disabled",
            "status_label": "未开启",
            "reason": "该标的当前未启用持续监控。",
            "monitoring_now": False,
            "context_label": "监控开关关闭",
        }

    if monitoring_context["market_open"]:
        return {
            "status": "active",
            "status_label": "监控中",
            "reason": f"当前处于A股交易时段，系统应持续刷新建议。({monitoring_context['now_label']})",
            "monitoring_now": True,
            "context_label": f"当前时间 {monitoring_context['now_label']} · {monitoring_context['timezone']}",
        }

    if not monitoring_context["is_weekday"]:
        return {
            "status": "paused",
            "status_label": "非交易日暂停",
            "reason": "当前不是交易日，监控按照默认规则自动暂停。",
            "monitoring_now": False,
            "context_label": f"当前时间 {monitoring_context['now_label']} · {monitoring_context['timezone']}",
        }

    return {
        "status": "paused",
        "status_label": "闭市暂停",
        "reason": f"当前不在默认交易时段 {monitoring_context['session_label']} 内，监控自动暂停。",
        "monitoring_now": False,
        "context_label": f"当前时间 {monitoring_context['now_label']} · {monitoring_context['timezone']}",
    }


def _parse_market_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _build_research_workspace(query: str) -> dict[str, object]:
    target = _resolve_research_target(query)
    workspace = {
        "query": query,
        "has_query": bool(query),
        "target": target,
        "market": _empty_market_summary(),
        "technical": _empty_technical_summary(),
        "sentiment": _empty_sentiment_summary(),
        "mapping": _empty_mapping_summary(),
        "recommendation": _empty_recommendation_summary(),
        "recent_activity": _empty_research_recent_activity_summary(),
        "recommendation_events": [],
        "sentiment_source_health": None,
        "sentiment_runtime": {
            "mode": "idle",
            "latest_update": None,
            "fallback_used": False,
            "status": "idle",
        },
        "errors": list(target["issues"]),
    }

    if target["symbol"] is None:
        workspace["market"]["message"] = "输入股票代码或已收录公司名称后，这里会展示最新行情摘要。"
        workspace["technical"]["message"] = "解析到股票后，这里会展示趋势、均线和关键技术信号。"
        workspace["sentiment"]["message"] = "解析到股票后，这里会展示关联舆情与来源概览。"
        workspace["mapping"]["message"] = "解析到股票后，这里会展示实体映射证据与置信度。"
        workspace["recommendation"]["message"] = "解析到股票后，这里会展示最终建议、风险和证据链。"
        return workspace

    symbol = str(target["symbol"])
    workspace["recent_activity"] = _build_research_recent_activity_summary(target)
    workspace["recommendation_events"] = _build_recommendation_event_history(symbol, limit=3)
    market_service = build_default_market_data_service()
    snapshot_result = market_service.get_latest_snapshot(symbol)
    workspace["market"] = _build_market_summary(target=target, snapshot_result=snapshot_result)
    workspace["errors"].extend(issue.message for issue in snapshot_result.issues)

    end_date = date.today()
    bars_result = market_service.get_daily_bars(
        symbol,
        start_date=end_date - timedelta(days=240),
        end_date=end_date,
        limit=120,
    )
    workspace["errors"].extend(issue.message for issue in bars_result.issues)

    technical_analysis_result = None
    if bars_result.data:
        try:
            technical_analysis_result = build_default_technical_analysis_service().analyze_bars(bars_result.data)
        except TechnicalAnalysisValidationError as exc:
            workspace["errors"].append(str(exc))
        else:
            workspace["technical"] = _build_technical_summary(technical_analysis_result)
    else:
        workspace["technical"]["status"] = "empty"
        workspace["technical"]["message"] = "暂无足够K线数据，技术分析未生成。"

    if target["company"] is None:
        workspace["sentiment"]["status"] = "unavailable"
        workspace["sentiment"]["message"] = "该标的未收录进当前实体映射字典，暂时无法展示定向舆情映射。"
        workspace["mapping"]["status"] = "unavailable"
        workspace["mapping"]["message"] = "该标的未收录进当前实体映射字典，暂时无法展示映射证据。"
        sentiment_items: list[SentimentItem] = []
        matched_sentiment: list[dict[str, object]] = []
    else:
        try:
            entity_mapping_service = build_default_entity_mapping_service()
            sentiment_items, matched_sentiment, sentiment_source_health = _collect_target_sentiment(
                company=target["company"],
                entity_mapping_service=entity_mapping_service,
            )
        except Exception as exc:
            workspace["errors"].append(f"舆情或实体映射服务暂时不可用: {exc}")
            sentiment_items = []
            matched_sentiment = []
            workspace["sentiment"]["status"] = "unavailable"
            workspace["sentiment"]["message"] = "舆情服务暂时不可用，已保留研究页其他结果。"
            workspace["mapping"]["status"] = "unavailable"
            workspace["mapping"]["message"] = "实体映射暂时不可用，已保留研究页其他结果。"
        else:
            workspace["sentiment_source_health"] = sentiment_source_health
            workspace["sentiment"] = _build_sentiment_summary(matched_sentiment)
            workspace["mapping"] = _build_mapping_summary(matched_sentiment)
            workspace["sentiment_runtime"] = {
                "mode": sentiment_source_health.get("mode", "request"),
                "latest_update": sentiment_source_health.get("checked_at"),
                "fallback_used": bool(sentiment_source_health.get("fallback_used")),
                "status": sentiment_source_health.get("status", "healthy"),
            }

    technical_signals = (
        list(technical_analysis_result.signals)
        if technical_analysis_result is not None
        else []
    )
    evaluation_at = (
        snapshot_result.data.captured_at
        if snapshot_result.data is not None
        else None
    )
    try:
        trader_agent_service = build_default_trader_agent_service()
        trader_input = trader_agent_service.assemble_input(
            symbol=symbol,
            technical_signals=technical_signals,
            sentiment_items=sentiment_items,
            company_matches=[row["match"] for row in matched_sentiment],
            evaluation_at=evaluation_at,
        )
        agent_recommendation = trader_agent_service.generate_recommendation_from_input(trader_input)
        recommendation_bundle = build_default_recommendation_engine_service().build_recommendation_bundle(
            symbol=symbol,
            technical_signals=technical_signals,
            sentiment_items=sentiment_items,
            company_matches=[row["match"] for row in matched_sentiment],
            agent_recommendation=agent_recommendation,
            trader_agent_input=trader_input,
            evaluation_at=evaluation_at,
        )
    except Exception as exc:
        workspace["errors"].append(f"推荐引擎暂时不可用: {exc}")
        workspace["recommendation"]["status"] = "unavailable"
        workspace["recommendation"]["message"] = "推荐引擎暂时不可用，已保留行情和技术分析结果。"
    else:
        workspace["recommendation"] = _build_recommendation_summary(
            recommendation_bundle=recommendation_bundle,
            sentiment_count=len(sentiment_items),
        )
    workspace["errors"] = list(dict.fromkeys(workspace["errors"]))
    return workspace


def _resolve_research_target(query: str) -> dict[str, object]:
    if not query:
        return {
            "query": "",
            "symbol": None,
            "company": None,
            "display_name": "未选择标的",
            "issues": [],
        }

    dictionary = build_default_entity_mapping_service().company_dictionary
    compact_query = "".join(character for character in query.split())
    try:
        symbol = normalize_symbol(query)
    except MarketDataValidationError:
        symbol = None
    else:
        company = _find_company_by_symbol(dictionary, symbol)
        return {
            "query": query,
            "symbol": symbol,
            "company": company,
            "display_name": (
                f"{company.company_name} ({company.symbol})"
                if company is not None
                else symbol
            ),
            "issues": [],
        }

    matched_entry = _find_company_entry_by_query(dictionary, compact_query)
    if matched_entry is not None:
        return {
            "query": query,
            "symbol": matched_entry.company.symbol,
            "company": matched_entry.company,
            "display_name": f"{matched_entry.company.company_name} ({matched_entry.company.symbol})",
            "issues": [],
        }

    return {
        "query": query,
        "symbol": None,
        "company": None,
        "display_name": query,
        "issues": ["未能解析该查询。请使用6位股票代码，或输入当前字典已收录的公司名称/别名。"],
    }


def _find_company_by_symbol(dictionary: CompanyDictionary, symbol: str) -> CompanyReference | None:
    for entry in dictionary.entries:
        if entry.company.symbol == symbol:
            return entry.company
    return None


def _find_company_entry_by_query(
    dictionary: CompanyDictionary,
    query: str,
) -> CompanyDictionaryEntry | None:
    normalized_query = normalize_lookup_key(query)
    if not normalized_query:
        return None

    for entry in dictionary.entries:
        candidates = (
            entry.company.company_name,
            *entry.aliases,
            *entry.symbol_keywords,
        )
        for candidate in candidates:
            if normalize_lookup_key(candidate) == normalized_query:
                return entry
    return None


def _build_market_summary(
    *,
    target: dict[str, object],
    snapshot_result: MarketDataResult[MarketSnapshot | None],
) -> dict[str, object]:
    company = target["company"]
    snapshot = snapshot_result.data
    if snapshot is None:
        return {
            "status": "unavailable",
            "message": "实时行情暂时不可用，页面保留了基础研究上下文和后续分析占位。",
            "display_name": company.company_name if company is not None else target["display_name"],
            "symbol": target["symbol"],
            "exchange": company.exchange if company is not None else "--",
            "industry": company.industry if company is not None and company.industry else "--",
            "themes": list(company.themes) if company is not None else [],
            "source": snapshot_result.source,
            "captured_at": None,
            "last_price": None,
            "change_percent": None,
            "volume": None,
            "turnover": None,
        }

    return {
        "status": "ready",
        "message": None,
        "display_name": snapshot.name,
        "symbol": snapshot.symbol,
        "exchange": company.exchange if company is not None else "--",
        "industry": company.industry if company is not None and company.industry else "--",
        "themes": list(company.themes) if company is not None else [],
        "source": snapshot_result.source,
        "captured_at": snapshot.captured_at.strftime("%Y-%m-%d %H:%M"),
        "last_price": f"{snapshot.last_price:.2f}",
        "change_percent": _format_percent(snapshot.change_percent),
        "volume": _format_large_number(snapshot.volume),
        "turnover": _format_large_number(snapshot.turnover),
    }


def _empty_market_summary() -> dict[str, object]:
    return {
        "status": "idle",
        "message": None,
        "display_name": "未选择标的",
        "symbol": None,
        "exchange": "--",
        "industry": "--",
        "themes": [],
        "source": None,
        "captured_at": None,
        "last_price": None,
        "change_percent": None,
        "volume": None,
        "turnover": None,
    }


def _build_technical_summary(analysis_result: TechnicalAnalysisResult) -> dict[str, object]:
    bullish_signals = sorted(
        (signal for signal in analysis_result.signals if signal.direction.value == "bullish"),
        key=lambda signal: signal.score,
        reverse=True,
    )
    bearish_signals = sorted(
        (signal for signal in analysis_result.signals if signal.direction.value == "bearish"),
        key=lambda signal: signal.score,
        reverse=True,
    )
    latest_bar = analysis_result.latest_bar
    indicator_snapshot = analysis_result.indicator_snapshot
    return {
        "status": "ready",
        "message": None,
        "trend_direction": analysis_result.trend_direction.value,
        "trend_label": _DIRECTION_LABELS[analysis_result.trend_direction.value],
        "market_regime": analysis_result.market_regime,
        "market_regime_label": analysis_result.market_regime_label,
        "confirmation_score": f"{analysis_result.confirmation_score:.2f}",
        "bullish_score": f"{analysis_result.bullish_score:.2f}",
        "bearish_score": f"{analysis_result.bearish_score:.2f}",
        "analyzed_bar_count": analysis_result.analyzed_bar_count,
        "latest_trade_date": latest_bar.trade_date.isoformat(),
        "latest_close": f"{latest_bar.close_price:.2f}",
        "latest_change_percent": _format_percent(latest_bar.change_percent),
        "sma_20": _format_nullable_float(indicator_snapshot.sma_20),
        "sma_60": _format_nullable_float(indicator_snapshot.sma_60),
        "change_5d": _format_percent(indicator_snapshot.change_5d),
        "change_10d": _format_percent(indicator_snapshot.change_10d),
        "volume_ratio_5d": _format_nullable_float(indicator_snapshot.volume_ratio_5d),
        "breakout_level": _format_nullable_float(indicator_snapshot.breakout_level),
        "breakdown_level": _format_nullable_float(indicator_snapshot.breakdown_level),
        "strongest_bullish": _format_signal_row(bullish_signals[0] if bullish_signals else None),
        "strongest_bearish": _format_signal_row(bearish_signals[0] if bearish_signals else None),
        "signals": [
            {
                "name": signal.name,
                "direction": signal.direction.value,
                "direction_label": _DIRECTION_LABELS[signal.direction.value],
                "score": f"{signal.score:.2f}",
                "summary": signal.summary,
                "evidence": list(signal.evidence[:2]),
            }
            for signal in analysis_result.signals
        ],
        "warnings": list(analysis_result.warnings),
    }


def _empty_technical_summary() -> dict[str, object]:
    return {
        "status": "idle",
        "message": None,
        "trend_direction": "neutral",
        "trend_label": _DIRECTION_LABELS["neutral"],
        "market_regime": None,
        "market_regime_label": "暂无",
        "confirmation_score": None,
        "bullish_score": None,
        "bearish_score": None,
        "analyzed_bar_count": 0,
        "latest_trade_date": None,
        "latest_close": None,
        "latest_change_percent": None,
        "sma_20": None,
        "sma_60": None,
        "change_5d": None,
        "change_10d": None,
        "volume_ratio_5d": None,
        "breakout_level": None,
        "breakdown_level": None,
        "strongest_bullish": None,
        "strongest_bearish": None,
        "signals": [],
        "warnings": [],
    }


def _collect_target_sentiment(
    *,
    company: CompanyReference | None,
    entity_mapping_service: object,
) -> tuple[list[SentimentItem], list[dict[str, object]], dict[str, object]]:
    if company is None:
        return [], [], {
            "status": "idle",
            "label": "未采集",
            "message": "解析到股票后会显示舆情来源健康状态。",
            "failed_source_count": 0,
            "total_source_count": 0,
            "reason_summary": [],
            "failures": [],
        }

    snapshot = _load_sentiment_snapshot(symbols=[company.symbol])
    sentiment_result = snapshot["ingestion_result"]
    source_runs = [_normalize_snapshot_source_run(run) for run in _snapshot_source_runs(sentiment_result)]
    source_failure_summary = _build_sentiment_failure_summary(
        ingestion_result=sentiment_result,
        source_runs=source_runs,
        checked_at=str(snapshot["latest_update"]),
    )
    source_failure_summary["mode"] = str(snapshot["mode"])
    source_failure_summary["fallback_used"] = bool(snapshot["fallback_used"])
    matched_rows: list[dict[str, object]] = []
    for item in _snapshot_items(sentiment_result):
        matches = entity_mapping_service.map_sentiment_item(item, min_confidence=0.18, max_matches=3)
        for match in matches:
            if match.company.symbol == company.symbol:
                matched_rows.append({"item": item, "match": match})
                break
    return [row["item"] for row in matched_rows], matched_rows, source_failure_summary


def _build_worker_health_summary(
    *,
    sentiment_latest_update: str | None,
    sentiment_mode: str,
    sentiment_status: str,
    research_symbol: str | None = None,
) -> dict[str, object]:
    monitoring_status = _safe_monitoring_status_snapshot()
    recent_activity = (
        _build_recent_activity(research_symbol, limit=1)
        if research_symbol
        else _build_recent_activity(limit=1)
    )
    latest_analysis = recent_activity[0]["created_at"] if recent_activity else None
    sentiment_label = {
        "persistent": "持久化快照",
        "request": "请求时计算",
        "idle": "待触发",
    }.get(sentiment_mode, sentiment_mode)
    return {
        "monitoring": {
            "label": "监控调度",
            "mode": monitoring_status["label"],
            "latest_update": monitoring_status["tick_at"],
            "status": "healthy" if monitoring_status["mode"] == "embedded" else "passive",
            "description": "关注列表自动刷新由常驻调度器驱动；未内嵌时由外部进程或手动触发。",
        },
        "sentiment": {
            "label": "舆情聚合",
            "mode": sentiment_label,
            "latest_update": sentiment_latest_update,
            "status": sentiment_status,
            "description": "优先读取持久化结果；不可用时回退到页面请求阶段的实时采集。",
        },
        "research": {
            "label": "研究计算",
            "mode": "请求时计算",
            "latest_update": latest_analysis,
            "status": "healthy" if latest_analysis else "passive",
            "description": "行情、技术分析与推荐链路在访问研究页时计算，最近研究动作会写入历史。",
        },
    }


def _build_evaluation_report(
    *,
    symbol: str | None = None,
    recent_runs: list[dict[str, object]] | None = None,
):
    sentiment_repository = current_app.config.get("TRADER_SENTIMENT_REPOSITORY")
    sentiment_worker_state = (
        sentiment_repository.get_worker_state()
        if sentiment_repository is not None and hasattr(sentiment_repository, "get_worker_state")
        else None
    )
    latest_sentiment_run = (
        sentiment_repository.get_latest_run()
        if sentiment_repository is not None and hasattr(sentiment_repository, "get_latest_run")
        else None
    )
    latest_source_failures = (
        sentiment_repository.list_source_failures(run_id=latest_sentiment_run.id)
        if sentiment_repository is not None
        and latest_sentiment_run is not None
        and hasattr(sentiment_repository, "list_source_failures")
        else []
    )
    resolved_recent_runs = recent_runs if recent_runs is not None else _build_recent_activity(symbol, limit=12)
    return build_recommendation_review_report(
        watchlist_rows=_watchlist_repository().list_rows(),
        recommendation_events=_recommendation_event_repository().list_recent(
            limit=12,
            symbol=symbol,
        ),
        recent_runs=resolved_recent_runs,
        unread_alerts=_alert_repository().list_unread(),
        sentiment_worker_state=sentiment_worker_state,
        latest_source_failures=latest_source_failures,
    )


def _build_sentiment_summary(matched_sentiment: list[dict[str, object]]) -> dict[str, object]:
    if not matched_sentiment:
        return {
            "status": "empty",
            "message": "当前样例舆情源中没有稳定映射到该股票的内容。",
            "item_rows": [],
            "mapped_count": 0,
            "average_score": None,
            "latest_published_at": None,
            "sources": [],
        }

    items = [row["item"] for row in matched_sentiment]
    scores = [item.sentiment_score for item in items if item.sentiment_score is not None]
    return {
        "status": "ready",
        "message": None,
        "item_rows": [
            {
                "title": item.title,
                "source": item.source,
                "published_at": item.published_at.strftime("%m-%d %H:%M"),
                "score": _format_sentiment_score(item.sentiment_score),
                "tags": list(item.tags[:3]),
                "url": item.url,
            }
            for item in items[:4]
        ],
        "mapped_count": len(items),
        "average_score": _format_sentiment_score(mean(scores)) if scores else "--",
        "latest_published_at": max(item.published_at for item in items).strftime("%Y-%m-%d %H:%M"),
        "sources": list(dict.fromkeys(item.source for item in items)),
    }


def _empty_sentiment_summary() -> dict[str, object]:
    return {
        "status": "idle",
        "message": None,
        "item_rows": [],
        "mapped_count": 0,
        "average_score": None,
        "latest_published_at": None,
        "sources": [],
    }


def _build_mapping_summary(matched_sentiment: list[dict[str, object]]) -> dict[str, object]:
    if not matched_sentiment:
        return {
            "status": "empty",
            "message": "暂无可用于展示的实体映射结果。",
            "average_confidence": None,
            "top_evidence": [],
        }

    matches = [row["match"] for row in matched_sentiment]
    evidence: list[str] = []
    for match in matches[:3]:
        evidence.extend(match.evidence[:2])
    return {
        "status": "ready",
        "message": None,
        "average_confidence": f"{mean(match.confidence for match in matches):.0%}",
        "top_evidence": list(dict.fromkeys(evidence))[:4],
    }


def _empty_mapping_summary() -> dict[str, object]:
    return {
        "status": "idle",
        "message": None,
        "average_confidence": None,
        "top_evidence": [],
    }


def _build_recommendation_summary(
    *,
    recommendation_bundle: RecommendationBundle,
    sentiment_count: int,
) -> dict[str, object]:
    recommendation = recommendation_bundle.recommendation
    decision_trace = recommendation_bundle.decision_trace
    agent_recommendation = recommendation.agent_recommendation
    return {
        "status": "ready",
        "message": None,
        "action": recommendation.action.value,
        "action_label": _ACTION_LABELS[recommendation.action.value],
        "confidence": f"{recommendation.confidence:.0%}",
        "summary": recommendation.summary,
        "agent_thesis": agent_recommendation.thesis if agent_recommendation is not None else None,
        "agent_confidence": (
            f"{agent_recommendation.confidence:.0%}"
            if agent_recommendation is not None
            else None
        ),
        "evidence": list(decision_trace.evidence_summary[:5]),
        "conflicts": list(decision_trace.conflicts),
        "risk_notes": list(recommendation.risk_notes[:6]),
        "trigger_conditions": (
            list(agent_recommendation.trigger_conditions[:3])
            if agent_recommendation is not None
            else []
        ),
        "invalidation_conditions": (
            list(agent_recommendation.invalidation_conditions[:3])
            if agent_recommendation is not None
            else []
        ),
        "generated_at": decision_trace.generated_at.strftime("%Y-%m-%d %H:%M"),
        "technical_signal_count": len(recommendation.technical_signals),
        "sentiment_count": sentiment_count,
        "decision_score": f"{decision_trace.final_score:+.2f}",
    }


def _empty_recommendation_summary() -> dict[str, object]:
    return {
        "status": "idle",
        "message": None,
        "action": None,
        "action_label": None,
        "confidence": None,
        "summary": None,
        "agent_thesis": None,
        "agent_confidence": None,
        "evidence": [],
        "conflicts": [],
        "risk_notes": [],
        "trigger_conditions": [],
        "invalidation_conditions": [],
        "generated_at": None,
        "technical_signal_count": 0,
        "sentiment_count": 0,
        "decision_score": None,
    }


def _format_signal_row(signal: object | None) -> dict[str, object] | None:
    if signal is None:
        return None
    return {
        "name": signal.name,
        "summary": signal.summary,
        "score": f"{signal.score:.2f}",
    }


def _format_percent(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:+.2f}%"


def _format_nullable_float(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def _format_large_number(value: float | None) -> str | None:
    if value is None:
        return None
    abs_value = abs(value)
    if abs_value >= 100000000:
        return f"{value / 100000000:.2f}亿"
    if abs_value >= 10000:
        return f"{value / 10000:.2f}万"
    return f"{value:.0f}"


def _format_sentiment_score(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:+.2f}"
