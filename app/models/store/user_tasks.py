"""User-task lifecycle operations for RuntimeStore."""
from __future__ import annotations

from ...config import now_iso
from .base import _log_store


class UserTasksMixin:
    def create_user_task(self, *, leader_agent_id: str, content: str) -> dict:
        now = now_iso()
        with self._lock:
            leader = next(
                (a for a in self.agents if a["agent_id"] == leader_agent_id), None
            )
            if leader is None:
                raise ValueError("leader agent not found")
            task = {
                "user_task_id": f"ut_{next(self._user_task_ids):04d}",
                "leader_agent_id": leader_agent_id,
                "content": (content or "").strip(),
                "delegation_ids": [],
                "status": "running",
                "dispatch_closed": False,
                "summary_requested_at": None,
                "completed_at": None,
                "created_at": now,
            }
            self.user_tasks.append(task)
            leader["last_active_at"] = now
            task_snapshot = dict(task)
            leader_snapshot = dict(leader)
        self._persist("upsert_user_task", task_snapshot)
        self._persist("upsert_agent", leader_snapshot)
        self.push_event(
            "user_task.created",
            leader_agent_id,
            task["user_task_id"],
            {"text": "用户任务已创建"},
        )
        _log_store("user_task_created", user_task_id=task["user_task_id"], leader_agent_id=leader_agent_id)
        self.push_agents_changed()
        return task

    def count_active_user_tasks(
        self, leader_agent_id: str, *, exclude_user_task_id: str | None = None
    ) -> int:
        with self._lock:
            return sum(
                1
                for item in self.user_tasks
                if item["leader_agent_id"] == leader_agent_id
                and item["user_task_id"] != exclude_user_task_id
                and item["status"]
                in {"running", "waiting_workers", "ready_to_summarize", "summarizing"}
            )

    def close_user_task_dispatch(self, user_task_id: str) -> dict | None:
        ready_task = None
        completed_task = None
        with self._lock:
            task = self._find_user_task_locked(user_task_id)
            if task["status"] == "completed":
                return None
            task["dispatch_closed"] = True
            leader = next(
                (a for a in self.agents if a["agent_id"] == task["leader_agent_id"]),
                None,
            )
            if not task["delegation_ids"]:
                task["status"] = "completed"
                task["completed_at"] = now_iso()
                completed_task = dict(task)
                if leader is not None:
                    leader["orchestration_state"] = "none"
                    leader["current_task"] = "空闲"
                    leader["queue_depth"] = 0
                    leader["last_active_at"] = now_iso()
            elif self._user_task_ready_to_summarize_locked(task):
                task["status"] = "ready_to_summarize"
                ready_task = dict(task)
                if leader is not None:
                    leader["orchestration_state"] = "summarizing"
                    leader["current_task"] = "准备汇总 worker 结果"
                    leader["queue_depth"] = max(leader.get("queue_depth") or 0, 1)
                    leader["last_active_at"] = now_iso()
            else:
                task["status"] = "waiting_workers"
                if leader is not None:
                    leader["orchestration_state"] = "waiting_workers"
                    leader["current_task"] = "等待 worker 返回"
                    leader["queue_depth"] = max(leader.get("queue_depth") or 0, 1)
                    leader["last_active_at"] = now_iso()
            task_snapshot = dict(task)
            leader_snapshot = dict(leader) if leader is not None else None
        self._persist("upsert_user_task", task_snapshot)
        if leader_snapshot is not None:
            self._persist("upsert_agent", leader_snapshot)
        if completed_task is not None:
            self.push_event(
                "user_task.completed",
                completed_task["leader_agent_id"],
                user_task_id,
                {"text": "用户任务已直接完成"},
            )
            _log_store("user_task_completed_direct", user_task_id=user_task_id)
        else:
            _log_store("user_task_dispatch_closed", user_task_id=user_task_id, ready=bool(ready_task), status=task["status"])
        self.push_agents_changed()
        return ready_task

    def mark_user_task_summarizing(self, user_task_id: str) -> dict:
        with self._lock:
            task = self._find_user_task_locked(user_task_id)
            task["status"] = "summarizing"
            task["summary_requested_at"] = task["summary_requested_at"] or now_iso()
            for delegation_id in task["delegation_ids"]:
                delegation = self._find_delegation_locked(delegation_id)
                if delegation["status"] in {"ready_to_summarize", "waiting_workers"}:
                    delegation["status"] = "summarizing"
            leader = next(
                (a for a in self.agents if a["agent_id"] == task["leader_agent_id"]),
                None,
            )
            if leader is not None:
                leader["orchestration_state"] = "summarizing"
                leader["current_task"] = "汇总 worker 结果中"
                leader["queue_depth"] = max(leader.get("queue_depth") or 0, 1)
                leader["last_active_at"] = now_iso()
            snapshot = dict(task)
            leader_snapshot = dict(leader) if leader is not None else None
            delegation_snapshots = [
                dict(self._find_delegation_locked(delegation_id))
                for delegation_id in task["delegation_ids"]
            ]
        self._persist("upsert_user_task", snapshot)
        if leader_snapshot is not None:
            self._persist("upsert_agent", leader_snapshot)
        for delegation_snapshot in delegation_snapshots:
            self._persist("upsert_delegation", delegation_snapshot)
        _log_store("user_task_summarizing", user_task_id=user_task_id)
        self.push_agents_changed()
        return snapshot

    def mark_user_task_completed(self, user_task_id: str) -> None:
        with self._lock:
            task = self._find_user_task_locked(user_task_id)
            task["status"] = "completed"
            task["completed_at"] = now_iso()
            for delegation_id in task["delegation_ids"]:
                delegation = self._find_delegation_locked(delegation_id)
                delegation["status"] = "summarized"
                delegation["summarized_at"] = delegation["summarized_at"] or now_iso()
            leader_id = task["leader_agent_id"]
            leader = next((a for a in self.agents if a["agent_id"] == leader_id), None)
            has_active = any(
                item["leader_agent_id"] == leader_id
                and item["user_task_id"] != user_task_id
                and item["status"]
                in {"running", "waiting_workers", "ready_to_summarize", "summarizing"}
                for item in self.user_tasks
            )
            if leader is not None and not has_active:
                leader["orchestration_state"] = "none"
                leader["current_task"] = "空闲"
                leader["queue_depth"] = 0
                leader["last_active_at"] = now_iso()
            task_snapshot = dict(task)
            leader_snapshot = dict(leader) if leader is not None else None
            delegation_snapshots = [
                dict(self._find_delegation_locked(delegation_id))
                for delegation_id in task["delegation_ids"]
            ]
        self._persist("upsert_user_task", task_snapshot)
        if leader_snapshot is not None:
            self._persist("upsert_agent", leader_snapshot)
        for delegation_snapshot in delegation_snapshots:
            self._persist("upsert_delegation", delegation_snapshot)
        self.push_event(
            "user_task.completed",
            leader_id,
            user_task_id,
            {"text": "用户任务汇总完成"},
        )
        _log_store("user_task_completed", user_task_id=user_task_id, leader_agent_id=leader_id)
        self.push_agents_changed()
