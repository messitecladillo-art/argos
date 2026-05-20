from __future__ import annotations

from flask import Flask

from app.controllers import kanban as kanban_controller
from app.models.store import RuntimeStore


def _agent(agent_id: str, profile_name: str, workspace_path: str | None = None) -> dict:
    return {
        "agent_id": agent_id,
        "profile_name": profile_name,
        "name": profile_name.title(),
        "role": "leader",
        "description": "",
        "is_leader": True,
        "workspace_path": workspace_path or f"/tmp/{profile_name}",
        "status": "idle",
        "current_task": "空闲",
        "runtime_status": "running",
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


def test_answer_human_input_creates_continuation_task(monkeypatch, tmp_path):
    runtime_store = RuntimeStore()
    workspace_path = tmp_path / "lead_workspace"
    runtime_store.register_agent(_agent("agent_lead", "lead", str(workspace_path)))
    runtime_store.upsert_kanban_task_link(
        local_type="human_input",
        local_id="kb_human_1",
        kanban_task_id="kb_human_1",
        kanban_role="human_input",
        kanban_status="waiting_human",
        metadata={
            "kind": "human_input",
            "question": "是否继续部署？",
            "context": "测试已通过。",
            "requester_agent_id": "agent_lead",
            "requester_profile": "lead",
            "parent_task_id": "kb_parent",
            "user_task_id": "ut_0001",
        },
    )
    monkeypatch.setattr(kanban_controller, "store", runtime_store)
    monkeypatch.setattr(kanban_controller.human_input_service, "runtime_store", runtime_store, raising=False)

    created = []
    completed = []

    def fake_create_task(title, **kwargs):
        created.append({"title": title, **kwargs})
        return {"task_id": "kb_continue_1", "status": "ready"}

    def fake_complete_task(task_id, **kwargs):
        completed.append({"task_id": task_id, **kwargs})
        return "completed"

    monkeypatch.setattr(kanban_controller.human_input_service.kanban_service, "create_task", fake_create_task, raising=False)
    monkeypatch.setattr(kanban_controller.human_input_service.kanban_service, "complete_task", fake_complete_task, raising=False)

    app = Flask(__name__)
    app.register_blueprint(kanban_controller.bp)
    client = app.test_client()

    response = client.post("/api/kanban/tasks/kb_human_1/answer", json={"answer": "继续，今晚 22:00 上线。"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["continuation_task_id"] == "kb_continue_1"
    assert created[0]["assignee"] == "lead"
    assert created[0]["parent"] == "kb_human_1"
    assert created[0]["workspace"] == f"dir:{workspace_path.resolve()}"
    assert "继续，今晚 22:00 上线。" in created[0]["body"]
    assert completed[0]["task_id"] == "kb_human_1"
    human_link = runtime_store.find_kanban_task_link(kanban_task_id="kb_human_1")
    assert human_link["kanban_status"] == "done"
    assert human_link["metadata"]["answer"] == "继续，今晚 22:00 上线。"
    continuation_link = runtime_store.find_kanban_task_link(kanban_task_id="kb_continue_1")
    assert continuation_link["kanban_role"] == "human_continuation"
    assert continuation_link["assignee_profile"] == "lead"
