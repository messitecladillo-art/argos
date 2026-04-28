from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.controllers import agent_mcps as mcp_controller
from app.db.models import AgentMcpServerRecord
from app.db.session import Base
from app.models.store import RuntimeStore
from app.services import mcp_installer


def _client(monkeypatch, tmp_path):
    test_store = RuntimeStore()
    db_path = tmp_path / "mcp-test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    Base.metadata.create_all(bind=engine)
    hermes_home = tmp_path / ".hermes"
    monkeypatch.setattr(mcp_installer, "SessionLocal", session_local)
    monkeypatch.setattr(mcp_installer.profiles, "HERMES_HOME", hermes_home)
    monkeypatch.setattr(mcp_controller, "store", test_store)
    monkeypatch.setattr(mcp_controller.mcp_installer, "SessionLocal", session_local)
    monkeypatch.setattr(mcp_controller.mcp_installer.profiles, "HERMES_HOME", hermes_home)
    monkeypatch.setattr(mcp_installer, "_find_agent", lambda agent_id: test_store.find_agent(agent_id))
    app = Flask(__name__)
    app.register_blueprint(mcp_controller.bp)
    return app.test_client(), test_store, hermes_home, session_local


def _register_agent(store: RuntimeStore, hermes_home: Path, profile_name: str = "dev") -> dict:
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
    cfg_dir = hermes_home / "profiles" / profile_name
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text("model: test\nmcp_servers: {}\n", encoding="utf-8")
    return agent


def _config(hermes_home: Path, profile_name: str = "dev") -> dict:
    return yaml.safe_load((hermes_home / "profiles" / profile_name / "config.yaml").read_text())


def test_mcp_add_http_masks_secret(monkeypatch, tmp_path):
    client, store, hermes_home, session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)

    response = client.post(
        "/api/agents/agent_dev/mcps",
        json={
            "name": "figma",
            "transport": "http",
            "url": "https://mcp.figma.com/sse",
            "headers": {"Authorization": "Bearer figd_xxx"},
            "description": "Figma 设计文件访问",
        },
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["ok"] is True
    assert data["mcp"]["headers"]["Authorization"] != "Bearer figd_xxx"
    assert _config(hermes_home)["mcp_servers"]["figma"]["headers"]["Authorization"] == "Bearer figd_xxx"
    with session_local() as session:
        record = session.query(AgentMcpServerRecord).filter_by(profile_name="dev", name="figma").one()
    assert record.transport == "http"
    assert record.description == "Figma 设计文件访问"


def test_mcp_add_streamable_http(monkeypatch, tmp_path):
    client, store, hermes_home, session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)

    response = client.post(
        "/api/agents/agent_dev/mcps",
        json={"name": "remote", "transport": "streamable_http", "url": "https://mcp.example.com/mcp"},
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["mcp"]["transport"] == "streamable_http"
    spec = _config(hermes_home)["mcp_servers"]["remote"]
    assert spec["url"] == "https://mcp.example.com/mcp"
    assert spec["transport"] == "streamable_http"
    with session_local() as session:
        record = session.query(AgentMcpServerRecord).filter_by(profile_name="dev", name="remote").one()
    assert record.transport == "streamable_http"


def test_mcp_add_stdio_any_command(monkeypatch, tmp_path):
    client, store, hermes_home, _session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)

    response = client.post(
        "/api/agents/agent_dev/mcps",
        json={"name": "playwright", "transport": "stdio", "command": "npx", "args": ["-y", "@playwright/mcp@latest"]},
    )

    assert response.status_code == 201
    spec = _config(hermes_home)["mcp_servers"]["playwright"]
    assert spec["command"] == "npx"
    assert spec["args"] == ["-y", "@playwright/mcp@latest"]


