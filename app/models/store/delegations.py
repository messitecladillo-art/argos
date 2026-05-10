"""Delegation & assignment operations for RuntimeStore."""
from __future__ import annotations

from ...config import now_iso
from .base import _log_store


class DelegationsMixin:
    def create_delegation(
        self,
        *,
        leader_agent_id: str,
        assignments: list[dict],
        summary_instruction: str,
        user_task_id: str | None = None,
        round_number: int | None = None,
    ) -> dict:
        now = now_iso()
        delegation_id = f"dlg_{next(self._delegation_ids):04d}"
        normalized_assignments = []
        with self._lock:
            leader = next(
                (a for a in self.agents if a["agent_id"] == leader_agent_id), None
            )
            if leader is None:
                raise ValueError("leader agent not found")
            task = self._find_user_task_locked(user_task_id) if user_task_id else None
            resolved_round = int(round_number or (task or {}).get("current_round") or 1)
            for assignment in assignments:
                worker_id = (assignment.get("to_agent_id") or "").strip()
                content = (assignment.get("content") or "").strip()
                if not worker_id:
                    raise ValueError("assignment.to_agent_id is required")
                if not content:
                    raise ValueError("assignment.content is required")
                worker = next(
                    (a for a in self.agents if a["agent_id"] == worker_id), None
                )
                if worker is None:
                    raise ValueError(f"worker agent not found: {worker_id}")
                normalized_assignments.append(
                    {
                        "assignment_id": f"asg_{next(self._assignment_ids):04d}",
                        "worker_agent_id": worker_id,
                        "worker_name": worker.get("name") or worker_id,
                        "content": content,
                        "message_id": None,
                        "status": "pending",
                        "result": None,
                        "completed_at": None,
                    }
                )
            delegation = {
                "delegation_id": delegation_id,
                "user_task_id": user_task_id,
                "leader_agent_id": leader_agent_id,
                "summary_instruction": (summary_instruction or "").strip()
                or "请汇总所有 worker 的结果，给用户输出最终答复。",
                "assignments": normalized_assignments,
                "status": "waiting_workers",
                "round": resolved_round,
                "review_task_id": None,
                "created_at": now,
                "completed_at": None,
                "summarized_at": None,
                "reviewed_at": None,
            }
            self.delegations.append(delegation)
            if user_task_id:
                task["delegation_ids"].append(delegation_id)
                task["status"] = "waiting_workers"
            leader["orchestration_state"] = "waiting_workers"
            leader["current_task"] = f"等待 {len(normalized_assignments)} 个 worker 返回"
            leader["queue_depth"] = max(leader.get("queue_depth") or 0, 1)
            leader["last_active_at"] = now
            delegation_snapshot = dict(delegation)
            task_snapshot = dict(task) if user_task_id else None
            leader_snapshot = dict(leader)
        self._persist("upsert_delegation", delegation_snapshot)
        if task_snapshot is not None:
            self._persist("upsert_user_task", task_snapshot)
        self._persist("upsert_agent", leader_snapshot)
        self.push_event(
            "delegation.created",
            leader_agent_id,
            delegation_id,
            {"text": f"已创建并行批次 {delegation_id}"},
        )
        _log_store(
            "delegation_created",
            delegation_id=delegation_id,
            user_task_id=user_task_id,
            leader_agent_id=leader_agent_id,
            assignment_count=len(normalized_assignments),
            round=delegation["round"],
        )
        self.push_agents_changed()
        return delegation

    def attach_assignment_message(
        self, delegation_id: str, assignment_id: str, message_id: str
    ) -> None:
        should_mark_started = False
        with self._lock:
            assignment = self._find_assignment_locked(delegation_id, assignment_id)
            assignment["message_id"] = message_id
            if assignment["status"] not in {"completed", "failed"}:
                assignment["status"] = "running"
                should_mark_started = True
            worker_agent_id = assignment["worker_agent_id"]
            worker_name = assignment["worker_name"]
            status = assignment["status"]
            assignment_snapshot = dict(assignment)
        self._persist("upsert_assignment", delegation_id, assignment_snapshot)
        if should_mark_started:
            self.push_event(
                "delegation.assignment.started",
                worker_agent_id,
                delegation_id,
                {"text": f"{worker_name} 已开始处理 {assignment_id}"},
            )
        _log_store(
            "assignment_started",
            delegation_id=delegation_id,
            assignment_id=assignment_id,
            message_id=message_id,
            status=status,
            emitted=should_mark_started,
        )

    def complete_assignment(
        self,
        delegation_id: str,
        assignment_id: str,
        *,
        result: str,
        failed: bool = False,
    ) -> dict | None:
        completed_summary = None
        completed_user_task = None
        with self._lock:
            delegation = self._find_delegation_locked(delegation_id)
            assignment = self._find_assignment_locked(delegation_id, assignment_id)
            if assignment["status"] in {"completed", "failed"}:
                return None
            assignment["status"] = "failed" if failed else "completed"
            assignment["result"] = result
            assignment["completed_at"] = now_iso()
            all_done = all(
                item["status"] in {"completed", "failed"}
                for item in delegation["assignments"]
            )
            if all_done and delegation["status"] == "waiting_workers":
                delegation["status"] = "ready_to_review"
                delegation["completed_at"] = now_iso()
                user_task_id = delegation.get("user_task_id")
                if user_task_id:
                    task = self._find_user_task_locked(user_task_id)
                    if self._current_round_ready_to_review_locked(task):
                        task["status"] = "ready_to_review"
                        completed_user_task = dict(task)
                else:
                    completed_summary = dict(delegation)
            assignment_snapshot = dict(assignment)
            delegation_snapshot = dict(delegation)
            user_task_snapshot = (
                dict(self._find_user_task_locked(delegation.get("user_task_id")))
                if delegation.get("user_task_id")
                else None
            )
        self._persist("upsert_assignment", delegation_id, assignment_snapshot)
        self._persist("upsert_delegation", delegation_snapshot)
        if user_task_snapshot is not None:
            self._persist("upsert_user_task", user_task_snapshot)
        self.push_event(
            "delegation.assignment.completed",
            assignment["worker_agent_id"],
            delegation_id,
            {"text": f"{assignment['worker_name']} 已完成 {assignment_id}"},
        )
        _log_store(
            "assignment_completed",
            delegation_id=delegation_id,
            assignment_id=assignment_id,
            status=assignment["status"],
            completed_summary=bool(completed_summary),
            completed_user_task=bool(completed_user_task),
        )
        if completed_summary is not None:
            self.push_event(
                "delegation.ready_to_summarize",
                completed_summary["leader_agent_id"],
                delegation_id,
                {"text": f"批次 {delegation_id} 的 worker 已全部返回"},
            )
        if completed_user_task is not None:
            self.push_event(
                "user_task.ready_to_summarize",
                completed_user_task["leader_agent_id"],
                completed_user_task["user_task_id"],
                {"text": "用户任务的 worker 已全部返回"},
            )
        self.push_agents_changed()
        return completed_user_task or completed_summary

    def mark_delegation_reviewing(self, delegation_id: str, review_task_id: str = "") -> None:
        leader_id = None
        with self._lock:
            delegation = self._find_delegation_locked(delegation_id)
            delegation["status"] = "reviewing"
            if review_task_id:
                delegation["review_task_id"] = review_task_id
            leader_id = delegation["leader_agent_id"]
            leader = next((a for a in self.agents if a["agent_id"] == leader_id), None)
            if leader is not None:
                leader["orchestration_state"] = "reviewing"
                leader["current_task"] = "复盘 worker 结果中"
                leader["last_active_at"] = now_iso()
            delegation_snapshot = dict(delegation)
            leader_snapshot = dict(leader) if leader is not None else None
        self._persist("upsert_delegation", delegation_snapshot)
        if leader_snapshot is not None:
            self._persist("upsert_agent", leader_snapshot)
        if leader_id:
            self.push_agents_changed()

    def mark_delegation_summarizing(self, delegation_id: str) -> None:
        self.mark_delegation_reviewing(delegation_id)

    def mark_delegation_reviewed(self, delegation_id: str) -> None:
        with self._lock:
            delegation = self._find_delegation_locked(delegation_id)
            delegation["status"] = "reviewed"
            delegation["summarized_at"] = delegation.get("summarized_at") or now_iso()
            delegation["reviewed_at"] = delegation.get("reviewed_at") or now_iso()
            leader_id = delegation["leader_agent_id"]
            has_waiting = any(
                item["leader_agent_id"] == leader_id
                and item["delegation_id"] != delegation_id
                and item["status"] in {"waiting_workers", "ready_to_review", "reviewing", "ready_to_summarize", "summarizing"}
                for item in self.delegations
            )
            leader = next((a for a in self.agents if a["agent_id"] == leader_id), None)
            if leader is not None and not has_waiting:
                leader["orchestration_state"] = "none"
                leader["last_active_at"] = now_iso()
            elif leader is not None:
                leader["orchestration_state"] = "waiting_workers"
                leader["current_task"] = "等待 worker 返回"
                leader["last_active_at"] = now_iso()
            delegation_snapshot = dict(delegation)
            leader_snapshot = dict(leader) if leader is not None else None
        self._persist("upsert_delegation", delegation_snapshot)
        if leader_snapshot is not None:
            self._persist("upsert_agent", leader_snapshot)
        self.push_agents_changed()

    def mark_delegation_summarized(self, delegation_id: str) -> None:
        self.mark_delegation_reviewed(delegation_id)
