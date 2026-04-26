from __future__ import annotations

from flask import Flask

from app.controllers import agents as agents_controller
from app.models.store import RuntimeStore


def _client(monkeypatch, tmp_path):
    test_store = RuntimeStore()
    monkeypatch.setattr(agents_controller, "store", test_store)
    monkeypatch.setattr(agents_controller.registry, "HERMES_HOME", tmp_path / ".hermes")
    app = Flask(__name__)
    app.register_blueprint(agents_controller.bp)
    return app.test_client(), test_store


def _register_agent(store: RuntimeStore, profile_name: str = "dev") -> dict:
    agent = {
        "agent_id": f"agent_{profile_name}",
        "profile_name": profile_name,
        "name": "Dev",
        "role": "worker",
        "description": "",
        "is_leader": False,
        "workspace_path": "/tmp/dev",
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
        "readiness_message": "SOUL.md 已就绪",
        "created_at": "2026-04-26T00:00:00Z",
        "last_active_at": "2026-04-26T00:00:00Z",
    }
    store.register_agent(agent)
    return agent


def test_get_agent_soul_reads_existing_file(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)
    soul_path = agents_controller.registry.soul_path_for("dev")
    soul_path.parent.mkdir(parents=True)
    soul_path.write_text("# SOUL: Dev\n", encoding="utf-8")

    response = client.get("/api/agents/agent_dev/soul")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["content"] == "# SOUL: Dev\n"
    assert data["path"] == str(soul_path)
    assert data["updated_at"]
    assert data["agent"]["profile_name"] == "dev"


def test_put_agent_soul_saves_with_trailing_newline(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)

    response = client.put(
        "/api/agents/agent_dev/soul",
        json={"content": "# SOUL: Dev\n\n## Identity\nWorker"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    soul_path = agents_controller.registry.soul_path_for("dev")
    assert soul_path.read_text(encoding="utf-8").endswith("\n")
    assert data["content"].endswith("\n")
    assert store.find_agent("agent_dev")["readiness_status"] == "ready"


def test_put_agent_soul_rejects_empty_content(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)

    response = client.put("/api/agents/agent_dev/soul", json={"content": "  \n"})

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_put_agent_soul_rejects_preparing_agent(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    agent = _register_agent(store)
    agent["readiness_status"] = "preparing"

    response = client.put("/api/agents/agent_dev/soul", json={"content": "# SOUL: Dev"})

    assert response.status_code == 409
    assert response.get_json()["ok"] is False


def test_agent_soul_unknown_agent_returns_404(monkeypatch, tmp_path):
    client, _store = _client(monkeypatch, tmp_path)

    response = client.get("/api/agents/missing/soul")

    assert response.status_code == 404
    assert response.get_json()["error"] == "agent not found"