def test_mcp_protect_builtin(monkeypatch, tmp_path):
    client, store, hermes_home, session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)
    mcp_installer.upsert_builtin_agent_bus("dev")
    config = _config(hermes_home)
    config["mcp_servers"]["agent_bus"] = {"url": "http://127.0.0.1:5050/mcp/", "enabled": True}
    (hermes_home / "profiles" / "dev" / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    response = client.put("/api/agents/agent_dev/mcps/agent_bus", json={"description": "x"})

    assert response.status_code == 400
    assert response.get_json()["error"] == "agent_bus is platform-managed"


def test_mcp_remove_external_deletes_yaml_only(monkeypatch, tmp_path):
    client, store, hermes_home, session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)
    config = _config(hermes_home)
    config["mcp_servers"]["external"] = {"url": "https://example.com/sse", "enabled": True}
    (hermes_home / "profiles" / "dev" / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    response = client.delete("/api/agents/agent_dev/mcps/external?confirm=1")

    assert response.status_code == 200
    assert "external" not in _config(hermes_home)["mcp_servers"]
    with session_local() as session:
        assert session.query(AgentMcpServerRecord).filter_by(profile_name="dev", name="external").count() == 0


def test_mcp_same_name_external_requires_takeover(monkeypatch, tmp_path):
    client, store, hermes_home, _session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)
    config = _config(hermes_home)
    config["mcp_servers"]["figma"] = {"url": "https://old.example/sse", "enabled": True}
    (hermes_home / "profiles" / "dev" / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    response = client.post("/api/agents/agent_dev/mcps", json={"name": "figma", "transport": "http", "url": "https://new.example/sse"})
    assert response.status_code == 409

    response = client.post("/api/agents/agent_dev/mcps", json={"name": "figma", "transport": "http", "url": "https://new.example/sse", "takeover": True})
    assert response.status_code == 201
    assert _config(hermes_home)["mcp_servers"]["figma"]["url"] == "https://new.example/sse"


def test_secret_reveal_and_empty_clears(monkeypatch, tmp_path):
    client, store, hermes_home, _session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)
    client.post(
        "/api/agents/agent_dev/mcps",
        json={"name": "figma", "transport": "http", "url": "https://mcp.figma.com/sse", "headers": {"Authorization": "Bearer token"}},
    )

    masked = client.get("/api/agents/agent_dev/mcps/figma").get_json()["mcp"]
    revealed = client.get("/api/agents/agent_dev/mcps/figma?reveal=1").get_json()["mcp"]
    assert masked["headers"]["Authorization"] != "Bearer token"
    assert revealed["headers"]["Authorization"] == "Bearer token"

    response = client.put("/api/agents/agent_dev/mcps/figma", json={"headers": {"Authorization": ""}})
    assert response.status_code == 200
    assert "headers" not in _config(hermes_home)["mcp_servers"]["figma"]


def test_masked_secret_edit_preserves_original(monkeypatch, tmp_path):
    client, store, hermes_home, _session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)
    client.post(
        "/api/agents/agent_dev/mcps",
        json={"name": "figma", "transport": "http", "url": "https://mcp.figma.com/sse", "headers": {"Authorization": "Bearer token"}},
    )
    masked = client.get("/api/agents/agent_dev/mcps/figma").get_json()["mcp"]["headers"]["Authorization"]

    response = client.put(
        "/api/agents/agent_dev/mcps/figma",
        json={"description": "updated", "headers": {"Authorization": masked}},
    )

    assert response.status_code == 200
    spec = _config(hermes_home)["mcp_servers"]["figma"]
    assert spec["headers"]["Authorization"] == "Bearer token"


def test_mcp_add_ignores_orphan_db_record(monkeypatch, tmp_path):
    client, store, hermes_home, session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)
    client.post("/api/agents/agent_dev/mcps", json={"name": "figma", "transport": "http", "url": "https://old.example/sse"})
    config = _config(hermes_home)
    config["mcp_servers"].pop("figma")
    (hermes_home / "profiles" / "dev" / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    with session_local() as session:
        assert session.query(AgentMcpServerRecord).filter_by(profile_name="dev", name="figma").count() == 1

    response = client.post("/api/agents/agent_dev/mcps", json={"name": "figma", "transport": "http", "url": "https://new.example/sse"})

    assert response.status_code == 201
    assert _config(hermes_home)["mcp_servers"]["figma"]["url"] == "https://new.example/sse"


def test_http_test_head_fallback_get(monkeypatch, tmp_path):
    client, store, hermes_home, _session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)
    client.post("/api/agents/agent_dev/mcps", json={"name": "web", "transport": "http", "url": "https://example.com/sse"})
    calls = []

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_head(*args, **kwargs):
        calls.append("HEAD")
        assert kwargs["headers"]["Accept"] == "application/json, text/event-stream"
        return FakeResponse(405)

    def fake_stream(method, *args, **kwargs):
        calls.append(method)
        return FakeResponse(204)

    monkeypatch.setattr(mcp_installer.httpx, "head", fake_head)
    monkeypatch.setattr(mcp_installer.httpx, "stream", fake_stream)

    response = client.post("/api/agents/agent_dev/mcps/web/test")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
    assert calls == ["HEAD", "GET"]


def test_streamable_http_test_uses_http_probe(monkeypatch, tmp_path):
    client, store, hermes_home, _session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)
    client.post("/api/agents/agent_dev/mcps", json={"name": "remote", "transport": "streamable_http", "url": "https://example.com/mcp"})

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(mcp_installer.httpx, "head", lambda *args, **kwargs: FakeResponse())

    response = client.post("/api/agents/agent_dev/mcps/remote/test")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_stdio_test_handshake(monkeypatch, tmp_path):
    client, store, hermes_home, _session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)
    script = tmp_path / "stdio_mcp.py"
    script.write_text(
        "import json, sys\n"
        "line=sys.stdin.readline()\n"
        "req=json.loads(line)\n"
        "print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':{'capabilities':{}}}), flush=True)\n",
        encoding="utf-8",
    )
    client.post("/api/agents/agent_dev/mcps", json={"name": "local", "transport": "stdio", "command": "python3", "args": [str(script)]})

    response = client.post("/api/agents/agent_dev/mcps/local/test")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_args_must_be_array(monkeypatch, tmp_path):
    client, store, hermes_home, _session_local = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)

    response = client.post("/api/agents/agent_dev/mcps", json={"name": "bad", "transport": "stdio", "command": "npx", "args": "-y package"})

    assert response.status_code == 422
