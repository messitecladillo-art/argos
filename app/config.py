from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path


UTC = timezone.utc
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
MCP_BUS_URL = os.environ.get(
    "HERMES_AGENTS_MCP_URL", "http://127.0.0.1:5050/mcp/"
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
