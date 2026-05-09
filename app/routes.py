from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, current_app, jsonify, render_template, request

from app.config import Settings
from app.domain.serialization import to_json_ready
from app.modules import build_capability_catalog
from app.modules.market_data import build_default_market_data_service
from app.modules.market_data.contracts import MarketDataResult
from app.modules.technical_analysis import (
    TechnicalAnalysisValidationError,
    build_default_technical_analysis_service,
)

bp = Blueprint("core", __name__)

_WEB_NAVIGATION = (
    {"endpoint": "core.dashboard", "label": "总览", "description": "Dashboard"},
    {"endpoint": "core.research", "label": "个股研究", "description": "Research"},
    {"endpoint": "core.sentiment", "label": "舆情监控", "description": "Sentiment"},
    {"endpoint": "core.recommendations", "label": "交易员建议", "description": "Agent"},
    {"endpoint": "core.system_capabilities", "label": "系统能力", "description": "System"},
)


def _settings() -> Settings:
    return current_app.config["TRADER_SETTINGS"]


@bp.get("/")
def index() -> str:
    return dashboard()


@bp.get("/dashboard")
def dashboard() -> str:
    settings = _settings()
    capabilities = build_capability_catalog(settings)
    return render_template(
        "dashboard.html",
        capabilities=capabilities,
        settings=settings,
        navigation=_WEB_NAVIGATION,
        active_nav="core.dashboard",
    )


@bp.get("/research")
def research() -> str:
    return render_template(
        "research.html",
        navigation=_WEB_NAVIGATION,
        active_nav="core.research",
    )


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
    return render_template(
        "system.html",
        capabilities=capabilities,
        settings=settings,
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
