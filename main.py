import os

from app import create_app


app = create_app()


if __name__ == "__main__":
    settings = app.config["TRADER_SETTINGS"]
    app.run(
        host=os.getenv("TRADER_WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("TRADER_WEB_PORT", "5000")),
        debug=settings.debug,
    )
