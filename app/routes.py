from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template

from app.config import Settings
from app.domain.serialization import to_json_ready
from app.modules import build_capability_catalog

bp = Blueprint("core", __name__)


def _settings() -> Settings:
    return current_app.config["TRADER_SETTINGS"]


@bp.get("/")
def index() -> str:
    settings = _settings()
    capabilities = build_capability_catalog(settings)
    return render_template("index.html", capabilities=capabilities, settings=settings)


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
