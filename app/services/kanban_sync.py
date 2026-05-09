from __future__ import annotations

import logging
import threading
import time
from typing import Any

from ..config import KANBAN_POLL_INTERVAL
from ..models.store import RuntimeStore, store as default_store
from .kanban import KanbanError, KanbanService, extract_task_id, kanban_service, task_result, task_status
from .kanban_workspace import workspace_for_agent


logger = logging.getLogger("hermes.agent_state")
DONE_STATUSES = {"done"}
FAILED_STATUSES = {"blocked", "failed", "crashed", "timed_out", "gave_up"}
TERMINAL_STATUSES = DONE_STATUSES | FAILED_STATUSES | {"archived"}


class KanbanSyncWorker:
    def __init__(
        self,
        *,
        runtime_store: RuntimeStore = default_store,
        service: KanbanService = kanban_service,
        interval: float = KANBAN_POLL_INTERVAL,
    ) -> None:
        self.store = runtime_store
        self.service = service
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sync_lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            self.service.ensure_board()
        except KanbanError as exc:
            logger.warning("[kanban-sync] ensure_board failed: %s", exc)
        while not self._stop.is_set():
            if self._sync_lock.acquire(blocking=False):
                try:
                    self.sync_once()
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[kanban-sync] sync failed: %s", exc)
                finally:
                    self._sync_lock.release()
            self._stop.wait(self.interval)

    def sync_once(self) -> None:
        links = list(self.store.snapshot().get("kanban_task_links") or [])
        for link in links:
            self._sync_link(link)
        self._create_ready_summary_tasks()
        self._sync_agent_kanban_state()

    def sync_once_async(self) -> bool:
        if not self._sync_lock.acquire(blocking=False):
            return False

        def _run() -> None:
            try:
                self.sync_once()
            except Exception as exc:  # noqa: BLE001
                logger.exception("[kanban-sync] async sync failed: %s", exc)
            finally:
                self._sync_lock.release()

        threading.Thread(target=_run, daemon=True).start()
        return True

    def sync_agent(self, agent_id: str) -> None:
        """Sync kanban links owned by one agent, in the background.

        Called when an agent transitions to idle so the card flips to
        `done` without waiting for the next poll tick.
        """
        agent = self.store.find_agent(agent_id) or {}
        profile = agent.get("profile_name") or ""
        if not profile:
            return
        targets = [
            link
            for link in (self.store.snapshot().get("kanban_task_links") or [])
            if link.get("assignee_profile") == profile
            and (link.get("kanban_status") or "").lower() not in {"done", "archived", "pending_dispatch"}
        ]
        if not targets:
            return

        def _run() -> None:
            for link in targets:
                try:
                    self._sync_link(link)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[kanban-sync] sync_agent failed task=%s error=%s", link.get("kanban_task_id"), exc)

        threading.Thread(target=_run, daemon=True).start()

    def _sync_link(self, link: dict) -> None:
        if (link.get("metadata") or {}).get("seeded_for_ui_test"):
            return
        if (link.get("kanban_status") or "").lower() == "pending_dispatch":
            return
        task_id = link["kanban_task_id"]
        try:
            task = self.service.show_task(task_id)
        except KanbanError as exc:
            logger.warning("[kanban-sync] show failed task=%s error=%s", task_id, exc)
            return
        status = task_status(task)
        local_status = (link.get("kanban_status") or "").lower()
        remote_status = (status or "").lower()
        if (
            local_status in TERMINAL_STATUSES
            and remote_status not in TERMINAL_STATUSES
            and not _task_was_unblocked(task)
        ):
            logger.warning(
                "[kanban-sync] ignore terminal rollback task=%s local=%s remote=%s",
                task_id,
                local_status,
                remote_status or "unknown",
            )
            return
        if local_status == "running" and remote_status in {"ready", "todo", "triage"}:
            if link.get("kanban_role") == "worker" and not _task_has_started(task):
                metadata = dict(link.get("metadata") or {})
                metadata.pop("dispatch_started_at", None)
                self.store.update_kanban_task_link(
                    task_id,
                    kanban_status=status,
                    last_result=task_result(task) or link.get("last_result") or "",
                    last_summary=_task_summary(task) or link.get("last_summary") or "",
                    metadata=metadata,
                )
                return
            logger.warning(
                "[kanban-sync] ignore active rollback task=%s local=%s remote=%s",
                task_id,
                local_status,
                remote_status,
            )
            return
        title = _task_title(task)
        result = task_result(task)
        metadata = {**(link.get("metadata") or {}), "task_title": title} if title else (link.get("metadata") or {})
        if (
            status != link.get("kanban_status")
            or result != link.get("last_result")
            or metadata != (link.get("metadata") or {})
        ):
            self.store.update_kanban_task_link(
                task_id,
                kanban_status=status,
                last_result=result or link.get("last_result") or "",
                last_summary=_task_summary(task) or link.get("last_summary") or "",
                metadata=metadata,
            )
            self.store.push_event(
                "kanban.task.updated",
                _agent_for_link(self.store, link),
                link["local_id"],
                {
                    "text": f"Kanban 任务 {task_id} 状态更新为 {status or 'unknown'}",
                    "kanban_task_id": task_id,
                    "status": status,
                },
            )
        if link.get("kanban_role") == "worker":
            self._sync_worker_link(link, status, result, task)
        elif link.get("kanban_role") == "summary":
            self._sync_summary_link(link, status, result, task)

    def _sync_worker_link(self, link: dict, status: str, result: str, task: dict) -> None:
        metadata = link.get("metadata") or {}
        if metadata.get("direct_worker"):
            if status in DONE_STATUSES | FAILED_STATUSES and not metadata.get("completed_projected"):
                self.store.mark_user_task_completed(link["local_id"])
                self.store.update_kanban_task_link(
                    link["kanban_task_id"],
                    metadata={**metadata, "completed_projected": True},
                )
            return
        delegation_id = metadata.get("delegation_id")
        assignment_id = link["local_id"]
        if not delegation_id:
            return
        if status in DONE_STATUSES:
            completed = self.store.complete_assignment(
                delegation_id,
                assignment_id,
                result=result or _task_summary(task) or "(Kanban 任务已完成，但没有结果)",
            )
            if completed:
                self.store.push_event(
                    "kanban.assignment.completed",
                    _agent_for_link(self.store, link),
                    assignment_id,
                    {
                        "text": f"Worker Kanban 任务 {link['kanban_task_id']} 已完成",
                        "kanban_task_id": link["kanban_task_id"],
                    },
                )
        elif status in FAILED_STATUSES:
            self.store.complete_assignment(
                delegation_id,
                assignment_id,
                result=result or f"Kanban task status: {status}",
                failed=True,
            )

    def _sync_summary_link(self, link: dict, status: str, result: str, task: dict) -> None:
        if status not in DONE_STATUSES:
            return
        user_task_id = (link.get("metadata") or {}).get("user_task_id") or link.get("parent_local_id")
        if not user_task_id:
            return
        current = self.store.find_kanban_task_link(kanban_task_id=link["kanban_task_id"])
        if current and current.get("metadata", {}).get("completed_projected"):
            return
        self.store.mark_user_task_completed(user_task_id)
        self.store.update_kanban_task_link(
            link["kanban_task_id"],
            last_result=result or _task_summary(task),
            metadata={**(link.get("metadata") or {}), "completed_projected": True},
        )
        self.store.push_event(
            "kanban.summary.completed",
            _agent_for_link(self.store, link),
            user_task_id,
            {
                "text": result or _task_summary(task) or "Leader 汇总任务已完成",
                "kanban_task_id": link["kanban_task_id"],
            },
        )

    def _create_ready_summary_tasks(self) -> None:
        snapshot = self.store.snapshot()
        for user_task in snapshot["user_tasks"]:
            if user_task.get("status") not in {"ready_to_summarize", "waiting_workers"}:
                continue
            user_task_id = user_task["user_task_id"]
            existing = self.store.find_kanban_task_link(
                local_type="user_task",
                local_id=user_task_id,
                kanban_role="summary",
            )
            if existing:
                continue
            assignments = _assignments_for_user_task(snapshot, user_task_id)
            if not assignments or not all(item["status"] in {"completed", "failed"} for item in assignments):
                continue
            leader = self.store.find_agent(user_task["leader_agent_id"]) or {}
            worker_links = [
                link
                for link in snapshot.get("kanban_task_links", [])
                if link.get("kanban_role") == "worker"
                and link.get("local_id") in {item["assignment_id"] for item in assignments}
            ]
            task_title = f"汇总用户任务：{user_task_id}"
            summary_task = self.service.create_task(
                task_title,
                body=_format_summary_body(user_task, assignments),
                assignee=leader["profile_name"],
                parent=[link["kanban_task_id"] for link in worker_links],
                workspace=workspace_for_agent(leader),
                idempotency_key=f"summary:{user_task_id}",
            )
            summary_task_id = extract_task_id(summary_task)
            self.store.mark_user_task_summarizing(user_task_id)
            self.store.upsert_kanban_task_link(
                local_type="user_task",
                local_id=user_task_id,
                kanban_task_id=summary_task_id,
                kanban_role="summary",
                kanban_status=task_status(summary_task) or "ready",
                assignee_profile=leader["profile_name"],
                parent_local_id=user_task_id,
                metadata={"user_task_id": user_task_id, "task_title": task_title},
            )
            self.store.push_event(
                "kanban.summary.created",
                user_task["leader_agent_id"],
                user_task_id,
                {
                    "text": f"已创建 leader 汇总 Kanban 任务 {summary_task_id}",
                    "kanban_task_id": summary_task_id,
                },
            )

    def _sync_agent_kanban_state(self) -> None:
        snapshot = self.store.snapshot()
        active_by_profile: dict[str, list[dict]] = {}
        for link in snapshot.get("kanban_task_links", []):
            status = (link.get("kanban_status") or "").lower()
            if status in {"done", "archived", "blocked", "failed", "crashed", "timed_out", "gave_up"}:
                continue
            if status not in {"ready", "running", "todo", "triage"}:
                continue
            profile = link.get("assignee_profile") or ""
            if not profile:
                continue
            active_by_profile.setdefault(profile, []).append(link)

        for agent in snapshot["agents"]:
            profile = agent.get("profile_name") or ""
            links = active_by_profile.get(profile, [])
            running = [item for item in links if (item.get("kanban_status") or "").lower() == "running"]
            ready = [
                item
                for item in links
                if (item.get("kanban_status") or "").lower() in {"ready", "todo", "triage"}
            ]
            if running:
                patch = {
                    "status": "busy",
                    "orchestration_state": "kanban_running",
                    "current_task": f"执行 {len(running)} 个 Kanban 任务",
                    "queue_depth": len(links),
                }
            elif ready:
                patch = {
                    "status": "waiting",
                    "orchestration_state": "kanban_ready",
                    "current_task": f"等待执行 {len(ready)} 个 Kanban 任务",
                    "queue_depth": len(links),
                }
            else:
                patch = {
                    "status": "idle",
                    "orchestration_state": "none",
                    "current_task": "空闲",
                    "queue_depth": 0,
                }
            if any(agent.get(key) != value for key, value in patch.items()):
                self.store.update_agent(agent["agent_id"], **patch)


