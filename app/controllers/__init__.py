from __future__ import annotations

from flask import Flask

from .agents import bp as agents_bp
from .events import bp as events_bp
from .messages import bp as messages_bp
from .web import bp as web_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(web_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(events_bp)
