from __future__ import annotations

from collections import deque
from itertools import count

from argos.models.store import RuntimeStore
from argos.services import registry


class FakePersistence:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def upsert_agent(self, *args):
        self.calls.append(("upsert_agent", args))

    def soft_delete_agent(self, *args):
        self.calls.append(("soft_delete_agent", args))

    def upsert_user_task(self, *args):
        self.calls.append(("upsert_user_task", args))

    def upsert_delegation(self, *args):
        self.calls.append(("upsert_delegation", args))

    def upsert_assignment(self, *args):
        self.calls.append(("upsert_assignment", args))

    def insert_message(self, *args):
        self.calls.append(("insert_message", args))

    def insert_event(self, *args):
        self.calls.append(("insert_event", args))

    def load_runtime_state(self):
        return {
            "agents": [
                {
                    "agent_id": "agent_lead",
                    "profile_name": "lead",
                    "name": "Lead",
                    "role": "leader",
                    "description": "",
                    "is_leader": True,
                    "workspace_path": "/tmp/lead",
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
            ],
            "user_tasks": [],
            "delegations": [],
            "messages": deque(maxlen=200),
            "events": deque(maxlen=400),
            "event_ids": count(9),
            "message_ids": count(8),
            "user_task_ids": count(7),
            "delegation_ids": count(6),
            "assignment_ids": count(5),
        }


def _agent(agent_id: str, profile_name: str, role: str) -> dict:
    return {
        "agent_id": agent_id,
        "profile_name": profile_name,
        "name": profile_name.title(),
        "role": role,
        "description": "",
        "is_leader": role == "leader",
        "workspace_path": f"/tmp/{profile_name}",
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


def test_store_persists_core_task_flow():
    persistence = FakePersistence()
    store = RuntimeStore(persistence)
    store.register_agent(_agent("agent_lead", "lead", "leader"))
    store.register_agent(_agent("agent_dev", "dev", "worker"))

    task = store.create_user_task(leader_agent_id="agent_lead", content="Build it")
    delegation = store.create_delegation(
        leader_agent_id="agent_lead",
        assignments=[{"to_agent_id": "agent_dev", "content": "Implement"}],
        summary_instruction="Summarize",
        user_task_id=task["user_task_id"],
    )
    assignment = delegation["assignments"][0]
    message = store.record_message(
        "Implement",
        "agent_dev",
        from_agent_id="agent_lead",
        delegation_id=delegation["delegation_id"],
        assignment_id=assignment["assignment_id"],
        user_task_id=task["user_task_id"],
    )
    store.attach_assignment_message(
        delegation["delegation_id"],
        assignment["assignment_id"],
        message["message_id"],
    )
    store.complete_assignment(
        delegation["delegation_id"],
        assignment["assignment_id"],
        result="done",
    )

    called = [name for name, _args in persistence.calls]
    assert "upsert_user_task" in called
    assert "upsert_delegation" in called
    assert "upsert_assignment" in called
    assert "insert_message" in called
    assert "insert_event" in called


def test_store_loads_persisted_state_and_counters():
    persistence = FakePersistence()
    store = RuntimeStore(persistence)

    store.load_persisted_state()
    event = store.push_event("test.event", "agent_lead", None, {"text": "ok"})

    assert store.find_agent("agent_lead")["profile_name"] == "lead"
    assert event["id"] == "evt_0009"


def test_store_does_not_persist_terminal_stream_events():
    persistence = FakePersistence()
    store = RuntimeStore(persistence)

    store.push_event("agent.terminal.output", "agent_lead", None, {"text": "chunk"})
    store.push_event("agent.terminal.snapshot", "agent_lead", None, {"text": "screen"})
    store.push_event("agent.output.final", "agent_lead", None, {"text": "done"})

    persisted_events = [
        args[0]
        for name, args in persistence.calls
        if name == "insert_event"
    ]
    assert [event["event_type"] for event in persisted_events] == ["agent.output.final"]


def test_bootstrap_refreshes_persisted_agent_readiness(monkeypatch):
    persistence = FakePersistence()
    store = RuntimeStore(persistence)
    persisted_agent = _agent("agent_dev", "dev", "worker")
    persisted_agent["readiness_status"] = "preparing"
    persisted_agent["readiness_message"] = "正在生成 SOUL.md"
    store.register_agent(persisted_agent)

    hydrated_agent = _agent("agent_dev", "dev", "worker")
    hydrated_agent["readiness_status"] = "ready"
    hydrated_agent["readiness_message"] = "SOUL.md 已就绪"
    monkeypatch.setattr(registry, "load_team_metas", lambda: [hydrated_agent])

    registry.bootstrap(store)

    agent = store.find_agent("agent_dev")
    assert agent["readiness_status"] == "ready"
    assert agent["readiness_message"] == "SOUL.md 已就绪"
