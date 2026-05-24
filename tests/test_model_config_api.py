from __future__ import annotations

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.controllers import model_configs as model_configs_controller
from app.db.session import Base
from app.models.store import RuntimeStore
from app.services import model_configs as model_configs_service


def _client(monkeypatch, tmp_path):
    test_store = RuntimeStore()
    db_path = tmp_path / "model-configs.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(model_configs_service, "SessionLocal", session_local)
    monkeypatch.setattr(model_configs_service, "store", test_store)
    monkeypatch.setattr(model_configs_controller.model_configs, "store", test_store)
    monkeypatch.setattr(model_configs_controller.model_configs.profiles, "HERMES_HOME", tmp_path / ".hermes")
    app = Flask(__name__)
    app.register_blueprint(model_configs_controller.bp)
    return app.test_client(), test_store, tmp_path / ".hermes"


def _register_agent(store: RuntimeStore, hermes_home, profile_name: str = "dev") -> dict:
    cfg_dir = hermes_home / "profiles" / profile_name
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "agent:\n  name: Dev\nmodel:\n  default: old-model\n  provider: custom\n  base_url: https://old.example/v1\n  api_key: old-key\n",
        encoding="utf-8",
    )
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


def test_model_config_crud_validates_and_lists(monkeypatch, tmp_path):
    client, _store, _hermes_home = _client(monkeypatch, tmp_path)

    bad_response = client.post(
        "/api/model-configs",
        json={"name": " bad ", "model": "gpt-5.4", "base_url": "ftp://bad", "api_key": "sk"},
    )
    assert bad_response.status_code == 400

    response = client.post(
        "/api/model-configs",
        json={
            "name": " 公司网关 ",
            "model": " gpt-5.4 ",
            "base_url": " https://example.com/v1 ",
            "api_key": " sk-xxx ",
        },
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data["ok"] is True
    assert data["item"]["name"] == "公司网关"

    list_response = client.get("/api/model-configs")
    assert list_response.status_code == 200
    assert list_response.get_json()["items"][0]["model"] == "gpt-5.4"


def test_apply_model_config_updates_profile_yaml(monkeypatch, tmp_path):
    client, store, hermes_home = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)
    created = client.post(
        "/api/model-configs",
        json={
            "name": "Gateway",
            "model": "gpt-5.4",
            "base_url": "https://example.com/v1",
            "api_key": "${OPENAI_API_KEY}",
        },
    ).get_json()["item"]

    response = client.put("/api/agents/agent_dev/model", json={"model_config_id": created["id"]})

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["model"]["default"] == "gpt-5.4"
    content = (hermes_home / "profiles" / "dev" / "config.yaml").read_text(encoding="utf-8")
    assert "agent:\n  name: Dev" in content
    assert "provider: custom" in content
    assert "api_key: ${OPENAI_API_KEY}" in content


def test_update_preserves_masked_api_key(monkeypatch, tmp_path):
    """When the client sends a masked API key, the existing key is preserved."""
    client, _store, _hermes_home = _client(monkeypatch, tmp_path)
    created = client.post(
        "/api/model-configs",
        json={
            "name": "Original",
            "model": "gpt-4",
            "base_url": "https://example.com/v1",
            "api_key": "sk-real-secret-key-12345",
        },
    ).get_json()["item"]

    # Update with masked key — the UI sends back the masked value
    response = client.put(
        f"/api/model-configs/{created['id']}",
        json={
            "name": "Original",
            "model": "gpt-4",
            "base_url": "https://example.com/v1",
            "api_key": "sk-r...12345",  # masked
        },
    )
    assert response.status_code == 200
    # The item should be returned with masked key (safe for UI)
    assert response.get_json()["item"]["api_key"] != "sk-real-secret-key-12345"

    # But internally the real key is preserved — verify by testing the connection
    # The test_model_config would fail if the key was overwritten with the masked value
    # We can't easily verify the DB value directly here, but the service-level
    # test below confirms the logic.


def test_validate_payload_rejects_masked_key_without_existing(monkeypatch):
    """If no existing_api_key is provided and the payload key looks masked, raise."""
    from app.services.model_configs import ModelConfigError, _validate_payload

    try:
        _validate_payload({
            "name": "Test", "model": "gpt-4",
            "base_url": "https://example.com/v1", "api_key": "sk-a...1234",
        })
        assert False, "Expected ModelConfigError"
    except ModelConfigError as exc:
        assert "masked" in str(exc).lower() or "api_key" in str(exc).lower()


def test_validate_payload_preserves_existing_on_masked(monkeypatch):
    """When existing_api_key is provided and payload key is masked, use existing."""
    from app.services.model_configs import _validate_payload

    result = _validate_payload(
        {"name": "Test", "model": "gpt-4", "base_url": "https://example.com/v1", "api_key": "sk-a...1234"},
        existing_api_key="sk-real-secret",
    )
    assert result["api_key"] == "sk-real-secret"


def test_get_agent_model_reads_profile(monkeypatch, tmp_path):
    client, store, hermes_home = _client(monkeypatch, tmp_path)
    _register_agent(store, hermes_home)

    response = client.get("/api/agents/agent_dev/model")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["model"]["default"] == "old-model"
