"""Agent registry operations for RuntimeStore."""
from __future__ import annotations

from ...config import now_iso


class AgentsMixin:
    def has_profile(self, profile_name: str) -> bool:
        with self._lock:
            return any(a["profile_name"] == profile_name for a in self.agents)

    def has_leader(self) -> bool:
        with self._lock:
            return any(a["role"] == "leader" for a in self.agents)

    def register_agent(self, agent: dict) -> None:
        with self._lock:
            existing = next(
                (
                    item
                    for item in self.agents
                    if item["agent_id"] == agent["agent_id"]
                    or item["profile_name"] == agent["profile_name"]
                ),
                None,
            )
            if existing is None:
                self.agents.append(agent)
                snapshot = dict(agent)
            else:
                existing.update(agent)
                snapshot = dict(existing)
        self._persist("upsert_agent", snapshot)

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
            snapshot = dict(agent)
        self._persist("upsert_agent", snapshot)
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
            removed_snapshot = dict(removed)
        self._persist("soft_delete_agent", agent_id, now_iso())
        self.push_agents_changed()
        return removed_snapshot
