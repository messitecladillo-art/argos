from __future__ import annotations

from flask import Flask

from app.controllers import agents as agents_controller
from app.models.store import RuntimeStore


def _agent(agent_id: str, *, ready: bool = True) -> dict:
    return {
        "agent_id": agent_id,
        "profile_name": agent_id,
        "name": agent_id,
        "role": "worker",
        "description": "",
        "is_leader": False,
        "workspace_path": f"/tmp/{agent_id}",
        "status": "offline",
        "current_task": "已停止",
        "runtime_status": "stopped",
        "interaction_state": "idle",
        "orchestration_state": "none",
        "queue_depth": 0,
        "pending_interaction": None,
        "load": 0,
        "last_input": "",
        "last_output": "",
        "last_output_at": "",
        "readiness_status": "ready" if ready else "missing_soul",
        "readiness_message": "ready" if ready else "missing",
        "created_at": "2026-04-26T00:00:00Z",
        "last_active_at": "2026-04-26T00:00:00Z",
    }


def test_bulk_runtime_starts_ready_agents_and_skips_unready(monkeypatch):
    test_store = RuntimeStore()
    test_store.register_agent(_agent("agent_ready"))
    test_store.register_agent(_agent("agent_unready", ready=False))
    started = []

    monkeypatch.setattr(agents_controller, "store", test_store)
    monkeypatch.setattr(agents_controller.session_pool, "start", lambda agent: started.append(agent["agent_id"]) or True)

    app = Flask(__name__)
    app.register_blueprint(agents_controller.bp)
    response = app.test_client().post("/api/agents/runtime", json={"action": "start"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["skipped"] == 1
    assert started == ["agent_ready"]
