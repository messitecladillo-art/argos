"""Inter-agent message recording for RuntimeStore."""
from __future__ import annotations

from ...config import now_iso


class MessagesMixin:
    def record_message(
        self,
        content: str,
        to_agent_id: str,
        *,
        from_agent_id: str | None = None,
        delegation_id: str | None = None,
        assignment_id: str | None = None,
        user_task_id: str | None = None,
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
                "to_agent_id": agent["agent_id"],
                "to_name": agent["name"],
                "content": content,
                "delegation_id": delegation_id,
                "assignment_id": assignment_id,
                "user_task_id": user_task_id,
                "created_at": now_iso(),
            }
            self.messages.appendleft(message)
            agent["last_input"] = content
            agent["last_active_at"] = now_iso()
            agent_id = agent["agent_id"]
            message_snapshot = dict(message)
            agent_snapshot = dict(agent)
        self._persist("insert_message", message_snapshot)
        self._persist("upsert_agent", agent_snapshot)
        self.push_event("message.sent", agent_id, None, {"text": content})
        return message
