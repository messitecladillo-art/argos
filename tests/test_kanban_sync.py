from __future__ import annotations

from app.models.store import RuntimeStore
from app.services.kanban_sync import KanbanSyncWorker


def _agent(agent_id: str, profile_name: str, role: str, workspace_path: str | None = None) -> dict:
    return {
        "agent_id": agent_id,
        "profile_name": profile_name,
        "name": profile_name.title(),
        "role": role,
        "description": "",
        "is_leader": role == "leader",
        "workspace_path": workspace_path or f"/tmp/{profile_name}",
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
        "readiness_status": "ready",
        "readiness_message": "",
        "created_at": "2026-04-26T00:00:00Z",
        "last_active_at": "2026-04-26T00:00:00Z",
    }


class FakeKanban:
    def __init__(self, tasks):
        self.tasks = tasks
        self.created = []

    def show_task(self, task_id):
        return self.tasks[task_id]

    def create_task(self, title, **kwargs):
        self.created.append({"title": title, **kwargs})
        return {"task_id": "kb_summary", "status": "ready"}


def test_worker_done_creates_summary_once(tmp_path):
    runtime_store = RuntimeStore()
    leader_workspace = tmp_path / "lead"
    runtime_store.register_agent(_agent("agent_lead", "lead", "leader", str(leader_workspace)))
    runtime_store.register_agent(_agent("agent_dev", "dev", "worker"))
    user_task = runtime_store.create_user_task(leader_agent_id="agent_lead", content="Build")
    delegation = runtime_store.create_delegation(
        leader_agent_id="agent_lead",
        assignments=[{"to_agent_id": "agent_dev", "content": "Implement"}],
        summary_instruction="Summarize",
        user_task_id=user_task["user_task_id"],
    )
    assignment = delegation["assignments"][0]
    runtime_store.close_user_task_dispatch(user_task["user_task_id"])
    runtime_store.upsert_kanban_task_link(
        local_type="assignment",
        local_id=assignment["assignment_id"],
        kanban_task_id="kb_worker",
        kanban_role="worker",
        kanban_status="running",
        assignee_profile="dev",
        parent_local_id=user_task["user_task_id"],
        metadata={"delegation_id": delegation["delegation_id"]},
    )

    service = FakeKanban({"kb_worker": {"task_id": "kb_worker", "status": "done", "result": "done"}})
    worker = KanbanSyncWorker(runtime_store=runtime_store, service=service, interval=1)

    worker.sync_once()
    worker.sync_once()

    updated_assignment = runtime_store.snapshot()["delegations"][0]["assignments"][0]
    assert updated_assignment["status"] == "completed"
    assert updated_assignment["result"] == "done"
    assert len(service.created) == 1
    assert service.created[0]["workspace"] == f"dir:{leader_workspace}"
    assert leader_workspace.is_dir()
    assert runtime_store.find_kanban_task_link(
        local_type="user_task",
        local_id=user_task["user_task_id"],
        kanban_role="summary",
    )["kanban_task_id"] == "kb_summary"


def test_summary_done_completes_user_task():
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_lead", "lead", "leader"))
    user_task = runtime_store.create_user_task(leader_agent_id="agent_lead", content="Build")
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id=user_task["user_task_id"],
        kanban_task_id="kb_summary",
        kanban_role="summary",
        kanban_status="running",
        assignee_profile="lead",
        parent_local_id=user_task["user_task_id"],
        metadata={"user_task_id": user_task["user_task_id"]},
    )

    service = FakeKanban({"kb_summary": {"task_id": "kb_summary", "status": "done", "result": "final"}})
    worker = KanbanSyncWorker(runtime_store=runtime_store, service=service, interval=1)

    worker.sync_once()

    assert runtime_store.snapshot()["user_tasks"][0]["status"] == "completed"
