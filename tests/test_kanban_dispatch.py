from __future__ import annotations

import time

from app.models.store import RuntimeStore
from app.services.kanban_dispatch import KanbanDispatchWorker


def _agent(agent_id: str, profile_name: str, role: str = "leader") -> dict:
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


def _register_dispatch_agents(runtime_store: RuntimeStore) -> None:
    runtime_store.register_agent(_agent("agent_leader", "leader", "leader"))
    runtime_store.register_agent(_agent("agent_developer", "developer", "worker"))


class FakeKanban:
    def __init__(self):
        self.assigned = []
        self.dispatched = 0
        self.tasks = {}
        self.dispatch_result = None

    def assign_task(self, task_id, profile):
        self.assigned.append((task_id, profile))

    def dispatch_once(self, *, max_workers=None):
        self.dispatched += 1
        return self.dispatch_result or {"ok": True, "max_workers": max_workers}

    def show_task(self, task_id):
        return self.tasks.get(task_id, {"status": "ready"})


def test_dispatch_skips_when_no_local_dispatchable_tasks():
    runtime_store = RuntimeStore()
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id="ut_1",
        kanban_task_id="kb_1",
        kanban_role="parent",
        kanban_status="done",
        assignee_profile="leader",
    )
    service = FakeKanban()
    worker = KanbanDispatchWorker(runtime_store=runtime_store, service=service)

    outcome = worker.dispatch_now()

    assert outcome == {"skipped": True, "released_count": 0, "result": None}
    assert service.dispatched == 0


def test_dispatch_skips_local_running_tasks_without_respawning():
    runtime_store = RuntimeStore()
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id="ut_1",
        kanban_task_id="kb_1",
        kanban_role="parent",
        kanban_status="running",
        assignee_profile="leader",
        metadata={"dispatch_started_at": time.time() - 60},
    )
    service = FakeKanban()
    service.tasks["kb_1"] = {"status": "running"}
    worker = KanbanDispatchWorker(runtime_store=runtime_store, service=service)

    outcome = worker.dispatch_now()

    assert outcome == {"skipped": True, "released_count": 0, "result": None}
    assert service.dispatched == 0
    assert runtime_store.find_kanban_task_link(kanban_task_id="kb_1")["kanban_status"] == "running"


def test_dispatch_runs_after_releasing_pending_task():
    runtime_store = RuntimeStore()
    _register_dispatch_agents(runtime_store)
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id="ut_1",
        kanban_task_id="kb_1",
        kanban_role="parent",
        kanban_status="pending_dispatch",
        assignee_profile="leader",
    )
    service = FakeKanban()
    worker = KanbanDispatchWorker(runtime_store=runtime_store, service=service)

    outcome = worker.dispatch_now(max_workers=1)

    assert outcome["skipped"] is False
    assert outcome["released_count"] == 1
    assert service.assigned == [("kb_1", "leader")]
    assert service.dispatched == 1


def test_dispatch_preflight_syncs_stale_done_task_and_skips():
    runtime_store = RuntimeStore()
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id="ut_1",
        kanban_task_id="kb_1",
        kanban_role="parent",
        kanban_status="ready",
        assignee_profile="leader",
    )
    service = FakeKanban()
    service.tasks["kb_1"] = {"status": "done"}
    worker = KanbanDispatchWorker(runtime_store=runtime_store, service=service)

    outcome = worker.dispatch_now()

    assert outcome == {"skipped": True, "released_count": 0, "result": None}
    assert service.dispatched == 0
    assert runtime_store.find_kanban_task_link(kanban_task_id="kb_1")["kanban_status"] == "done"


def test_dispatch_preflight_syncs_running_done_task_and_skips():
    runtime_store = RuntimeStore()
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id="ut_1",
        kanban_task_id="kb_1",
        kanban_role="parent",
        kanban_status="running",
        assignee_profile="leader",
    )
    service = FakeKanban()
    service.tasks["kb_1"] = {"status": "done"}
    worker = KanbanDispatchWorker(runtime_store=runtime_store, service=service)

    outcome = worker.dispatch_now()

    assert outcome == {"skipped": True, "released_count": 0, "result": None}
    assert service.dispatched == 0
    assert runtime_store.find_kanban_task_link(kanban_task_id="kb_1")["kanban_status"] == "done"


