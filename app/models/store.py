from __future__ import annotations

import json
import queue
import threading
from collections import deque
from itertools import count

from ..config import now_iso


class RuntimeStore:
    """In-memory agent registry with SSE pub/sub.

    Source of truth for persistence is the hermes CLI (profile dir) plus a
    per-profile `team-meta.json` sidecar. See services.registry for the
    disk I/O. This store holds runtime state only.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[str]] = []
        self._event_ids = count(1)
        self._message_ids = count(1)
        self._delegation_ids = count(1)
        self._assignment_ids = count(1)
        self.agents: list[dict] = []
        self.tasks: list[dict] = []
        self.delegations: list[dict] = []
        self.messages: deque = deque(maxlen=200)
        self.events: deque = deque(maxlen=400)

    # ------------------------------------------------------------------ snapshot
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "agents": list(self.agents),
                "tasks": list(self.tasks),
                "delegations": list(self.delegations),
                "messages": list(self.messages),
                "events": list(self.events),
                "stats": self._build_stats(),
            }

    def _build_stats(self) -> list[dict]:
        online = sum(1 for a in self.agents if a["status"] != "offline")
        active = sum(
            1
            for a in self.agents
            if a["status"] in {"busy", "waiting"}
            or a.get("orchestration_state") == "waiting_workers"
        )
        return [
            {"label": "在职员工", "value": f"{online:02d}", "hint": "当前接入运行单元"},
            {"label": "当前任务", "value": f"{active:02d}", "hint": "正在协同推进中"},
        ]

    # ------------------------------------------------------------------ agents
    def has_profile(self, profile_name: str) -> bool:
        with self._lock:
            return any(a["profile_name"] == profile_name for a in self.agents)

    def has_leader(self) -> bool:
        with self._lock:
            return any(a["role"] == "leader" for a in self.agents)

    def register_agent(self, agent: dict) -> None:
        with self._lock:
            self.agents.append(agent)

    def find_agent(self, agent_id: str) -> dict | None:
        with self._lock:
            return next((a for a in self.agents if a["agent_id"] == agent_id), None)

    def update_agent(self, agent_id: str, **patch) -> dict | None:
        with self._lock:
            agent = next((a for a in self.agents if a["agent_id"] == agent_id), None)
            if agent is None:
                return None
            agent.update(patch)
            agent["last_active_at"] = now_iso()
        self.push_agents_changed()
        return agent

    def remove_agent(self, agent_id: str) -> dict | None:
        with self._lock:
            idx = next(
                (i for i, a in enumerate(self.agents) if a["agent_id"] == agent_id),
                None,
            )
            if idx is None:
                return None
            removed = self.agents.pop(idx)
        self.push_agents_changed()
        return removed

    # ------------------------------------------------------------------ delegations
    def create_delegation(
        self,
        *,
        leader_agent_id: str,
        assignments: list[dict],
        summary_instruction: str,
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
                "leader_agent_id": leader_agent_id,
                "summary_instruction": (summary_instruction or "").strip()
                or "请汇总所有 worker 的结果，给用户输出最终答复。",
                "assignments": normalized_assignments,
                "status": "waiting_workers",
                "created_at": now,
                "completed_at": None,
                "summarized_at": None,
            }
            self.delegations.append(delegation)
            leader["orchestration_state"] = "waiting_workers"
            leader["current_task"] = f"等待 {len(normalized_assignments)} 个 worker 返回"
            leader["last_active_at"] = now
        self.push_event(
            "delegation.created",
            leader_agent_id,
            delegation_id,
            {"text": f"已创建并行批次 {delegation_id}"},
        )
        self.push_agents_changed()
        return delegation

    def attach_assignment_message(
        self, delegation_id: str, assignment_id: str, message_id: str
    ) -> None:
        with self._lock:
            assignment = self._find_assignment_locked(delegation_id, assignment_id)
            assignment["message_id"] = message_id
            assignment["status"] = "running"
        self.push_event(
            "delegation.assignment.started",
            assignment["worker_agent_id"],
            delegation_id,
            {"text": f"{assignment['worker_name']} 已开始处理 {assignment_id}"},
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
                delegation["status"] = "ready_to_summarize"
                delegation["completed_at"] = now_iso()
                completed_summary = dict(delegation)
        self.push_event(
            "delegation.assignment.completed",
            assignment["worker_agent_id"],
            delegation_id,
            {"text": f"{assignment['worker_name']} 已完成 {assignment_id}"},
        )
        if completed_summary is not None:
            self.push_event(
                "delegation.ready_to_summarize",
                completed_summary["leader_agent_id"],
                delegation_id,
                {"text": f"批次 {delegation_id} 的 worker 已全部返回"},
            )
        self.push_agents_changed()
        return completed_summary

    def mark_delegation_summarizing(self, delegation_id: str) -> None:
        leader_id = None
        with self._lock:
            delegation = self._find_delegation_locked(delegation_id)
            delegation["status"] = "summarizing"
            leader_id = delegation["leader_agent_id"]
            leader = next((a for a in self.agents if a["agent_id"] == leader_id), None)
            if leader is not None:
                leader["orchestration_state"] = "summarizing"
                leader["current_task"] = "汇总 worker 结果中"
                leader["last_active_at"] = now_iso()
        if leader_id:
            self.push_agents_changed()

    def mark_delegation_summarized(self, delegation_id: str) -> None:
        with self._lock:
            delegation = self._find_delegation_locked(delegation_id)
            delegation["status"] = "summarized"
            delegation["summarized_at"] = now_iso()
            leader_id = delegation["leader_agent_id"]
            has_waiting = any(
                item["leader_agent_id"] == leader_id
                and item["delegation_id"] != delegation_id
                and item["status"] in {"waiting_workers", "ready_to_summarize", "summarizing"}
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
        self.push_agents_changed()

    def _find_delegation_locked(self, delegation_id: str) -> dict:
        delegation = next(
            (d for d in self.delegations if d["delegation_id"] == delegation_id), None
        )
        if delegation is None:
            raise ValueError("delegation not found")
        return delegation

    def _find_assignment_locked(self, delegation_id: str, assignment_id: str) -> dict:
        delegation = self._find_delegation_locked(delegation_id)
        assignment = next(
            (a for a in delegation["assignments"] if a["assignment_id"] == assignment_id),
            None,
        )
        if assignment is None:
            raise ValueError("assignment not found")
        return assignment

    # ------------------------------------------------------------------ messages
    def record_message(
        self,
        content: str,
        to_agent_id: str,
        *,
        from_agent_id: str | None = None,
        delegation_id: str | None = None,
        assignment_id: str | None = None,
    ) -> dict:
        with self._lock:
            agent = next(
                (a for a in self.agents if a["agent_id"] == to_agent_id), None
            )
            if agent is None:
                raise ValueError("target agent not found")
            from_name = "User"
            if from_agent_id:
                sender = next(
                    (a for a in self.agents if a["agent_id"] == from_agent_id),
                    None,
                )
                if sender is not None:
                    from_name = sender["name"]
            message = {
                "message_id": f"msg_{next(self._message_ids):04d}",
                "from_agent_id": from_agent_id,
                "from_name": from_name,
                "to_name": agent["name"],
                "content": content,
                "delegation_id": delegation_id,
                "assignment_id": assignment_id,
                "created_at": now_iso(),
            }
            self.messages.appendleft(message)
            agent["last_input"] = content
            agent["last_active_at"] = now_iso()
            agent_id = agent["agent_id"]
        self.push_event("message.sent", agent_id, None, {"text": content})
        return message

    # ------------------------------------------------------------------ SSE
    def subscribe(self) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[str]) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _broadcast(self, payload: str) -> None:
        for subscriber in list(self._subscribers):
            subscriber.put(payload)

    def push_event(
        self, event_type: str, agent_id: str, task_id: str | None, data: dict
    ) -> dict:
        event = {
            "id": f"evt_{next(self._event_ids):04d}",
            "event_type": event_type,
            "agent_id": agent_id,
            "task_id": task_id,
            "timestamp": now_iso(),
            "data": data,
        }
        payload = f"event: event\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        with self._lock:
            self.events.appendleft(event)
            self._broadcast(payload)
        return event

    def push_agents_changed(self) -> None:
        body = {"agents": list(self.agents), "stats": self._build_stats()}
        payload = f"event: agents\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"
        with self._lock:
            self._broadcast(payload)


store = RuntimeStore()
