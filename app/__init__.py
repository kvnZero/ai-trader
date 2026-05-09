from flask import Flask

from app.config import get_settings
from app.routes import bp as core_blueprint

def create_app() -> Flask:
    app = Flask(__name__)
    settings = get_settings()

    app.config["TRADER_SETTINGS"] = settings
    app.register_blueprint(core_blueprint)

    return app