def _task_summary(task: dict[str, Any]) -> str:
    for key in ("summary", "handoff_summary"):
        value = task.get(key)
        if value:
            return str(value)
    nested = task.get("task")
    if isinstance(nested, dict):
        return _task_summary(nested)
    return ""


def _task_title(task: dict[str, Any]) -> str:
    value = task.get("title")
    if value:
        return str(value)
    nested = task.get("task")
    if isinstance(nested, dict):
        return _task_title(nested)
    return ""


def _task_has_started(task: dict[str, Any]) -> bool:
    if task.get("started_at") or task.get("completed_at"):
        return True
    runs = task.get("runs")
    if isinstance(runs, list) and runs:
        return True
    nested = task.get("task")
    if isinstance(nested, dict):
        return _task_has_started(nested)
    return False


def _task_was_unblocked(task: dict[str, Any]) -> bool:
    events = task.get("events")
    if isinstance(events, list):
        return any(isinstance(event, dict) and event.get("kind") == "unblocked" for event in events)
    nested = task.get("task")
    if isinstance(nested, dict):
        return _task_was_unblocked(nested)
    return False


def _agent_for_link(runtime_store: RuntimeStore, link: dict) -> str:
    assignee = link.get("assignee_profile") or ""
    for agent in runtime_store.snapshot()["agents"]:
        if agent.get("profile_name") == assignee:
            return agent["agent_id"]
    return ""


