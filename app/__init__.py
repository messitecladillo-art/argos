from flask import Flask

from .controllers import register_blueprints
from .models.store import store
from .services import registry


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        TEMPLATES_AUTO_RELOAD=True,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )
    registry.bootstrap(store)
    register_blueprints(app)
    return app
