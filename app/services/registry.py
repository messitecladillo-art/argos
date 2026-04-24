from __future__ import annotations

import json
from pathlib import Path

from ..config import HERMES_HOME, PROFILE_NAME_RE, now_iso


META_FILENAME = "team-meta.json"
META_FIELDS = ("name", "role", "description", "is_leader", "created_at")


def agent_id_for(profile_name: str) -> str:
    """Derive a stable agent_id from a profile name."""
    return f"agent_{profile_name}"


def _meta_path(profile_name: str) -> Path:
    return HERMES_HOME / "profiles" / profile_name / META_FILENAME


def write_team_meta(profile_name: str, meta: dict) -> None:
    path = _meta_path(profile_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: meta.get(k) for k in META_FIELDS}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_team_meta(profile_name: str) -> None:
    path = _meta_path(profile_name)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _hydrate(profile_name: str, meta: dict) -> dict:
    created_at = meta.get("created_at") or now_iso()
    return {
        "agent_id": agent_id_for(profile_name),
        "profile_name": profile_name,
        "name": meta.get("name") or profile_name,
        "role": meta.get("role") or "worker",
        "description": meta.get("description") or "",
        "is_leader": bool(meta.get("is_leader")),
        "status": "idle",
        "current_task": "空闲",
        "runtime_status": "stopped",
        "interaction_state": "idle",
        "queue_depth": 0,
        "pending_interaction": None,
        "load": 0,
        "last_input": "",
        "last_output": "",
        "last_output_at": "",
        "created_at": created_at,
        "last_active_at": created_at,
    }


def load_team_metas() -> list[dict]:
    """Scan `~/.hermes/profiles/*/team-meta.json` and return runtime agent dicts."""
    profiles_dir = HERMES_HOME / "profiles"
    if not profiles_dir.exists():
        return []
    agents: list[dict] = []
    for child in sorted(profiles_dir.iterdir()):
        if not child.is_dir():
            continue
        profile_name = child.name
        if not PROFILE_NAME_RE.match(profile_name):
            continue
        meta_file = child / META_FILENAME
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        agents.append(_hydrate(profile_name, meta))
    return agents


def bootstrap(store) -> None:
    """Populate a RuntimeStore from disk. Called once on app startup."""
    for agent in load_team_metas():
        store.register_agent(agent)
