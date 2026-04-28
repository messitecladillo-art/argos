from __future__ import annotations

import shutil
from pathlib import Path

from ..config import AGENT_TEAM_WORKSPACE_ROOT, MCP_BUS_URL, PROFILE_NAME_RE, now_iso
from ..models.store import RuntimeStore
from . import acp, mcp_installer, profiles, registry, soul


VALID_ROLES = {"leader", "worker"}


def _safe_workspace_delete_path(workspace_path: str) -> Path:
    workspace_root = AGENT_TEAM_WORKSPACE_ROOT.resolve(strict=False)
    target = Path(workspace_path).expanduser().resolve(strict=False)
    if target == workspace_root or workspace_root not in target.parents:
        raise ValueError("workspace_path is outside the configured team workspace root")
    return target


def _delete_workspace(workspace_path: str) -> None:
    target = _safe_workspace_delete_path(workspace_path)
    if target.exists():
        shutil.rmtree(target)


def create_agent(
    store: RuntimeStore,
    *,
    name: str,
    profile_name: str,
    role: str = "worker",
    description: str = "",
) -> dict:
    """Validate input, create the hermes profile, write team-meta.json,
    register the agent, and kick off SOUL.md generation asynchronously."""
    name = name.strip()
    profile_name = profile_name.strip().lower()
    role = role.strip()
    description = description.strip()

    if not name:
        raise ValueError("name is required")
    if not PROFILE_NAME_RE.match(profile_name):
        raise ValueError(
            "profile_name must be lowercase alphanumeric (dash/underscore allowed)"
        )
    if role not in VALID_ROLES:
        raise ValueError("role must be one of leader/worker")

    if store.has_profile(profile_name):
        raise ValueError(f"profile '{profile_name}' is already registered")
    if role == "leader" and store.has_leader():
        raise ValueError("only one leader can exist")

    workspace_path = registry.ensure_workspace(profile_name)

    profiles.create_hermes_profile(profile_name)
    registry.skills_dir_for(profile_name).mkdir(parents=True, exist_ok=True)

    if role == "leader":
        profiles.attach_mcp_server(
            profile_name, name="agent_bus", url=MCP_BUS_URL
        )
        mcp_installer.upsert_builtin_agent_bus(profile_name)
        profiles.disable_conflicting_toolsets(profile_name)

    created_at = now_iso()
    meta = {
        "name": name,
        "role": role,
        "description": description,
        "is_leader": role == "leader",
        "created_at": created_at,
        "workspace_path": workspace_path,
    }
    registry.write_team_meta(profile_name, meta)

    agent = {
        "agent_id": registry.agent_id_for(profile_name),
        "profile_name": profile_name,
        "status": "idle",
        "current_task": "空闲",
        "runtime_status": "stopped",
        "interaction_state": "idle",
        "orchestration_state": "none",
        "queue_depth": 0,
        "pending_interaction": None,
        "load": 0,
        "last_input": "",
        "last_output": "",
        "last_output_at": "",
        "readiness_status": "preparing",
        "readiness_message": "正在生成 SOUL.md",
        "last_active_at": created_at,
        **meta,
    }
    store.register_agent(agent)
    store.push_event(
        "agent.created",
        agent["agent_id"],
        None,
        {"text": f"Agent {name} 已创建（profile={profile_name}），开始生成 SOUL.md…"},
    )
    store.push_agents_changed()

    soul.spawn_generate(
        store,
        agent_id=agent["agent_id"],
        name=name,
        role=role,
        description=description,
        profile_name=profile_name,
    )
    return agent


def delete_agent(store: RuntimeStore, agent_id: str) -> dict:
    agent = store.find_agent(agent_id)
    if agent is None:
        raise ValueError("agent not found")
    orchestration_state = agent.get("orchestration_state") or "none"
    if agent.get("status") != "idle" or orchestration_state != "none":
        raise ValueError("only idle agents can be dismissed")
    profile_name = agent["profile_name"]
    workspace_path = agent.get("workspace_path") or str(registry.workspace_path_for(profile_name))
    _safe_workspace_delete_path(workspace_path)
    acp.pool.stop(agent_id)
    profiles.delete_hermes_profile(profile_name)
    registry.delete_team_meta(profile_name)  # no-op if the profile dir was already gone
    mcp_installer.delete_records_for_profile(profile_name)
    _delete_workspace(workspace_path)
    store.remove_agent(agent_id)
    store.push_event(
        "agent.deleted",
        agent_id,
        None,
        {"text": f"Agent {agent['name']} 已解雇（profile={profile_name}）"},
    )
    return agent
