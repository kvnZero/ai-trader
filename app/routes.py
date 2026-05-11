from __future__ import annotations

from datetime import date, datetime, time, timedelta
from statistics import mean
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for

from app.config import Settings
from app.domain import CompanyReference, MarketSnapshot, SentimentItem
from app.domain.serialization import to_json_ready
from app.modules import build_capability_catalog
from app.modules.entity_mapping import CompanyDictionary, CompanyDictionaryEntry, build_default_entity_mapping_service
from app.modules.entity_mapping.normalization import normalize_lookup_key
from app.modules.market_data import build_default_market_data_service
from app.modules.market_data.adapters import normalize_symbol
from app.modules.market_data.contracts import MarketDataResult
from app.modules.market_data.errors import MarketDataValidationError
from app.modules.recommendation_engine import RecommendationBundle, build_default_recommendation_engine_service
from app.modules.sentiment_ingestion import build_default_sentiment_service
from app.modules.technical_analysis import (
    TechnicalAnalysisValidationError,
    build_default_technical_analysis_service,
)
from app.modules.technical_analysis.contracts import TechnicalAnalysisResult
from app.modules.trader_agent import build_default_trader_agent_service
from app.persistence import AlertRepository, WatchlistRepository

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


def _monitoring_scheduler():
    return current_app.config["TRADER_MONITORING_SCHEDULER"]


@bp.get("/")
def index() -> str:
    return dashboard()


@bp.get("/dashboard")
def dashboard() -> str:
    settings = _settings()
    capabilities = build_capability_catalog(settings)
    watchlist = _build_watchlist_view_models()
    alerts = _build_alert_view_models()
    return render_template(
        "dashboard.html",
        capabilities=capabilities,
        settings=settings,
        watchlist=watchlist,
        alerts=alerts,
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
    return render_template(
        "research.html",
        query=query,
        workspace=workspace,
        watchlist_action=watchlist_action,
        navigation=_WEB_NAVIGATION,
        active_nav="core.research",
    )


@bp.post("/research/watchlist")
def research_add_watchlist_stock() -> str:
    symbol = request.form.get("symbol", "").strip()
    name = request.form.get("name", "").strip()
    if symbol and name:
        _watchlist_repository().create_stock(symbol, name)
    return redirect(url_for("core.research", query=symbol or name))


@bp.get("/sentiment")
def sentiment() -> str:
    return render_template(
        "sentiment.html",
        navigation=_WEB_NAVIGATION,
        active_nav="core.sentiment",
    )


@bp.get("/recommendations")
def recommendations() -> str:
    return render_template(
        "recommendations.html",
        navigation=_WEB_NAVIGATION,
        active_nav="core.recommendations",
    )


@bp.get("/system")
def system_capabilities() -> str:
    settings = _settings()
    capabilities = build_capability_catalog(settings)
    recent_runs = _watchlist_repository().list_recent_analysis_runs()
    monitoring_status = _monitoring_scheduler().status_snapshot()
    return render_template(
        "system.html",
        capabilities=capabilities,
        settings=settings,
        recent_runs=recent_runs,
        monitoring_status=monitoring_status,
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


@bp.get("/api/capabilities")
def capabilities() -> tuple[object, int]:
    settings = _settings()
    payload = build_capability_catalog(settings)
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


def _build_alert_view_models() -> list[dict[str, object]]:
    rows = _alert_repository().list_unread()
    return [
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
            sentiment_items, matched_sentiment = _collect_target_sentiment(
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
            workspace["sentiment"] = _build_sentiment_summary(matched_sentiment)
            workspace["mapping"] = _build_mapping_summary(matched_sentiment)

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
) -> tuple[list[SentimentItem], list[dict[str, object]]]:
    if company is None:
        return [], []

    sentiment_result = build_default_sentiment_service().ingest()
    matched_rows: list[dict[str, object]] = []
    for item in sentiment_result.items:
        matches = entity_mapping_service.map_sentiment_item(item, min_confidence=0.18, max_matches=3)
        for match in matches:
            if match.company.symbol == company.symbol:
                matched_rows.append({"item": item, "match": match})
                break
    return [row["item"] for row in matched_rows], matched_rows


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
