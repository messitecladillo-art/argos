from __future__ import annotations

import json
from collections import deque
from itertools import count
from typing import Any

from sqlalchemy import select

from .models import (
    AgentRecord,
    AssignmentRecord,
    DelegationRecord,
    EventRecord,
    KanbanTaskLinkRecord,
    MessageRecord,
    UserTaskRecord,
)
from .session import Base, SessionLocal, engine


def init_database() -> None:
    Base.metadata.create_all(bind=engine)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _next_counter(values: list[str], prefix: str) -> count:
    maximum = 0
    for value in values:
        if not value.startswith(prefix):
            continue
        try:
            maximum = max(maximum, int(value.removeprefix(prefix)))
        except ValueError:
            continue
    return count(maximum + 1)


class SQLitePersistence:
    """Synchronous persistence adapter for the in-memory RuntimeStore."""

    def upsert_agent(self, agent: dict) -> None:
        with SessionLocal.begin() as session:
            record = session.scalar(
                select(AgentRecord).where(AgentRecord.agent_id == agent["agent_id"])
            )
            if record is None:
                record = AgentRecord(agent_id=agent["agent_id"], profile_name=agent["profile_name"])
                session.add(record)
            record.profile_name = agent.get("profile_name") or record.profile_name
            record.name = agent.get("name") or ""
            record.role = agent.get("role") or "worker"
            record.description = agent.get("description") or ""
            record.is_leader = bool(agent.get("is_leader"))
            record.workspace_path = agent.get("workspace_path") or ""
            record.status = agent.get("status") or "idle"
            record.current_task = agent.get("current_task") or "空闲"
            record.runtime_status = agent.get("runtime_status") or "stopped"
            record.interaction_state = agent.get("interaction_state") or "idle"
            record.orchestration_state = agent.get("orchestration_state") or "none"
            record.queue_depth = int(agent.get("queue_depth") or 0)
            record.pending_interaction_json = _json_dumps(agent.get("pending_interaction"))
            record.load = int(agent.get("load") or 0)
            record.last_input = agent.get("last_input") or ""
            record.last_output = agent.get("last_output") or ""
            record.last_output_at = agent.get("last_output_at") or ""
            record.readiness_status = agent.get("readiness_status") or "ready"
            record.readiness_message = agent.get("readiness_message") or ""
            record.created_at = agent.get("created_at")
            record.updated_at = agent.get("updated_at")
            record.deleted_at = agent.get("deleted_at")
            record.last_active_at = agent.get("last_active_at") or ""

    def soft_delete_agent(self, agent_id: str, deleted_at: str) -> None:
        with SessionLocal.begin() as session:
            record = session.scalar(select(AgentRecord).where(AgentRecord.agent_id == agent_id))
            if record is not None:
                record.deleted_at = deleted_at
                record.runtime_status = "stopped"
                record.status = "offline"

    def upsert_user_task(self, task: dict) -> None:
        with SessionLocal.begin() as session:
            record = session.scalar(
                select(UserTaskRecord).where(UserTaskRecord.user_task_id == task["user_task_id"])
            )
            if record is None:
                record = UserTaskRecord(user_task_id=task["user_task_id"])
                session.add(record)
            record.leader_agent_id = task["leader_agent_id"]
            record.content = task.get("content") or ""
            record.delegation_ids_json = _json_dumps(task.get("delegation_ids") or [])
            record.status = task.get("status") or "running"
            record.dispatch_closed = bool(task.get("dispatch_closed"))
            record.summary_requested_at = task.get("summary_requested_at")
            record.completed_at = task.get("completed_at")
            record.created_at = task.get("created_at")
            record.updated_at = task.get("updated_at")
            record.deleted_at = task.get("deleted_at")

    def upsert_delegation(self, delegation: dict) -> None:
        with SessionLocal.begin() as session:
            record = session.scalar(
                select(DelegationRecord).where(
                    DelegationRecord.delegation_id == delegation["delegation_id"]
                )
            )
            if record is None:
                record = DelegationRecord(delegation_id=delegation["delegation_id"])
                session.add(record)
            record.user_task_id = delegation.get("user_task_id")
            record.leader_agent_id = delegation["leader_agent_id"]
            record.summary_instruction = delegation.get("summary_instruction") or ""
            record.status = delegation.get("status") or "waiting_workers"
            record.completed_at = delegation.get("completed_at")
            record.summarized_at = delegation.get("summarized_at")
            record.created_at = delegation.get("created_at")
            record.updated_at = delegation.get("updated_at")
            record.deleted_at = delegation.get("deleted_at")
            for assignment in delegation.get("assignments") or []:
                self._upsert_assignment_record(session, delegation["delegation_id"], assignment)

    def upsert_assignment(self, delegation_id: str, assignment: dict) -> None:
        with SessionLocal.begin() as session:
            self._upsert_assignment_record(session, delegation_id, assignment)

    def _upsert_assignment_record(self, session, delegation_id: str, assignment: dict) -> None:
        record = session.scalar(
            select(AssignmentRecord).where(
                AssignmentRecord.delegation_id == delegation_id,
                AssignmentRecord.assignment_id == assignment["assignment_id"],
            )
        )
        if record is None:
            record = AssignmentRecord(
                delegation_id=delegation_id,
                assignment_id=assignment["assignment_id"],
            )
            session.add(record)
        record.worker_agent_id = assignment["worker_agent_id"]
        record.worker_name = assignment.get("worker_name") or ""
        record.content = assignment.get("content") or ""
        record.message_id = assignment.get("message_id")
        record.status = assignment.get("status") or "pending"
        record.result = assignment.get("result")
        record.completed_at = assignment.get("completed_at")
        record.created_at = assignment.get("created_at")
        record.updated_at = assignment.get("updated_at")
        record.deleted_at = assignment.get("deleted_at")

    def insert_message(self, message: dict) -> None:
        with SessionLocal.begin() as session:
            existing = session.scalar(
                select(MessageRecord).where(MessageRecord.message_id == message["message_id"])
            )
            if existing is not None:
                return
            session.add(
                MessageRecord(
                    message_id=message["message_id"],
                    from_agent_id=message.get("from_agent_id"),
                    from_name=message.get("from_name") or "",
                    to_agent_id=message.get("to_agent_id") or "",
                    to_name=message.get("to_name") or "",
                    content=message.get("content") or "",
                    delegation_id=message.get("delegation_id"),
                    assignment_id=message.get("assignment_id"),
                    user_task_id=message.get("user_task_id"),
                    created_at=message.get("created_at") or "",
                )
            )

    def insert_event(self, event: dict) -> None:
        with SessionLocal.begin() as session:
            existing = session.scalar(
                select(EventRecord).where(EventRecord.event_id == event["id"])
            )
            if existing is not None:
                return
            session.add(
                EventRecord(
                    event_id=event["id"],
                    event_type=event.get("event_type") or "",
                    agent_id=event.get("agent_id") or "",
                    task_id=event.get("task_id"),
                    data_json=_json_dumps(event.get("data") or {}),
                    created_at=event.get("timestamp") or "",
                )
            )

    def upsert_kanban_task_link(self, link: dict) -> None:
        with SessionLocal.begin() as session:
            record = session.scalar(
                select(KanbanTaskLinkRecord).where(
                    KanbanTaskLinkRecord.local_type == link["local_type"],
                    KanbanTaskLinkRecord.local_id == link["local_id"],
                    KanbanTaskLinkRecord.kanban_role == link["kanban_role"],
                )
            )
            if record is None:
                record = session.scalar(
                    select(KanbanTaskLinkRecord).where(
                        KanbanTaskLinkRecord.kanban_task_id == link["kanban_task_id"]
                    )
                )
            if record is None:
                record = KanbanTaskLinkRecord(
                    local_type=link["local_type"],
                    local_id=link["local_id"],
                    kanban_role=link["kanban_role"],
                    kanban_task_id=link["kanban_task_id"],
                )
                session.add(record)
            record.local_type = link["local_type"]
            record.local_id = link["local_id"]
            record.kanban_task_id = link["kanban_task_id"]
            record.kanban_role = link["kanban_role"]
            record.kanban_status = link.get("kanban_status") or ""
            record.assignee_profile = link.get("assignee_profile") or ""
            record.parent_local_id = link.get("parent_local_id")
            record.last_result = link.get("last_result") or ""
            record.last_summary = link.get("last_summary") or ""
            record.summary_created = bool(link.get("summary_created"))
            record.metadata_json = _json_dumps(link.get("metadata") or {})
            record.created_at = link.get("created_at")
            record.updated_at = link.get("updated_at")
            record.deleted_at = link.get("deleted_at")

    def load_runtime_state(self) -> dict:
        with SessionLocal() as session:
            agents = [
                self._agent_to_dict(record)
                for record in session.scalars(
                    select(AgentRecord)
                    .where(AgentRecord.deleted_at.is_(None))
                    .order_by(AgentRecord.id)
                )
            ]
            user_tasks = [
                self._task_to_dict(record)
                for record in session.scalars(select(UserTaskRecord).order_by(UserTaskRecord.id))
            ]
            assignments_by_delegation: dict[str, list[dict]] = {}
            for record in session.scalars(select(AssignmentRecord).order_by(AssignmentRecord.id)):
                assignments_by_delegation.setdefault(record.delegation_id, []).append(
                    self._assignment_to_dict(record)
                )
            delegations = [
                self._delegation_to_dict(record, assignments_by_delegation)
                for record in session.scalars(select(DelegationRecord).order_by(DelegationRecord.id))
            ]
            messages = [
                self._message_to_dict(record)
                for record in session.scalars(select(MessageRecord).order_by(MessageRecord.id.desc()).limit(200))
            ]
            events = [
                self._event_to_dict(record)
                for record in session.scalars(select(EventRecord).order_by(EventRecord.id.desc()).limit(400))
            ]
            kanban_task_links = [
                self._kanban_task_link_to_dict(record)
                for record in session.scalars(
                    select(KanbanTaskLinkRecord).order_by(KanbanTaskLinkRecord.id)
                )
            ]
        return {
            "agents": agents,
            "user_tasks": user_tasks,
            "delegations": delegations,
            "kanban_task_links": kanban_task_links,
            "messages": deque(messages, maxlen=200),
            "events": deque(events, maxlen=400),
            "event_ids": _next_counter([event["id"] for event in events], "evt_"),
            "message_ids": _next_counter([message["message_id"] for message in messages], "msg_"),
            "user_task_ids": _next_counter([task["user_task_id"] for task in user_tasks], "ut_"),
            "delegation_ids": _next_counter(
                [delegation["delegation_id"] for delegation in delegations],
                "dlg_",
            ),
            "assignment_ids": _next_counter(
                [
                    assignment["assignment_id"]
                    for delegation in delegations
                    for assignment in delegation.get("assignments", [])
                ],
                "asg_",
            ),
        }

    def _agent_to_dict(self, record: AgentRecord) -> dict:
        agent = {
            "agent_id": record.agent_id,
            "profile_name": record.profile_name,
            "name": record.name,
            "role": record.role,
            "description": record.description or "",
            "is_leader": bool(record.is_leader),
            "workspace_path": record.workspace_path or "",
            "status": "idle",
            "current_task": "空闲",
            "runtime_status": "stopped",
            "interaction_state": "idle",
            "orchestration_state": "none",
            "queue_depth": 0,
            "pending_interaction": None,
            "load": record.load or 0,
            "last_input": record.last_input or "",
            "last_output": record.last_output or "",
            "last_output_at": record.last_output_at or "",
            "readiness_status": record.readiness_status or "ready",
            "readiness_message": record.readiness_message or "",
            "created_at": record.created_at or "",
            "last_active_at": record.last_active_at or record.created_at or "",
        }
        return agent

    def _task_to_dict(self, record: UserTaskRecord) -> dict:
        status = record.status
        if status in {"running", "waiting_workers", "ready_to_summarize", "summarizing"}:
            status = "interrupted"
        return {
            "user_task_id": record.user_task_id,
            "leader_agent_id": record.leader_agent_id,
            "content": record.content,
            "delegation_ids": _json_loads(record.delegation_ids_json, []),
            "status": status,
            "dispatch_closed": bool(record.dispatch_closed),
            "summary_requested_at": record.summary_requested_at,
            "completed_at": record.completed_at,
            "created_at": record.created_at or "",
        }

    def _delegation_to_dict(
        self,
        record: DelegationRecord,
        assignments_by_delegation: dict[str, list[dict]],
    ) -> dict:
        status = record.status
        if status in {"waiting_workers", "ready_to_summarize", "summarizing"}:
            status = "interrupted"
        return {
            "delegation_id": record.delegation_id,
            "user_task_id": record.user_task_id,
            "leader_agent_id": record.leader_agent_id,
            "summary_instruction": record.summary_instruction or "",
            "assignments": assignments_by_delegation.get(record.delegation_id, []),
            "status": status,
            "created_at": record.created_at or "",
            "completed_at": record.completed_at,
            "summarized_at": record.summarized_at,
        }

    def _assignment_to_dict(self, record: AssignmentRecord) -> dict:
        status = record.status
        if status in {"pending", "running"}:
            status = "interrupted"
        return {
            "assignment_id": record.assignment_id,
            "worker_agent_id": record.worker_agent_id,
            "worker_name": record.worker_name,
            "content": record.content,
            "message_id": record.message_id,
            "status": status,
            "result": record.result,
            "completed_at": record.completed_at,
        }

    def _message_to_dict(self, record: MessageRecord) -> dict:
        return {
            "message_id": record.message_id,
            "from_agent_id": record.from_agent_id,
            "from_name": record.from_name,
            "to_agent_id": record.to_agent_id,
            "to_name": record.to_name,
            "content": record.content,
            "delegation_id": record.delegation_id,
            "assignment_id": record.assignment_id,
            "user_task_id": record.user_task_id,
            "created_at": record.created_at,
        }

    def _event_to_dict(self, record: EventRecord) -> dict:
        return {
            "id": record.event_id,
            "event_type": record.event_type,
            "agent_id": record.agent_id,
            "task_id": record.task_id,
            "timestamp": record.created_at,
            "data": _json_loads(record.data_json, {}),
        }

    def _kanban_task_link_to_dict(self, record: KanbanTaskLinkRecord) -> dict:
        return {
            "local_type": record.local_type,
            "local_id": record.local_id,
            "kanban_task_id": record.kanban_task_id,
            "kanban_role": record.kanban_role,
            "kanban_status": record.kanban_status or "",
            "assignee_profile": record.assignee_profile or "",
            "parent_local_id": record.parent_local_id,
            "last_result": record.last_result or "",
            "last_summary": record.last_summary or "",
            "summary_created": bool(record.summary_created),
            "metadata": _json_loads(record.metadata_json, {}),
            "created_at": record.created_at or "",
            "updated_at": record.updated_at,
        }
