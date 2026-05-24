from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .services.secrets import load_docker_secrets, load_env_file

# Load .env and Docker secrets early so os.environ is populated for all modules.
load_env_file()
_docker_secrets = load_docker_secrets()
for _k, _v in _docker_secrets.items():
    if _k not in os.environ:
        os.environ[_k] = _v

UTC = timezone.utc
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
AGENT_TEAM_WORKSPACE_ROOT = Path(
    os.environ.get("AGENT_TEAM_WORKSPACE_ROOT", str(Path.home() / "agent_team"))
).expanduser().resolve(strict=False)
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{(Path(__file__).resolve().parents[1] / 'data' / 'argos.db')}",
)
MCP_BUS_URL = os.environ.get(
    "HERMES_AGENTS_MCP_URL", "http://127.0.0.1:5050/mcp/"
)
KANBAN_BOARD = os.environ.get("KANBAN_BOARD", "argos")
KANBAN_POLL_INTERVAL = float(os.environ.get("KANBAN_POLL_INTERVAL", "2"))
KANBAN_DEFAULT_WORKSPACE = os.environ.get("KANBAN_DEFAULT_WORKSPACE", "scratch")
KANBAN_AUTO_DISPATCH = os.environ.get("KANBAN_AUTO_DISPATCH", "0") == "1"
AUTO_START_AGENTS = os.environ.get("AUTO_START_AGENTS", "1") != "0"
DEFAULT_MAX_TASK_ROUNDS = 10

# Application secret key (auto-generated in dev, must be set in production).
# Used for session signing and optional API-key encryption.
SECRET_KEY = os.environ.get("SECRET_KEY") or os.environ.get("HERMES_SECRET_KEY")
_is_production = os.environ.get("FLASK_DEBUG", "0") != "1"
if not SECRET_KEY and _is_production:
    import warnings

    warnings.warn(
        "SECRET_KEY is not set. A random key will be generated but will not "
        "survive restarts. Set SECRET_KEY in your environment for production.",
        RuntimeWarning,
    )


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def validate_config() -> list[str]:
    """Validate critical configuration. Returns list of issues (empty = ok)."""
    issues: list[str] = []

    # SECRET_KEY check for production
    _is_prod = os.environ.get("FLASK_DEBUG", "0") != "1"
    if _is_prod and not SECRET_KEY:
        issues.append("SECRET_KEY is not set — generate with: python -c \"import secrets; print(secrets.token_hex(32))\"")

    # DATABASE_URL basic sanity
    if DATABASE_URL.startswith("sqlite:///"):
        db_path = DATABASE_URL.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            db_dir = Path(db_path).expanduser().resolve(strict=False).parent
            try:
                db_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                issues.append(f"Cannot create database directory {db_dir}: {exc}")

    # HERMES_HOME sanity
    try:
        HERMES_HOME.expanduser().resolve(strict=False)
    except Exception as exc:
        issues.append(f"HERMES_HOME path error: {exc}")

    return issues
