from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
from collections import deque
from datetime import datetime, timezone
from itertools import count


UTC = timezone.utc
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ProfileError(RuntimeError):
    pass


class RuntimeStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[str]] = []
        self._event_ids = count(1)
        self._message_ids = count(1)
        self._agent_ids = count(1)
        self.agents: list[dict] = []
        self.tasks: list[dict] = []
        self.messages: deque = deque(maxlen=200)
        self.events: deque = deque(maxlen=400)

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

    def push_event(self, event_type: str, agent_id: str, task_id: str | None, data: dict) -> dict:
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

    def add_message(self, content: str, to_agent_id: str) -> dict:
        with self._lock:
            agent = next((a for a in self.agents if a["agent_id"] == to_agent_id), None)
        if agent is None:
            raise ValueError("target agent not found")
        message = {
            "message_id": f"msg_{next(self._message_ids):04d}",
            "from_name": "User",
            "to_name": agent["name"],
            "content": content,
            "created_at": now_iso(),
        }
        with self._lock:
            self.messages.appendleft(message)
            agent["last_input"] = content
            agent["last_active_at"] = now_iso()
        self.push_event("message.sent", agent["agent_id"], None, {"text": content})
        return message

    def create_agent(
        self,
        *,
        name: str,
        profile_name: str,
        role: str = "specialist",
        description: str = "",
        skills: list[str] | None = None,
        clone_from: str | None = None,
    ) -> dict:
        name = name.strip()
        profile_name = profile_name.strip().lower()
        if not name:
            raise ValueError("name is required")
        if not PROFILE_NAME_RE.match(profile_name):
            raise ValueError("profile_name must be lowercase alphanumeric (dash/underscore allowed)")
        if role not in {"leader", "specialist", "custom"}:
            raise ValueError("role must be one of leader/specialist/custom")

        with self._lock:
            if any(a["profile_name"] == profile_name for a in self.agents):
                raise ValueError(f"profile '{profile_name}' is already registered")

        cmd = ["hermes", "profile", "create", profile_name, "--no-alias"]
        if clone_from:
            cmd += ["--clone-from", clone_from]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except FileNotFoundError as exc:
            raise ProfileError("hermes CLI not found in PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise ProfileError("hermes profile create timed out") from exc
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            if "already exists" not in stderr.lower():
                raise ProfileError(stderr or "hermes profile create failed")

        agent = {
            "agent_id": f"agent_{next(self._agent_ids):04d}",
            "name": name,
            "profile_name": profile_name,
            "role": role,
            "description": description.strip(),
            "skills": skills or [],
            "status": "idle",
            "current_task": "空闲",
            "load": 0,
            "last_input": "",
            "last_output": "",
            "is_leader": role == "leader",
            "created_at": now_iso(),
            "last_active_at": now_iso(),
        }
        with self._lock:
            if agent["is_leader"]:
                for other in self.agents:
                    other["is_leader"] = False
            self.agents.append(agent)
        self.push_event(
            "agent.created",
            agent["agent_id"],
            None,
            {"text": f"Agent {agent['name']} 已创建（profile={profile_name}）"},
        )
        self.push_agents_changed()
        return agent

    def list_profiles(self) -> list[str]:
        try:
            result = subprocess.run(
                ["hermes", "profile", "list"], capture_output=True, text=True, timeout=15
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        names: list[str] = []
        for line in (result.stdout or "").splitlines():
            stripped = line.strip().lstrip("◆").strip()
            if not stripped:
                continue
            first = stripped.split()[0]
            if first.lower() == "profile" or set(first) <= {"─", "-"}:
                continue
            if PROFILE_NAME_RE.match(first):
                names.append(first)
        return names


store = RuntimeStore()
