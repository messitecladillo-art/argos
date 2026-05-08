from __future__ import annotations

import logging
import threading
from typing import Any

from ..models.store import RuntimeStore, store as default_store
from .kanban import KanbanError, KanbanService, kanban_service
from .kanban_sync import sync_worker
from .settings import settings_service


logger = logging.getLogger("hermes.agent_state")


class KanbanDispatchWorker:
    """Backend dispatch loop.

    每个 tick 至多释放 1 个 pending_dispatch 任务，然后调用一次
    `hermes kanban dispatch`。HTTP `/api/kanban/dispatch` 与任务创建路径
    都通过 `dispatch_now()` 复用同一把锁，避免并发派发多任务。
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
        """串行执行：释放 1 个 pending_dispatch + 跑一次 kanban CLI dispatch。"""
        if not self._lock.acquire(blocking=False):
            return {"skipped": True, "released_count": 0, "result": None}
        try:
            released_count = self._release_one_pending_dispatch_task()
            result = self.service.dispatch_once(max_workers=max_workers)
            return {"skipped": False, "released_count": released_count, "result": result}
        finally:
            self._lock.release()

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
