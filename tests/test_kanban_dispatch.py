from __future__ import annotations

from app.models.store import RuntimeStore
from app.services.kanban_dispatch import KanbanDispatchWorker


class FakeKanban:
    def __init__(self):
        self.assigned = []
        self.dispatched = 0

    def assign_task(self, task_id, profile):
        self.assigned.append((task_id, profile))

    def dispatch_once(self, *, max_workers=None):
        self.dispatched += 1
        return {"ok": True, "max_workers": max_workers}


def test_dispatch_skips_when_no_local_dispatchable_tasks():
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
    worker = KanbanDispatchWorker(runtime_store=runtime_store, service=service)

    outcome = worker.dispatch_now()

    assert outcome == {"skipped": True, "released_count": 0, "result": None}
    assert service.dispatched == 0


def test_dispatch_runs_after_releasing_pending_task():
    runtime_store = RuntimeStore()
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
