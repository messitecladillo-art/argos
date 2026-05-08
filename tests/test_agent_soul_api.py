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


def test_post_agent_soul_regenerate_starts_generation(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)
    calls = []

    def fake_spawn_generate(runtime_store, **kwargs):
        calls.append((runtime_store, kwargs))

    monkeypatch.setattr(agents_controller.soul_service, "spawn_generate", fake_spawn_generate)

    response = client.post("/api/agents/agent_dev/soul/regenerate")

    assert response.status_code == 202
    data = response.get_json()
    assert data["ok"] is True
    agent = store.find_agent("agent_dev")
    assert agent["readiness_status"] == "preparing"
    assert agent["readiness_message"] == "正在重新生成 SOUL.md"
    assert calls[0][0] is store
    assert calls[0][1]["agent_id"] == "agent_dev"
    assert calls[0][1]["profile_name"] == "dev"


def test_post_agent_soul_regenerate_rejects_preparing_agent(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    agent = _register_agent(store)
    agent["readiness_status"] = "preparing"

    response = client.post("/api/agents/agent_dev/soul/regenerate")

    assert response.status_code == 409
    assert response.get_json()["ok"] is False


def test_agent_soul_unknown_agent_returns_404(monkeypatch, tmp_path):
    client, _store = _client(monkeypatch, tmp_path)

    response = client.get("/api/agents/missing/soul")

    assert response.status_code == 404
    assert response.get_json()["error"] == "agent not found"


def test_open_agent_workspace_creates_directory_and_opens(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    workspace_path = tmp_path / "workspaces" / "dev"
    agent = _register_agent(store)
    agent["workspace_path"] = str(workspace_path)
    opened = []
    monkeypatch.setattr(agents_controller, "_open_directory", lambda path: opened.append(path))

    response = client.post("/api/agents/agent_dev/open-workspace")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["path"] == str(workspace_path)
    assert workspace_path.is_dir()
    assert opened == [workspace_path]


def test_open_agent_workspace_unknown_agent_returns_404(monkeypatch, tmp_path):
    client, _store = _client(monkeypatch, tmp_path)

    response = client.post("/api/agents/missing/open-workspace")

    assert response.status_code == 404
    assert response.get_json()["error"] == "agent not found"


def test_open_directory_macos_uses_open(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(agents_controller.sys, "platform", "darwin")
    monkeypatch.setattr(agents_controller.subprocess, "Popen", lambda args: calls.append(args))

    agents_controller._open_directory(tmp_path)

    assert calls == [["open", str(tmp_path)]]


def test_open_directory_linux_uses_xdg_open(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(agents_controller.sys, "platform", "linux")
    monkeypatch.setattr(agents_controller.shutil, "which", lambda name: "/usr/bin/xdg-open")
    monkeypatch.setattr(agents_controller.subprocess, "Popen", lambda args: calls.append(args))

    agents_controller._open_directory(tmp_path)

    assert calls == [["/usr/bin/xdg-open", str(tmp_path)]]


def test_open_directory_linux_without_xdg_open_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(agents_controller.sys, "platform", "linux")
    monkeypatch.setattr(agents_controller.shutil, "which", lambda name: None)

    try:
        agents_controller._open_directory(tmp_path)
    except RuntimeError as exc:
        assert "xdg-open not found" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_open_directory_windows_uses_startfile(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(agents_controller.sys, "platform", "win32")
    monkeypatch.setattr(agents_controller.os, "startfile", lambda path: calls.append(path), raising=False)

    agents_controller._open_directory(tmp_path)

    assert calls == [str(tmp_path)]
