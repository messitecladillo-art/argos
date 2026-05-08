from __future__ import annotations

import logging
import threading
import time
from typing import Any

from ..models.store import RuntimeStore, store as default_store
from .kanban import KanbanError, KanbanService, kanban_service
from .kanban_sync import sync_worker
from .settings import settings_service


logger = logging.getLogger("hermes.agent_state")
DISPATCH_LEASE_SECONDS = 300
RUNNING_HOUSEKEEPING_SECONDS = 30


class KanbanDispatchWorker:
    """Backend dispatch loop.

    每个 tick 至多释放 1 个 pending_dispatch 任务；只有本地存在
    待执行任务时才调用 `hermes kanban dispatch`。HTTP `/api/kanban/dispatch`
    与任务创建路径都通过 `dispatch_now()` 复用同一把锁，避免并发派发多任务。
    """

    def __init__(
        self,
        *,
        runtime_store: RuntimeStore = default_store,
        service: KanbanService = kanban_service,
        interval: float = 2.0,
    ) -> None:
        self.store = runtime_store
        self.service = service
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if settings_service.get_kanban_auto_dispatch_enabled():
                    self.dispatch_now()
            except Exception as exc:  # noqa: BLE001
                logger.exception("[kanban-dispatch] tick failed: %s", exc)
            self._stop.wait(self.interval)

    def trigger_async(self) -> None:
        """任务创建后即时触发一次派发，不阻塞调用方。仅当自动派发开启时生效。"""
        if not settings_service.get_kanban_auto_dispatch_enabled():
            return
        threading.Thread(target=self._safe_dispatch, daemon=True).start()

    def _safe_dispatch(self) -> None:
        try:
            self.dispatch_now()
        except Exception as exc:  # noqa: BLE001
            logger.exception("[kanban-dispatch] async trigger failed: %s", exc)

    def dispatch_now(self, *, max_workers: int | None = None) -> dict[str, Any]:
        """串行执行：释放 1 个 pending_dispatch；有待执行任务才跑 CLI dispatch。"""
        if not self._lock.acquire(blocking=False):
            logger.info("[kanban-dispatch] skip reason=locked")
            return {"skipped": True, "released_count": 0, "result": None}
        try:
            released_count = self._release_one_pending_dispatch_task()
            self._sync_ready_links()
            dispatchable = self._dispatchable_tasks()
            running_housekeeping = self._running_tasks_due_for_housekeeping()
            if not dispatchable and not running_housekeeping:
                logger.info("[kanban-dispatch] skip reason=no_dispatchable released=%s", released_count)
                return {"skipped": True, "released_count": 0, "result": None}
            effective_max_workers = max_workers if max_workers is not None else max(1, len(dispatchable))
            logger.warning(
                "[kanban-dispatch] run released=%s max_workers=%s tasks=%s",
                released_count,
                effective_max_workers,
                [item.get("kanban_task_id") for item in dispatchable],
            )
            result = self.service.dispatch_once(max_workers=effective_max_workers)
            self._mark_dispatched(dispatchable, result)
            self._mark_running_housekeeping(running_housekeeping)
            return {"skipped": False, "released_count": released_count, "result": result}
        finally:
            self._lock.release()

    def _dispatchable_tasks(self) -> list[dict]:
        now = time.time()
        return [
            link
            for link in self.store.snapshot().get("kanban_task_links", []) or []
            if (link.get("kanban_status") or "").lower() in {"ready", "todo", "triage"}
            and bool(link.get("assignee_profile"))
            and bool(link.get("kanban_task_id"))
            and not self._has_active_dispatch_lease(link, now)
        ]

    def _has_active_dispatch_lease(self, link: dict, now: float) -> bool:
        metadata = link.get("metadata") or {}
        dispatched_at = metadata.get("dispatch_started_at")
        try:
            age = now - float(dispatched_at)
        except (TypeError, ValueError):
            return False
        if age < DISPATCH_LEASE_SECONDS:
            logger.info(
                "[kanban-dispatch] skip task=%s reason=active_lease age=%.1fs status=%s",
                link.get("kanban_task_id"),
                age,
                link.get("kanban_status"),
            )
            return True
        return False

    def _running_tasks_due_for_housekeeping(self) -> list[dict]:
        now = time.time()
        due = []
        for link in self.store.snapshot().get("kanban_task_links", []) or []:
            if (link.get("kanban_status") or "").lower() != "running":
                continue
            if not link.get("assignee_profile") or not link.get("kanban_task_id"):
                continue
            metadata = link.get("metadata") or {}
            checked_at = metadata.get("running_housekeeping_at") or metadata.get("dispatch_started_at")
            try:
                age = now - float(checked_at)
            except (TypeError, ValueError):
                due.append(link)
                continue
            if age >= RUNNING_HOUSEKEEPING_SECONDS:
                due.append(link)
        return due

    def _mark_running_housekeeping(self, links: list[dict]) -> None:
        checked_at = time.time()
        for link in links:
            task_id = link.get("kanban_task_id") or ""
            if not task_id:
                continue
            self.store.update_kanban_task_link(
                task_id,
                metadata={**(link.get("metadata") or {}), "running_housekeeping_at": checked_at},
            )

    def _mark_dispatched(self, links: list[dict], result: Any) -> None:
        spawned_ids = _spawned_task_ids(result)
        dispatched_at = time.time()
        for link in links:
            task_id = link.get("kanban_task_id") or ""
            if not task_id:
                continue
            if spawned_ids is not None and task_id not in spawned_ids:
                self._sync_link_after_dispatch(link)
                continue
            self.store.update_kanban_task_link(
                task_id,
                kanban_status="running",
                metadata={**(link.get("metadata") or {}), "dispatch_started_at": dispatched_at},
            )
            logger.warning(
                "[kanban-dispatch] lease task=%s assignee=%s status=running lease_seconds=%s",
                task_id,
                link.get("assignee_profile"),
                DISPATCH_LEASE_SECONDS,
            )

    def _sync_link_after_dispatch(self, link: dict) -> None:
        """Refresh tasks that were eligible locally but not spawned by dispatch.

        This happens for child tasks whose parent is still active: the CLI keeps
        them in todo/ready, so marking them running locally would make the UI
        report work that has not actually started.
        """
        task_id = link.get("kanban_task_id") or ""
        if not task_id:
            return
        try:
            task = self.service.show_task(task_id)
        except KanbanError as exc:
            logger.warning("[kanban-dispatch] post-dispatch show failed task=%s error=%s", task_id, exc)
            return
        status = str(task.get("status") or task.get("state") or task.get("task", {}).get("status") or "")
        if not status:
            return
        metadata = dict(link.get("metadata") or {})
        metadata.pop("dispatch_started_at", None)
        self.store.update_kanban_task_link(task_id, kanban_status=status, metadata=metadata)

    def _sync_ready_links(self) -> None:
        for link in self.store.snapshot().get("kanban_task_links", []) or []:
            if (link.get("kanban_status") or "").lower() not in {"ready", "todo", "triage", "running"}:
                continue
            if not link.get("kanban_task_id"):
                continue
            task_id = link.get("kanban_task_id") or ""
            try:
                task = self.service.show_task(task_id)
            except KanbanError as exc:
                logger.warning("[kanban-dispatch] preflight show failed task=%s error=%s", task_id, exc)
                continue
            status = str(task.get("status") or task.get("state") or task.get("task", {}).get("status") or "")
            local_status = (link.get("kanban_status") or "").lower()
            remote_status = (status or "").lower()
            if local_status == "running" and remote_status in {"ready", "todo", "triage"}:
                logger.warning(
                    "[kanban-dispatch] ignore active rollback task=%s local=%s remote=%s",
                    task_id,
                    local_status,
                    remote_status,
                )
                continue
            if status and status != link.get("kanban_status"):
                metadata = dict(link.get("metadata") or {})
                if remote_status in {"done", "blocked", "failed", "crashed", "timed_out", "gave_up"}:
                    metadata.pop("dispatch_started_at", None)
                logger.warning(
                    "[kanban-dispatch] preflight status sync task=%s local=%s remote=%s",
                    task_id,
                    link.get("kanban_status"),
                    status,
                )
                self.store.update_kanban_task_link(task_id, kanban_status=status, metadata=metadata)

    def _release_one_pending_dispatch_task(self) -> int:
        for link in self.store.snapshot().get("kanban_task_links", []) or []:
            if (link.get("kanban_status") or "").lower() != "pending_dispatch":
                continue
            if (link.get("kanban_status") or "").lower() == "archived":
                continue
            assignee = link.get("assignee_profile") or ""
            task_id = link.get("kanban_task_id") or ""
            if not assignee or not task_id:
                continue
            try:
                self.service.assign_task(task_id, assignee)
            except KanbanError as exc:
                logger.warning(
                    "[kanban-dispatch] assign failed task=%s assignee=%s error=%s",
                    task_id,
                    assignee,
                    exc,
                )
                return 0
            self.store.update_kanban_task_link(
                task_id,
                kanban_status="ready",
                metadata={**(link.get("metadata") or {}), "pending_dispatch": False},
            )
            sync_worker.sync_once_async()
            return 1
        return 0


dispatch_worker = KanbanDispatchWorker()


def _spawned_task_ids(result: Any) -> set[str] | None:
    if not isinstance(result, dict) or "spawned" not in result:
        return None
    spawned = result.get("spawned") or []
    task_ids: set[str] = set()
    for item in spawned:
        if isinstance(item, dict):
            task_id = item.get("task_id") or item.get("id") or item.get("key")
            if task_id:
                task_ids.add(str(task_id))
        elif item:
            task_ids.add(str(item))
    return task_ids
