from flask import Flask

from .controllers import register_blueprints
from .db import init_database
from .mcp_server import start_session_manager
from .models.store import store
from .services.autostart import start_ready_agents_on_boot
from .services import registry
from .services.kanban_sync import sync_worker


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        TEMPLATES_AUTO_RELOAD=True,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )
    init_database()
    store.load_persisted_state()
    registry.bootstrap(store)
    register_blueprints(app)
    start_ready_agents_on_boot()
    start_session_manager()
    sync_worker.start()
    return app
