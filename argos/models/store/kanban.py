"""Kanban task link operations for RuntimeStore."""
from __future__ import annotations

from ...config import now_iso


class KanbanLinksMixin:
    def upsert_kanban_task_link(
        self,
        *,
        local_type: str,
        local_id: str,
        kanban_task_id: str,
        kanban_role: str,
        kanban_status: str = "",
        assignee_profile: str = "",
        parent_local_id: str | None = None,
        last_result: str = "",
        last_summary: str = "",
        summary_created: bool = False,
        metadata: dict | None = None,
    ) -> dict:
        now = now_iso()
        with self._lock:
            existing = next(
                (
                    item
                    for item in self.kanban_task_links
                    if (
                        item["local_type"] == local_type
                        and item["local_id"] == local_id
                        and item["kanban_role"] == kanban_role
                    )
                    or item["kanban_task_id"] == kanban_task_id
                ),
                None,
            )
            payload = {
                "local_type": local_type,
                "local_id": local_id,
                "kanban_task_id": kanban_task_id,
                "kanban_role": kanban_role,
                "kanban_status": kanban_status,
                "assignee_profile": assignee_profile,
                "parent_local_id": parent_local_id,
                "last_result": last_result,
                "last_summary": last_summary,
                "summary_created": summary_created,
                "metadata": metadata or {},
                "created_at": now,
                "updated_at": now,
            }
            if existing is None:
                self.kanban_task_links.append(payload)
                snapshot = dict(payload)
            else:
                payload["created_at"] = existing.get("created_at") or now
                existing.update(payload)
                existing["updated_at"] = now
                snapshot = dict(existing)
        self._persist("upsert_kanban_task_link", snapshot)
        self.push_event(
            "kanban.link.changed",
            agent_id="",
            task_id=snapshot.get("kanban_task_id"),
            data={"action": "upsert", "link": snapshot},
        )
        return snapshot

    def update_kanban_task_link(self, kanban_task_id: str, **patch) -> dict | None:
        with self._lock:
            link = next(
                (
                    item
                    for item in self.kanban_task_links
                    if item["kanban_task_id"] == kanban_task_id
                ),
                None,
            )
            if link is None:
                return None
            link.update(patch)
            link["updated_at"] = now_iso()
            snapshot = dict(link)
        self._persist("upsert_kanban_task_link", snapshot)
        self.push_event(
            "kanban.link.changed",
            agent_id="",
            task_id=snapshot.get("kanban_task_id"),
            data={"action": "update", "link": snapshot},
        )
        return snapshot

    def find_kanban_task_link(
        self,
        *,
        local_type: str | None = None,
        local_id: str | None = None,
        kanban_role: str | None = None,
        kanban_task_id: str | None = None,
    ) -> dict | None:
        with self._lock:
            for item in self.kanban_task_links:
                if kanban_task_id and item["kanban_task_id"] != kanban_task_id:
                    continue
                if local_type and item["local_type"] != local_type:
                    continue
                if local_id and item["local_id"] != local_id:
                    continue
                if kanban_role and item["kanban_role"] != kanban_role:
                    continue
                return dict(item)
        return None

    def kanban_links_for_local(self, local_type: str, local_id: str) -> list[dict]:
        with self._lock:
            return [
                dict(item)
                for item in self.kanban_task_links
                if item["local_type"] == local_type and item["local_id"] == local_id
            ]

    def kanban_links_for_parent(self, parent_local_id: str) -> list[dict]:
        with self._lock:
            return [
                dict(item)
                for item in self.kanban_task_links
                if item.get("parent_local_id") == parent_local_id
            ]
