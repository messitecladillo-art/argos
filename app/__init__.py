from flask import Flask
from pathlib import Path

from .controllers import register_blueprints
from .db import init_database
from .mcp_server import start_session_manager
from .models.store import store
from .services.autostart import start_ready_agents_on_boot
from .services import registry
from .services.kanban_dispatch import dispatch_worker
from .services.kanban_sync import sync_worker


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        TEMPLATES_AUTO_RELOAD=True,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )
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
    register_blueprints(app)
    start_ready_agents_on_boot()
    start_session_manager()
    sync_worker.start()
    dispatch_worker.start()
    return app