def _assignments_for_user_task(snapshot: dict, user_task_id: str) -> list[dict]:
    result = []
    for delegation in snapshot["delegations"]:
        if delegation.get("user_task_id") != user_task_id:
            continue
        result.extend(delegation.get("assignments") or [])
    return result


def _format_summary_body(user_task: dict, assignments: list[dict]) -> str:
    parts = []
    for index, assignment in enumerate(assignments, start=1):
        parts.append(
            "\n".join(
                [
                    f"## {index}. {assignment['worker_name']} ({assignment['worker_agent_id']})",
                    f"assignment_id: {assignment['assignment_id']}",
                    f"子任务：{assignment['content']}",
                    f"状态：{assignment['status']}",
                    "结果：",
                    assignment.get("result") or "(空响应)",
                ]
            )
        )
    worker_results = "\n\n".join(parts) or "(没有 worker 结果)"
    return (
        "[KANBAN_LEADER_SUMMARY_TASK]\n"
        f"user_task_id: {user_task['user_task_id']}\n\n"
        "同一个用户任务拆分出的所有 worker Kanban 子任务已经结束。请只基于以下 worker 结果，面向用户输出最终总结。\n"
        "不要重复派发同一批任务；如有缺失或失败，请在总结中明确说明。\n\n"
        "用户原始任务：\n"
        f"{user_task.get('content') or ''}\n\n"
        "Worker 结果：\n"
        f"{worker_results}"
    )


sync_worker = KanbanSyncWorker()
