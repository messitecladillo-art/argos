from __future__ import annotations

from pathlib import Path

from ..config import KANBAN_DEFAULT_WORKSPACE
from . import registry


def workspace_for_agent(agent: dict | None) -> str:
    if not agent:
        return KANBAN_DEFAULT_WORKSPACE
    profile_name = (agent.get("profile_name") or "").strip()
    if not profile_name:
        return KANBAN_DEFAULT_WORKSPACE
    workspace_path = agent.get("workspace_path") or registry.workspace_path_for(profile_name)
    path = Path(registry.ensure_workspace(profile_name, workspace_path))
    return f"dir:{path}"
