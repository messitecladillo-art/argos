import atexit
import threading

from a2wsgi import ASGIMiddleware
from flask import Flask
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from .controllers import register_blueprints
from .mcp_server import mcp_asgi_app, start_session_manager
from .models.store import store
from .services import registry
from .services.acp import pool as session_pool


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        TEMPLATES_AUTO_RELOAD=True,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )
    registry.bootstrap(store)
    register_blueprints(app)
    start_session_manager()

    # Leader sessions load MCP tools from their Hermes profile, so wait until
    # Flask is accepting connections before starting long-lived CLI sessions.
    def _deferred_start() -> None:
        for agent in list(store.agents):
            if (agent.get("readiness_status") or "ready") != "ready":
                continue
            session_pool.start(agent)

    threading.Timer(2.0, _deferred_start).start()
    atexit.register(session_pool.stop_all)

    app.wsgi_app = DispatcherMiddleware(
        app.wsgi_app, {"/mcp": ASGIMiddleware(mcp_asgi_app)}
    )
    return app
