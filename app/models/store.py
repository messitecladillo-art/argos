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
        self.agents: list[dict] = []
        self.tasks: list[dict] = []
        self.messages: deque = deque(maxlen=200)
        self.events: deque = deque(maxlen=400)

    # ------------------------------------------------------------------ snapshot
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "agents": list(self.agents),
                "tasks": list(self.tasks),
                "messages": list(self.messages),
                "events": list(self.events),
                "stats": self._build_stats(),
            }

    def _build_stats(self) -> list[dict]:
        online = sum(1 for a in self.agents if a["status"] != "offline")
        active = sum(1 for a in self.agents if a["status"] in {"busy", "waiting"})
        return [
            {"label": "Online Agents", "value": f"{online:02d}", "hint": "当前接入运行单元"},
            {"label": "Active Tasks", "value": f"{active:02d}", "hint": "正在协同推进中"},
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

    # ------------------------------------------------------------------ messages
    def record_message(
        self,
        content: str,
        to_agent_id: str,
        *,
        from_agent_id: str | None = None,
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
