from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path


UTC = timezone.utc
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
AGENT_TEAM_WORKSPACE_ROOT = Path(
    os.environ.get("AGENT_TEAM_WORKSPACE_ROOT", "/Users/liuwenbin/agent_team")
).expanduser().resolve(strict=False)
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{(Path(__file__).resolve().parents[1] / 'data' / 'hermes_agent_team.db')}",
)
MCP_BUS_URL = os.environ.get(
    "HERMES_AGENTS_MCP_URL", "http://127.0.0.1:5050/mcp/"
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
