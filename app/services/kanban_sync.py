from __future__ import annotations

import logging
import threading
import time
from typing import Any

from ..config import KANBAN_POLL_INTERVAL
from ..config import DEFAULT_MAX_TASK_ROUNDS
from ..models.store import RuntimeStore, store as default_store
from .acp.helpers import _clean_agent_reply
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
        self._create_ready_review_tasks()
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
        elif link.get("kanban_role") in {"review", "summary"}:
            self._sync_review_link(link, status, result, task)

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
            if status == "crashed" and self._auto_complete_crashed_worker(link, task):
                return
            self.store.complete_assignment(
                delegation_id,
                assignment_id,
                result=result or f"Kanban task status: {status}",
                failed=True,
            )

    def _auto_complete_crashed_worker(self, link: dict, task: dict) -> bool:
        metadata = link.get("metadata") or {}
        if metadata.get("auto_complete_attempted"):
            return False
        summary = _crashed_task_summary(task)
        if not summary:
            return False
        task_id = link["kanban_task_id"]
        try:
            self.service.complete_task(
                task_id,
                result=summary,
                summary=summary,
                metadata={"auto_completed_after_crash": True},
            )
        except KanbanError as exc:
            logger.warning("[kanban-sync] auto-complete crashed worker failed task=%s error=%s", task_id, exc)
            self.store.update_kanban_task_link(
                task_id,
                metadata={**metadata, "auto_complete_attempted": True, "auto_complete_error": str(exc)},
            )
            return False
        self.store.update_kanban_task_link(
            task_id,
            kanban_status="done",
            last_result=summary,
            last_summary=summary,
            metadata={**metadata, "auto_completed_after_crash": True, "auto_complete_attempted": True},
        )
        delegation_id = metadata.get("delegation_id")
        if delegation_id:
            self.store.complete_assignment(delegation_id, link["local_id"], result=summary)
        return True

    def _sync_review_link(self, link: dict, status: str, result: str, task: dict) -> None:
        user_task_id = (link.get("metadata") or {}).get("user_task_id") or link.get("parent_local_id")
        if not user_task_id:
            return
        if status in FAILED_STATUSES:
            reason = result or _task_summary(task) or f"Kanban task status: {status}"
            self.store.mark_user_task_blocked(user_task_id, reason)
            self.store.update_kanban_task_link(
                link["kanban_task_id"],
                last_result=reason,
                metadata={**(link.get("metadata") or {}), "completed_projected": True},
            )
            return
        if status not in DONE_STATUSES:
            return
        current = self.store.find_kanban_task_link(kanban_task_id=link["kanban_task_id"])
        if current and current.get("metadata", {}).get("completed_projected"):
            return
        metadata = link.get("metadata") or {}
        round_number = int(metadata.get("round") or 1)
        has_next_round = any(
            delegation.get("user_task_id") == user_task_id
            and int(delegation.get("round") or 1) == round_number + 1
            for delegation in self.store.snapshot().get("delegations", [])
        )
        for delegation in self.store.snapshot().get("delegations", []):
            if (
                delegation.get("user_task_id") == user_task_id
                and int(delegation.get("round") or 1) == round_number
                and delegation.get("status") != "reviewed"
            ):
                self.store.mark_delegation_reviewed(delegation["delegation_id"])
        if not has_next_round:
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
                "text": result or _task_summary(task) or "Leader review 任务已完成",
                "kanban_task_id": link["kanban_task_id"],
            },
        )

    def _create_ready_review_tasks(self) -> None:
        snapshot = self.store.snapshot()
        for user_task in snapshot["user_tasks"]:
            if user_task.get("status") not in {"ready_to_review", "ready_to_summarize", "waiting_workers"}:
                continue
            user_task_id = user_task["user_task_id"]
            current_round = int(user_task.get("current_round") or 1)
            existing = next(
                (
                    link
                    for link in snapshot.get("kanban_task_links", [])
                    if link.get("local_type") == "user_task"
                    and link.get("kanban_role") in {"review", "summary"}
                    and (link.get("metadata") or {}).get("user_task_id") == user_task_id
                    and int((link.get("metadata") or {}).get("round") or 1) == current_round
                ),
                None,
            )
            if existing:
                continue
            assignments = _assignments_for_user_task_round(snapshot, user_task_id, current_round)
            if not assignments or not all(item["status"] in {"completed", "failed"} for item in assignments):
                continue
            leader = self.store.find_agent(user_task["leader_agent_id"]) or {}
            worker_links = [
                link
                for link in snapshot.get("kanban_task_links", [])
                if link.get("kanban_role") == "worker"
                and link.get("local_id") in {item["assignment_id"] for item in assignments}
            ]
            task_title = f"Review 用户任务 {user_task_id} 第 {current_round} 轮"
            review_task = self.service.create_task(
                task_title,
                body=_format_review_body(user_task, assignments, current_round),
                assignee=leader["profile_name"],
                parent=[link["kanban_task_id"] for link in worker_links],
                workspace=workspace_for_agent(leader),
                idempotency_key=f"review:{user_task_id}:round:{current_round}",
            )
            review_task_id = extract_task_id(review_task)
            self.store.mark_user_task_reviewing(user_task_id, review_task_id=review_task_id)
            self.store.upsert_kanban_task_link(
                local_type="user_task",
                local_id=f"{user_task_id}:round:{current_round}",
                kanban_task_id=review_task_id,
                kanban_role="review",
                kanban_status=task_status(review_task) or "ready",
                assignee_profile=leader["profile_name"],
                parent_local_id=user_task_id,
                metadata={
                    "user_task_id": user_task_id,
                    "round": current_round,
                    "kind": "review",
                    "task_title": task_title,
                    "assignee_agent_id": leader.get("agent_id") or user_task["leader_agent_id"],
                },
            )
            self.store.push_event(
                "kanban.summary.created",
                user_task["leader_agent_id"],
                user_task_id,
                {
                    "text": f"已创建 leader review Kanban 任务 {review_task_id}",
                    "kanban_task_id": review_task_id,
                },
            )

    def _create_ready_summary_tasks(self) -> None:
        self._create_ready_review_tasks()

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


