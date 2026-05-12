from __future__ import annotations

import shutil
from collections import deque
from itertools import count
from pathlib import Path

from sqlalchemy import select

from ..config import AGENT_TEAM_WORKSPACE_ROOT, now_iso
from ..db.models import (
    AgentRecord,
    AssignmentRecord,
    DelegationRecord,
    EventRecord,
    KanbanTaskLinkRecord,
    MessageRecord,
    UserTaskRecord,
)
from ..db.session import SessionLocal
from ..models.store import RuntimeStore
from . import registry
from .acp import pool as session_pool
from .kanban import KanbanError, kanban_service


class TeamInitializationError(RuntimeError):
    pass


RUNTIME_TABLES = (
    AssignmentRecord,
    DelegationRecord,
    UserTaskRecord,
    KanbanTaskLinkRecord,
    MessageRecord,
    EventRecord,
)
HISTORY_TABLE_NAMES = [model.__tablename__ for model in RUNTIME_TABLES]


def initialize_agents(
    store: RuntimeStore,
    *,
    clear_workspace: bool = True,
    clear_history: bool = True,
) -> dict:
    agents = store.snapshot().get("agents", [])
    archived_kanban = _archive_kanban_tasks(store) if clear_history else {"ok": True, "archived_count": 0, "errors": []}
    if not archived_kanban.get("ok", False):
        return {
            "ok": False,
            "results": [],
            "failed": 0,
            "kanban": archived_kanban,
            "cleared": {"agents": len(agents), "workspaces": 0, "history_tables": []},
            "agents": store.snapshot().get("agents", []),
        }
    results = []
    for agent in agents:
        results.append(_initialize_one_agent(agent, clear_workspace=clear_workspace))

    if clear_history:
        _clear_runtime_history(store)

    _reset_agent_runtime_state(store)
    store.push_agents_changed()
    failed = [item for item in results if not item.get("ok")]
    return {
        "ok": not failed and archived_kanban.get("ok", False),
        "results": results,
        "failed": len(failed),
        "kanban": archived_kanban,
        "cleared": {
            "agents": len(agents),
            "workspaces": sum(1 for item in results if item.get("workspace_cleared")),
            "history_tables": HISTORY_TABLE_NAMES if clear_history else [],
        },
        "agents": store.snapshot().get("agents", []),
}


def _archive_kanban_tasks(store: RuntimeStore) -> dict:
    task_ids = _linked_kanban_task_ids(store)
    try:
        for task in kanban_service.list_tasks(archived=False):
            task_id = _task_id(task)
            if task_id:
                task_ids.append(task_id)
    except KanbanError as exc:
        return {"ok": False, "archived_count": 0, "errors": [str(exc)]}

    ids = list(dict.fromkeys(task_ids))
    if not ids:
        return {"ok": True, "archived_count": 0, "errors": []}
    try:
        kanban_service.archive_tasks(ids)
    except KanbanError as exc:
        return {"ok": False, "archived_count": 0, "errors": [str(exc)]}
    return {"ok": True, "archived_count": len(ids), "errors": []}


def _linked_kanban_task_ids(store: RuntimeStore) -> list[str]:
    return [
        link.get("kanban_task_id") or ""
        for link in store.snapshot().get("kanban_task_links", [])
        if link.get("kanban_task_id")
    ]


def _task_id(task: dict) -> str:
    for key in ("task_id", "id"):
        value = task.get(key)
        if value:
            return str(value)
    return ""


def _initialize_one_agent(agent: dict, *, clear_workspace: bool) -> dict:
    agent_id = agent.get("agent_id") or ""
    name = agent.get("name") or agent_id
    result = {"agent_id": agent_id, "name": name, "ok": True, "workspace_cleared": False}
    try:
        session_pool.stop(agent_id)
    except Exception as exc:  # noqa: BLE001
        result["ok"] = False
        result["error"] = f"stop failed: {exc}"
        return result

    if not clear_workspace:
        return result

    try:
        _clear_agent_workspace(agent)
    except TeamInitializationError as exc:
        result["ok"] = False
        result["error"] = str(exc)
    else:
        result["workspace_cleared"] = True
    return result


def _clear_agent_workspace(agent: dict) -> None:
    profile_name = agent.get("profile_name") or ""
    raw_path = agent.get("workspace_path") or registry.workspace_path_for(profile_name)
    path = Path(raw_path).expanduser().resolve(strict=False)
    root = AGENT_TEAM_WORKSPACE_ROOT.resolve(strict=False)
    if path == root or root not in path.parents:
        raise TeamInitializationError(f"workspace path is outside agent team root: {path}")
    try:
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TeamInitializationError(f"clear workspace failed: {path}: {exc}") from exc


def _clear_runtime_history(store: RuntimeStore) -> None:
    with SessionLocal.begin() as session:
        for model in RUNTIME_TABLES:
            session.query(model).delete()
    with store._lock:
        store.user_tasks = []
        store.delegations = []
        store.kanban_task_links = []
        store.messages = deque(maxlen=200)
        store.events = deque(maxlen=400)
        store._event_ids = count(1)
        store._message_ids = count(1)
        store._user_task_ids = count(1)
        store._delegation_ids = count(1)
        store._assignment_ids = count(1)


def _reset_agent_runtime_state(store: RuntimeStore) -> None:
    timestamp = now_iso()
    runtime_patch = {
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
        "last_active_at": timestamp,
        "updated_at": timestamp,
    }
    with store._lock:
        for agent in store.agents:
            agent.update(runtime_patch)
    with SessionLocal.begin() as session:
        for record in session.scalars(select(AgentRecord).where(AgentRecord.deleted_at.is_(None))):
            record.status = "idle"
            record.current_task = "空闲"
            record.runtime_status = "stopped"
            record.interaction_state = "idle"
            record.orchestration_state = "none"
            record.queue_depth = 0
            record.pending_interaction_json = "null"
            record.load = 0
            record.last_input = ""
            record.last_output = ""
            record.last_output_at = ""
            record.last_active_at = timestamp
            record.updated_at = timestamp
