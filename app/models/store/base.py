"""Base class for RuntimeStore: core state, persistence bridge, snapshot.

The public `RuntimeStore` is assembled in `app.models.store.__init__` by
layering feature mixins (agents/user_tasks/delegations/messages/events) on
top of this base. Locked-lookup helpers used by multiple mixins live here
so each mixin can call `self._find_*_locked(...)` freely.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from collections import deque
from itertools import count
from typing import Any

from ...db import SQLitePersistence


logger = logging.getLogger("hermes.agent_state")

NON_PERSISTED_EVENT_TYPES = {
    # High-volume terminal stream events are transport/UI state, not durable
    # audit history. Persisting them can generate thousands of rows per task.
    "agent.terminal.output",
    "agent.terminal.snapshot",
}


def _log_store(event: str, **fields) -> None:
    details = " ".join(f"{key}={value!r}" for key, value in fields.items())
    logger.warning("[agent-store] %s %s", event, details)


class RuntimeStoreBase:
    """In-memory agent registry with SSE pub/sub.

    Source of truth for persistence is the hermes CLI (profile dir) plus a
    per-profile `team-meta.json` sidecar. See services.registry for the
    disk I/O. This store holds runtime state only.
    """

    def __init__(self, persistence: SQLitePersistence | None = None) -> None:
        self._lock = threading.Lock()
        self.persistence = persistence
        self._subscribers: list[queue.Queue[str]] = []
        self._event_ids = count(1)
        self._message_ids = count(1)
        self._user_task_ids = count(1)
        self._delegation_ids = count(1)
        self._assignment_ids = count(1)
        self.agents: list[dict] = []
        self.user_tasks: list[dict] = []
        self.tasks: list[dict] = []
        self.delegations: list[dict] = []
        self.messages: deque = deque(maxlen=200)
        self.events: deque = deque(maxlen=400)

    def _persist(self, method_name: str, *args: Any) -> None:
        if self.persistence is None:
            return
        try:
            getattr(self.persistence, method_name)(*args)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[agent-store] persistence_failed method=%s error=%s", method_name, exc)

    def load_persisted_state(self) -> None:
        if self.persistence is None:
            return
        state = self.persistence.load_runtime_state()
        with self._lock:
            self.agents = state["agents"]
            self.user_tasks = state["user_tasks"]
            self.delegations = state["delegations"]
            self.messages = state["messages"]
            self.events = state["events"]
            self._event_ids = state["event_ids"]
            self._message_ids = state["message_ids"]
            self._user_task_ids = state["user_task_ids"]
            self._delegation_ids = state["delegation_ids"]
            self._assignment_ids = state["assignment_ids"]

    def _sorted_agents(self) -> list[dict]:
        return sorted(
            self.agents,
            key=lambda agent: agent.get("role") != "leader",
        )

    # ------------------------------------------------------------------ snapshot
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "agents": self._sorted_agents(),
                "user_tasks": list(self.user_tasks),
                "tasks": list(self.tasks),
                "delegations": list(self.delegations),
                "messages": list(self.messages),
                "events": list(self.events),
                "stats": self._build_stats(),
            }

    def _build_stats(self) -> list[dict]:
        online = sum(
            1
            for a in self.agents
            if a["status"] != "offline"
            and (a.get("readiness_status") or "ready") == "ready"
        )
        active = sum(
            1
            for a in self.agents
            if (a.get("readiness_status") or "ready") == "ready"
            and (
                a["status"] in {"busy", "waiting"}
                or a.get("orchestration_state") == "waiting_workers"
                or any(
                    item["leader_agent_id"] == a["agent_id"]
                    and item["status"]
                    in {"running", "waiting_workers", "ready_to_summarize", "summarizing"}
                    for item in self.user_tasks
                )
            )
        )
        return [
            {"label": "在职员工", "value": f"{online:02d}", "hint": "当前接入运行单元"},
            {"label": "当前任务", "value": f"{active:02d}", "hint": "正在协同推进中"},
        ]

    # ------------------------------------------------------------------ locked lookups (shared)
    def _find_delegation_locked(self, delegation_id: str) -> dict:
        delegation = next(
            (d for d in self.delegations if d["delegation_id"] == delegation_id), None
        )
        if delegation is None:
            raise ValueError("delegation not found")
        return delegation

    def _find_user_task_locked(self, user_task_id: str) -> dict:
        task = next(
            (d for d in self.user_tasks if d["user_task_id"] == user_task_id), None
        )
        if task is None:
            raise ValueError("user task not found")
        return task

    def _user_task_ready_to_summarize_locked(self, task: dict) -> bool:
        if not task.get("dispatch_closed") or task.get("summary_requested_at"):
            return False
        delegation_ids = task.get("delegation_ids") or []
        if not delegation_ids:
            return False
        return all(
            self._find_delegation_locked(delegation_id)["status"]
            in {"ready_to_summarize", "summarizing", "summarized"}
            for delegation_id in delegation_ids
        )

    def _find_assignment_locked(self, delegation_id: str, assignment_id: str) -> dict:
        delegation = self._find_delegation_locked(delegation_id)
        assignment = next(
            (a for a in delegation["assignments"] if a["assignment_id"] == assignment_id),
            None,
        )
        if assignment is None:
            raise ValueError("assignment not found")
        return assignment

    # Event helpers are provided by EventsMixin; declare names here as
    # type hints for static checkers. Runtime resolution goes through MRO.
    def _broadcast(self, payload: str) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def push_event(
        self, event_type: str, agent_id: str, task_id: str | None, data: dict
    ) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError

    def push_agents_changed(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError
