from __future__ import annotations

from flask import Flask

from app.controllers import messages as messages_controller
from app.models.store import RuntimeStore


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


def test_messages_create_kanban_parent_without_acp(monkeypatch, tmp_path):
    runtime_store = RuntimeStore()
    workspace_path = tmp_path / "leader_profile"
    runtime_store.register_agent(_agent("agent_lead", "leader_profile", "leader", str(workspace_path)))
    monkeypatch.setattr(messages_controller, "store", runtime_store)

    created = {}

    def fake_create_task(title, **kwargs):
        created.update({"title": title, **kwargs})
        return {"task_id": "kb_parent", "status": "ready"}

    monkeypatch.setattr(messages_controller.messages_service.kanban_service, "create_task", fake_create_task)

    app = Flask(__name__)
    app.register_blueprint(messages_controller.bp)
    client = app.test_client()

    response = client.post("/api/messages", json={"content": "Build login"})

    assert response.status_code == 201
    data = response.get_json()
    assert data["message"]["user_task_id"] == "ut_0001"
    assert data["message"]["kanban_task_id"] == "kb_parent"
    assert created["assignee"] is None
    assert created["workspace"] == f"dir:{workspace_path}"
    assert workspace_path.is_dir()
    assert "mcp_agent_bus_create_kanban_worker_tasks" in created["body"]
    assert "严禁使用内置 kanban_create" in created["body"]
    assert "创建 worker 子任务后，必须立即调用 kanban_complete" in created["body"]
    assert "调度阶段已完成" in created["body"]
    link = runtime_store.find_kanban_task_link(
        local_type="user_task",
        local_id="ut_0001",
        kanban_role="parent",
    )
    assert link["kanban_task_id"] == "kb_parent"
    assert link["assignee_profile"] == "leader_profile"