def _crashed_task_summary(task: dict[str, Any]) -> str:
    summary = _task_summary(task) or task_result(task)
    if summary:
        return summary.strip()
    runs = task.get("runs")
    if isinstance(runs, list):
        for run in reversed(runs):
            if not isinstance(run, dict):
                continue
            for key in ("summary", "output", "stdout", "log"):
                value = run.get(key)
                if isinstance(value, str) and value.strip():
                    cleaned = _clean_agent_reply(value)
                    if cleaned:
                        return cleaned[-2000:]
    nested = task.get("task")
    if isinstance(nested, dict):
        return _crashed_task_summary(nested)
    return ""


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


def _assignments_for_user_task_round(snapshot: dict, user_task_id: str, round_number: int) -> list[dict]:
    result = []
    for delegation in snapshot["delegations"]:
        if delegation.get("user_task_id") != user_task_id:
            continue
        if int(delegation.get("round") or 1) != round_number:
            continue
        result.extend(delegation.get("assignments") or [])
    return result


def _format_review_body(user_task: dict, assignments: list[dict], round_number: int) -> str:
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
    max_rounds = int(user_task.get("max_rounds") or DEFAULT_MAX_TASK_ROUNDS)
    return (
        "[KANBAN_LEADER_REVIEW_TASK]\n"
        f"user_task_id: {user_task['user_task_id']}\n\n"
        f"round: {round_number}\n"
        f"max_rounds: {max_rounds}\n\n"
        "这是长时任务 checkpoint。请基于用户原始目标和本轮 worker 结果判断下一步。\n"
        "你必须选择一种行动：\n"
        "1. 如果目标已经完成：调用 kanban_complete(summary=最终答复)。\n"
        "2. 如果目标未完成且 round < max_rounds：调用 mcp_agent_bus_create_kanban_worker_tasks 创建下一轮 worker 子任务。\n"
        "   - 必须传 user_task_id。\n"
        "   - 必须传 parent_task_id 为当前 review Kanban task id。\n"
        "   - 子任务必须是下一轮需要的新工作，不要重复当前轮已经完成的同一批任务。\n"
        "   - 创建后调用 kanban_complete(summary=本轮复盘和下一轮计划)。\n"
        "3. 如果无法继续或已达到 max_rounds：调用 kanban_complete(summary=当前最佳结果和未完成/阻塞原因)，不要继续派发。\n\n"
        "用户原始任务：\n"
        f"{user_task.get('content') or ''}\n\n"
        "本轮 Worker 结果：\n"
        f"{worker_results}"
    )


def _format_summary_body(user_task: dict, assignments: list[dict]) -> str:
    return _format_review_body(user_task, assignments, int(user_task.get("current_round") or 1))


sync_worker = KanbanSyncWorker()
