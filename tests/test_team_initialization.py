from __future__ import annotations

from pathlib import Path

from flask import Flask
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from argos.controllers import agents as agents_controller
from argos.db.models import AgentRecord, EventRecord, KanbanTaskLinkRecord, MessageRecord, UserTaskRecord
from argos.db.session import Base
from argos.models.store import RuntimeStore
from argos.services import team_initialization
from argos.services.kanban import KanbanError


def _agent(agent_id: str, profile_name: str, workspace: Path) -> dict:
    return {
        "agent_id": agent_id,
        "profile_name": profile_name,
        "name": profile_name.title(),
        "role": "worker",
        "description": "",
        "is_leader": False,
        "workspace_path": str(workspace),
        "status": "busy",
        "current_task": "doing",
        "runtime_status": "running",
        "interaction_state": "busy",
        "orchestration_state": "running",
        "queue_depth": 3,
        "pending_interaction": {"request_id": "req_1"},
        "load": 9,
        "last_input": "old input",
        "last_output": "old output",
        "last_output_at": "2026-04-26T00:00:00Z",
        "readiness_status": "ready",
        "readiness_message": "ready",
        "created_at": "2026-04-26T00:00:00Z",
        "last_active_at": "2026-04-26T00:00:00Z",
    }


def _unready_agent(agent_id: str, profile_name: str, workspace: Path) -> dict:
    agent = _agent(agent_id, profile_name, workspace)
    agent["readiness_status"] = "missing_soul"
    agent["readiness_message"] = "missing"
    return agent


def _configure_env(monkeypatch, tmp_path):
    workspace_root = tmp_path / "agent_team"
    db_path = tmp_path / "initialize.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(team_initialization, "AGENT_TEAM_WORKSPACE_ROOT", workspace_root.resolve(strict=False))
    monkeypatch.setattr(team_initialization, "SessionLocal", session_local)
    monkeypatch.setattr(agents_controller.team_initialization, "AGENT_TEAM_WORKSPACE_ROOT", workspace_root.resolve(strict=False))
    monkeypatch.setattr(agents_controller.team_initialization, "SessionLocal", session_local)
    return workspace_root, session_local


def test_initialize_agents_clears_workspace_history_and_resets_runtime(monkeypatch, tmp_path):
    workspace_root, session_local = _configure_env(monkeypatch, tmp_path)
    workspace = workspace_root / "dev"
    workspace.mkdir(parents=True)
    (workspace / "old.txt").write_text("old", encoding="utf-8")
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_dev", "dev", workspace))
    runtime_store.record_message("hello", "agent_dev")
    runtime_store.create_user_task(leader_agent_id="agent_dev", content="build")
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id="ut_0001",
        kanban_task_id="task-1",
        kanban_role="leader",
    )
    stopped = []
    monkeypatch.setattr(team_initialization.session_pool, "stop", lambda agent_id: stopped.append(agent_id))
    started = []
    monkeypatch.setattr(team_initialization.session_pool, "start", lambda agent: started.append(agent["agent_id"]) or True)
    resets = []
    monkeypatch.setattr(team_initialization.kanban_service, "reset_board", lambda: resets.append(True) or {"board": "team-board"})
    with session_local.begin() as session:
        session.add(
            AgentRecord(
                agent_id="agent_dev",
                profile_name="dev",
                name="Dev",
                role="worker",
                workspace_path=str(workspace),
                status="busy",
                current_task="doing",
                runtime_status="running",
                interaction_state="busy",
                orchestration_state="running",
                queue_depth=3,
                pending_interaction_json='{"request_id":"req_1"}',
                load=9,
                last_input="old input",
                last_output="old output",
            )
        )
        session.add(MessageRecord(message_id="msg_db", to_agent_id="agent_dev", content="old", created_at="now"))
        session.add(EventRecord(event_id="evt_db", event_type="old", agent_id="agent_dev", data_json="{}", created_at="now"))
        session.add(UserTaskRecord(user_task_id="ut_db", leader_agent_id="agent_dev", content="old", status="running"))
        session.add(KanbanTaskLinkRecord(local_type="user_task", local_id="ut_db", kanban_task_id="kb_db", kanban_role="leader"))

    result = team_initialization.initialize_agents(runtime_store)

    assert result["ok"] is True
    assert result["kanban"]["reset"] is True
    assert resets == [True]
    assert stopped == ["agent_dev"]
    assert started == ["agent_dev"]
    assert result["startup"]["started"] == 1
    assert workspace.exists()
    assert list(workspace.iterdir()) == []
    snapshot = runtime_store.snapshot()
    assert snapshot["messages"] == []
    assert snapshot["events"] == []
    assert snapshot["user_tasks"] == []
    assert snapshot["kanban_task_links"] == []
    agent = runtime_store.find_agent("agent_dev")
    assert agent["runtime_status"] == "stopped"
    assert agent["status"] == "idle"
    assert agent["current_task"] == "空闲"
    assert agent["last_input"] == ""
    assert agent["last_output"] == ""
    with session_local() as session:
        assert session.scalar(select(MessageRecord)) is None
        assert session.scalar(select(EventRecord)) is None
        assert session.scalar(select(UserTaskRecord)) is None
        assert session.scalar(select(KanbanTaskLinkRecord)) is None
        record = session.scalar(select(AgentRecord).where(AgentRecord.agent_id == "agent_dev"))
        assert record.runtime_status == "stopped"
        assert record.status == "idle"
        assert record.current_task == "空闲"


