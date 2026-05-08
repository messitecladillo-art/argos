from __future__ import annotations

from app import mcp_server
from app.models.store import RuntimeStore
from app.services import mcp_installer


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


def test_leader_creates_worker_kanban_tasks(monkeypatch, tmp_path):
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_lead", "lead", "leader"))
    workspace_path = tmp_path / "dev_profile"
    runtime_store.register_agent(_agent("agent_dev", "dev_profile", "worker", str(workspace_path)))
    task = runtime_store.create_user_task(leader_agent_id="agent_lead", content="Build")
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id=task["user_task_id"],
        kanban_task_id="kb_parent",
        kanban_role="parent",
    )
    monkeypatch.setattr(mcp_server, "store", runtime_store)

    calls = []

    def fake_create_task(title, **kwargs):
        calls.append({"title": title, **kwargs})
        return {"task_id": f"kb_worker_{len(calls)}", "status": "ready"}

    monkeypatch.setattr(mcp_server.kanban_service, "create_task", fake_create_task, raising=False)

    result = mcp_server.create_kanban_worker_tasks(
        assignments=[{"to_agent_id": "agent_dev", "content": "Implement", "title": "Implement API"}],
        from_agent_id="agent_lead",
        user_task_id=task["user_task_id"],
        summary_instruction="Summarize",
    )

    assert result["ok"] is True
    assert result["assignments"][0]["kanban_task_id"] == "kb_worker_1"
    assert calls[0]["assignee"] == "dev_profile"
    assert calls[0]["parent"] == "kb_parent"
    assert calls[0]["workspace"] == f"dir:{workspace_path}"
    assert workspace_path.is_dir()


def test_list_workers_does_not_expose_workspace(monkeypatch):
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_dev", "dev_profile", "worker"))
    monkeypatch.setattr(mcp_server, "store", runtime_store)
    monkeypatch.setattr(mcp_installer, "mcp_summary", lambda profile_name: [])

    workers = mcp_server.list_workers()

    assert workers[0]["agent_id"] == "agent_dev"
    assert "workspace_path" not in workers[0]


def test_non_leader_cannot_create_kanban_tasks(monkeypatch):
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_dev", "dev_profile", "worker"))
    monkeypatch.setattr(mcp_server, "store", runtime_store)

    try:
        mcp_server.create_kanban_worker_tasks(
            assignments=[{"to_agent_id": "agent_dev", "content": "Implement"}],
            from_agent_id="agent_dev",
        )
    except ValueError as exc:
        assert "leader" in str(exc)
    else:
        raise AssertionError("expected ValueError")