def test_dispatch_lease_prevents_immediate_duplicate_when_remote_stays_ready():
    runtime_store = RuntimeStore()
    _register_dispatch_agents(runtime_store)
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id="ut_1",
        kanban_task_id="kb_1",
        kanban_role="parent",
        kanban_status="ready",
        assignee_profile="leader",
    )
    service = FakeKanban()
    service.tasks["kb_1"] = {"status": "ready"}
    worker = KanbanDispatchWorker(runtime_store=runtime_store, service=service)

    first = worker.dispatch_now()
    second = worker.dispatch_now()

    assert first["skipped"] is False
    assert second == {"skipped": True, "released_count": 0, "result": None}
    assert service.dispatched == 1
    link = runtime_store.find_kanban_task_link(kanban_task_id="kb_1")
    assert link["kanban_status"] == "running"
    assert link["metadata"]["dispatch_started_at"]


def test_dispatch_marks_only_spawned_tasks_running():
    runtime_store = RuntimeStore()
    _register_dispatch_agents(runtime_store)
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id="ut_1",
        kanban_task_id="kb_parent",
        kanban_role="parent",
        kanban_status="ready",
        assignee_profile="leader",
    )
    runtime_store.upsert_kanban_task_link(
        local_type="assignment",
        local_id="asg_1",
        kanban_task_id="kb_child",
        kanban_role="worker",
        kanban_status="ready",
        assignee_profile="developer",
        parent_local_id="ut_1",
    )
    service = FakeKanban()
    service.tasks = {
        "kb_parent": {"status": "ready"},
        "kb_child": {"status": "todo"},
    }
    service.dispatch_result = {"spawned": [{"task_id": "kb_parent", "assignee": "leader"}]}
    worker = KanbanDispatchWorker(runtime_store=runtime_store, service=service)

    outcome = worker.dispatch_now()

    assert outcome["skipped"] is False
    assert service.dispatched == 1
    assert runtime_store.find_kanban_task_link(kanban_task_id="kb_parent")["kanban_status"] == "running"
    child = runtime_store.find_kanban_task_link(kanban_task_id="kb_child")
    assert child["kanban_status"] == "todo"
    assert "dispatch_started_at" not in child["metadata"]
def test_dispatch_task_now_marks_only_target_running(monkeypatch):
    runtime_store = RuntimeStore()
    _register_dispatch_agents(runtime_store)
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id="ut_1",
        kanban_task_id="kb_target",
        kanban_role="parent",
        kanban_status="ready",
        assignee_profile="leader",
    )
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id="ut_2",
        kanban_task_id="kb_other",
        kanban_role="parent",
        kanban_status="ready",
        assignee_profile="leader",
    )
    service = FakeKanban()
    service.tasks = {"kb_target": {"status": "ready"}, "kb_other": {"status": "ready"}}
    service.dispatch_one = lambda task_id, **kwargs: {
        "spawned": [{"task_id": task_id, "assignee": "leader", "workspace": "/tmp/ws"}]
    }
    worker = KanbanDispatchWorker(runtime_store=runtime_store, service=service)

    outcome = worker.dispatch_task_now("kb_target")

    assert outcome["skipped"] is False
    assert runtime_store.find_kanban_task_link(kanban_task_id="kb_target")["kanban_status"] == "running"
    assert runtime_store.find_kanban_task_link(kanban_task_id="kb_other")["kanban_status"] == "ready"


def test_dispatch_task_now_releases_pending_dispatch_target_only():
    runtime_store = RuntimeStore()
    _register_dispatch_agents(runtime_store)
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id="ut_1",
        kanban_task_id="kb_target",
        kanban_role="parent",
        kanban_status="pending_dispatch",
        assignee_profile="leader",
        metadata={"pending_dispatch": True},
    )
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id="ut_2",
        kanban_task_id="kb_other",
        kanban_role="parent",
        kanban_status="pending_dispatch",
        assignee_profile="leader",
        metadata={"pending_dispatch": True},
    )
    service = FakeKanban()
    service.tasks = {"kb_target": {"status": "ready"}, "kb_other": {"status": "pending_dispatch"}}
    service.dispatch_one = lambda task_id, **kwargs: {
        "spawned": [{"task_id": task_id, "assignee": "leader", "workspace": "/tmp/ws"}]
    }
    worker = KanbanDispatchWorker(runtime_store=runtime_store, service=service)

    outcome = worker.dispatch_task_now("kb_target")

    assert outcome["skipped"] is False
    assert service.assigned == [("kb_target", "leader")]
    assert runtime_store.find_kanban_task_link(kanban_task_id="kb_target")["kanban_status"] == "running"
    assert runtime_store.find_kanban_task_link(kanban_task_id="kb_other")["kanban_status"] == "pending_dispatch"
