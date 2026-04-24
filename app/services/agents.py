from __future__ import annotations

from ..config import MCP_BUS_URL, PROFILE_NAME_RE, now_iso
from ..models.store import RuntimeStore
from . import acp, profiles, registry, soul


VALID_ROLES = {"leader", "worker"}


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

    profiles.create_hermes_profile(profile_name)

    if role == "leader":
        profiles.attach_mcp_server(
            profile_name, name="agent_bus", url=MCP_BUS_URL
        )
        profiles.disable_conflicting_toolsets(profile_name)

    created_at = now_iso()
    meta = {
        "name": name,
        "role": role,
        "description": description,
        "is_leader": role == "leader",
        "created_at": created_at,
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
    acp.pool.start(agent)
    return agent


def delete_agent(store: RuntimeStore, agent_id: str) -> dict:
    agent = store.find_agent(agent_id)
    if agent is None:
        raise ValueError("agent not found")
    profile_name = agent["profile_name"]
    acp.pool.stop(agent_id)
    profiles.delete_hermes_profile(profile_name)
    registry.delete_team_meta(profile_name)  # no-op if the profile dir was already gone
    store.remove_agent(agent_id)
    store.push_event(
        "agent.deleted",
        agent_id,
        None,
        {"text": f"Agent {agent['name']} 已删除（profile={profile_name}）"},
    )
    return agent
