import logging
import sys
from pathlib import Path

from flask import Flask

from .logging_config import setup_logging

setup_logging()

logger = logging.getLogger("argos")

from .config import validate_config  # noqa: E402
from .controllers import register_blueprints  # noqa: E402
from .db import init_database  # noqa: E402
from .learning import trace_collector, memory_store, feedback_engine, active_engine, ab_evaluator
from .mcp_server import start_session_manager
from .middleware.errors import (
    install_signal_handlers,
    register_error_handlers,
    register_shutdown_hook,
)
from .services.acp import pool as session_pool
from .models.store import store
from .services.autostart import start_ready_agents_on_boot
from .services import registry
from .services.kanban_dispatch import dispatch_worker
from .services.kanban_sync import sync_worker


def create_app() -> Flask:
    issues = validate_config()
    if issues:
        for msg in issues:
            logger.error("Config error: %s", msg)
        sys.exit(1)

    app = Flask(__name__)
    app.config.update(
        TEMPLATES_AUTO_RELOAD=True,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )
    register_error_handlers(app)
    install_signal_handlers()
    init_database()

    @app.context_processor
    def inject_asset_version():
        def asset_version(filename: str) -> str:
            static_root = Path(app.static_folder or "")
            paths = [static_root / filename]
            if filename == "styles.css":
                paths.extend((static_root / "css").glob("*.css"))
            mtimes = []
            for path in paths:
                try:
                    mtimes.append(int(path.stat().st_mtime))
                except OSError:
                    continue
            return str(max(mtimes, default=0))

        return {"asset_version": asset_version}

    store.load_persisted_state()
    registry.bootstrap(store)

    # Initialize self-evolving learning system
    try:
        trace_collector.init_app(store)
        memory_store.init_app(store)
        feedback_engine.init_app(store, memory_store)
        active_engine.init_app(store, memory_store)
        ab_evaluator.init_app(store)
    except Exception:
        pass  # learning is optional, never block app startup

    register_blueprints(app)
    start_ready_agents_on_boot()
    start_session_manager()
    sync_worker.start()
    dispatch_worker.start()

    register_shutdown_hook("kanban_sync", sync_worker.stop)
    register_shutdown_hook("kanban_dispatch", dispatch_worker.stop)
    register_shutdown_hook("acp_pool", session_pool.stop_all)
    register_shutdown_hook("learning_memory", memory_store.shutdown)
    register_shutdown_hook("learning_feedback", feedback_engine.shutdown)

    return app