def test_initialize_agents_endpoint(monkeypatch, tmp_path):
    workspace_root, _session_local = _configure_env(monkeypatch, tmp_path)
    workspace = workspace_root / "dev"
    workspace.mkdir(parents=True)
    test_store = RuntimeStore()
    test_store.register_agent(_agent("agent_dev", "dev", workspace))
    monkeypatch.setattr(agents_controller, "store", test_store)
    monkeypatch.setattr(team_initialization.session_pool, "stop", lambda agent_id: None)
    monkeypatch.setattr(team_initialization.session_pool, "start", lambda agent: True)
    monkeypatch.setattr(team_initialization.kanban_service, "reset_board", lambda: {"board": "team-board"})

    app = Flask(__name__)
    app.register_blueprint(agents_controller.bp)
    response = app.test_client().post("/api/agents/initialize", json={})

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["cleared"]["agents"] == 1
    assert data["agents"][0]["runtime_status"] == "stopped"
    assert data["startup"]["started"] == 1


def test_initialize_agents_aborts_when_kanban_reset_fails(monkeypatch, tmp_path):
    workspace_root, session_local = _configure_env(monkeypatch, tmp_path)
    workspace = workspace_root / "dev"
    workspace.mkdir(parents=True)
    (workspace / "old.txt").write_text("old", encoding="utf-8")
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_dev", "dev", workspace))
    runtime_store.record_message("hello", "agent_dev")
    monkeypatch.setattr(team_initialization.session_pool, "stop", lambda agent_id: None)
    monkeypatch.setattr(team_initialization.kanban_service, "reset_board", lambda: (_ for _ in ()).throw(KanbanError("kanban failed")))

    result = team_initialization.initialize_agents(runtime_store)

    assert result["ok"] is False
    assert result["kanban"]["errors"] == ["kanban failed"]
    assert (workspace / "old.txt").exists()
    assert runtime_store.snapshot()["messages"]


def test_initialize_agents_skips_unready_agent_start(monkeypatch, tmp_path):
    workspace_root, _session_local = _configure_env(monkeypatch, tmp_path)
    ready_workspace = workspace_root / "ready"
    unready_workspace = workspace_root / "unready"
    ready_workspace.mkdir(parents=True)
    unready_workspace.mkdir(parents=True)
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_ready", "ready", ready_workspace))
    runtime_store.register_agent(_unready_agent("agent_unready", "unready", unready_workspace))
    monkeypatch.setattr(team_initialization.session_pool, "stop", lambda agent_id: None)
    started = []
    monkeypatch.setattr(team_initialization.session_pool, "start", lambda agent: started.append(agent["agent_id"]) or True)
    monkeypatch.setattr(team_initialization.kanban_service, "reset_board", lambda: {"board": "team-board"})

    result = team_initialization.initialize_agents(runtime_store)

    assert result["ok"] is True
    assert started == ["agent_ready"]
    assert result["startup"]["started"] == 1
    assert result["startup"]["skipped"] == 1
