from flask import Flask

from app.workers.runtime import (
    InactiveMonitoringScheduler,
    build_monitoring_scheduler,
    build_worker_runtime,
    embedded_monitoring_enabled,
)
from app.persistence import PortfolioSettingsRepository, RecommendationSnapshotRepository, SentimentRepository
from app.routes import bp as core_blueprint

def create_app() -> Flask:
    app = Flask(__name__)
    runtime = build_worker_runtime()
    scheduler = InactiveMonitoringScheduler()
    if embedded_monitoring_enabled():
        _, scheduler = build_monitoring_scheduler(
            settings=runtime.settings,
            interval_seconds=300,
        )
        scheduler.start()

    app.config["TRADER_SETTINGS"] = runtime.settings
    app.config["TRADER_DATABASE"] = runtime.watchlist_repository.database
    app.config["TRADER_WATCHLIST_REPOSITORY"] = runtime.watchlist_repository
    app.config["TRADER_ALERT_REPOSITORY"] = runtime.alert_repository
    app.config["TRADER_ISSUE_LEDGER_REPOSITORY"] = runtime.issue_repository
    app.config["TRADER_RECOMMENDATION_EVENT_REPOSITORY"] = runtime.recommendation_event_repository
    app.config["TRADER_PORTFOLIO_SETTINGS_REPOSITORY"] = PortfolioSettingsRepository(runtime.watchlist_repository.database)
    app.config["TRADER_RECOMMENDATION_SNAPSHOT_REPOSITORY"] = RecommendationSnapshotRepository(runtime.watchlist_repository.database)
    app.config["TRADER_SENTIMENT_REPOSITORY"] = SentimentRepository(
        runtime.watchlist_repository.database,
        issue_repository=runtime.issue_repository,
    )
    app.config["TRADER_SENTIMENT_CACHE_READER"] = app.config["TRADER_SENTIMENT_REPOSITORY"]
    app.config["TRADER_WATCHLIST_REFRESH_SERVICE"] = runtime.refresh_service
    app.config["TRADER_MONITORING_SCHEDULER"] = scheduler
    app.config["TRADER_EMBEDDED_MONITORING_ENABLED"] = embedded_monitoring_enabled()
    app.register_blueprint(core_blueprint)

    return app
