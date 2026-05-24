from __future__ import annotations


def is_agent_ready(agent: dict | None) -> bool:
    return bool(agent) and (agent.get("readiness_status") or "ready") == "ready"


def is_agent_running(agent: dict | None) -> bool:
    return bool(agent) and (agent.get("runtime_status") or "stopped") == "running"


def is_agent_dispatchable(agent: dict | None) -> bool:
    return is_agent_ready(agent) and is_agent_running(agent)


def agent_dispatch_block_reason(agent: dict | None) -> str:
    if not agent:
        return "agent not found"
    readiness = agent.get("readiness_status") or "ready"
    if readiness != "ready":
        return f"agent is not ready: {readiness}"
    runtime = agent.get("runtime_status") or "stopped"
    if runtime != "running":
        return f"agent is not running: {runtime}"
    return ""


def find_agent_by_profile(agents: list[dict], profile_name: str) -> dict | None:
    value = (profile_name or "").strip()
    if not value:
        return None
    return next((agent for agent in agents if agent.get("profile_name") == value), None)
