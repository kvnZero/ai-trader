from flask import Flask

from app.config import get_settings
from app.persistence import AlertRepository, WatchlistRepository, init_database
from app.routes import bp as core_blueprint

def create_app() -> Flask:
    app = Flask(__name__)
    settings = get_settings()
    database = init_database(settings.database_path)
    watchlist_repository = WatchlistRepository(database)
    alert_repository = AlertRepository(database)

    watchlist_repository.seed_defaults()
    alert_repository.seed_defaults()

    app.config["TRADER_SETTINGS"] = settings
    app.config["TRADER_DATABASE"] = database
    app.config["TRADER_WATCHLIST_REPOSITORY"] = watchlist_repository
    app.config["TRADER_ALERT_REPOSITORY"] = alert_repository
    app.register_blueprint(core_blueprint)

    return app
