from __future__ import annotations

import importlib

from argos.models.store import RuntimeStore
from argos.services import autostart


def _agent(agent_id: str, readiness_status: str = "ready", runtime_status: str = "stopped") -> dict:
    return {
        "agent_id": agent_id,
        "profile_name": agent_id,
        "name": agent_id,
        "role": "worker",
        "description": "",
        "is_leader": False,
        "workspace_path": "/tmp/workspace",
        "status": "offline",
        "current_task": "已停止",
        "runtime_status": runtime_status,
        "interaction_state": "idle",
        "orchestration_state": "none",
        "queue_depth": 0,
        "pending_interaction": None,
        "load": 0,
        "last_input": "",
        "last_output": "",
        "last_output_at": "",
        "readiness_status": readiness_status,
        "readiness_message": "",
        "created_at": "2026-04-26T00:00:00Z",
        "last_active_at": "2026-04-26T00:00:00Z",
    }


def test_start_ready_agents_on_boot_starts_ready_agents(monkeypatch):
    test_store = RuntimeStore()
    ready = _agent("agent_ready")
    failed = _agent("agent_failed", readiness_status="failed")
    test_store.register_agent(ready)
    test_store.register_agent(failed)
    started = []

    monkeypatch.setattr(autostart, "store", test_store)
    monkeypatch.setattr(autostart, "AUTO_START_AGENTS", True)
    monkeypatch.setattr(autostart.session_pool, "start", lambda agent: started.append(agent["agent_id"]) or True)
    monkeypatch.setattr(autostart.session_pool, "is_running", lambda agent_id: False)

    autostart.start_ready_agents_on_boot()

    assert started == ["agent_ready"]


def test_start_ready_agents_on_boot_can_be_disabled(monkeypatch):
    test_store = RuntimeStore()
    test_store.register_agent(_agent("agent_ready"))
    started = []

    monkeypatch.setattr(autostart, "store", test_store)
    monkeypatch.setattr(autostart, "AUTO_START_AGENTS", False)
    monkeypatch.setattr(autostart.session_pool, "start", lambda agent: started.append(agent["agent_id"]) or True)

    autostart.start_ready_agents_on_boot()

    assert started == []


def test_auto_start_agents_env_defaults_on(monkeypatch):
    monkeypatch.delenv("AUTO_START_AGENTS", raising=False)
    import argos.config as config

    importlib.reload(config)

    assert config.AUTO_START_AGENTS is True
