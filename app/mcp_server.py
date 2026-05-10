"""MCP server exposing the agent registry over Streamable HTTP.

Mounted into the Flask app at /mcp; lets a leader agent (running inside a
hermes CLI subprocess) call `list_agents` to discover available workers.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading

from mcp.server.fastmcp import FastMCP

from .models.store import store
from .services.kanban import extract_task_id, kanban_service, task_status
from .services.kanban_dispatch import dispatch_worker
from .services.kanban_workspace import workspace_for_agent

mcp = FastMCP("hermes-agents", streamable_http_path="/")
logger = logging.getLogger("hermes.agent_state")


def _resolve_sender_agent_id(from_agent_id: str) -> str:
    """Accept common leader aliases and return the registered agent_id."""
    value = (from_agent_id or "").strip()
    snapshot = store.snapshot()
    if any(agent.get("agent_id") == value for agent in snapshot["agents"]):
        return value
    normalized = value.lower()
    leader = next((a for a in snapshot["agents"] if a.get("role") == "leader"), None)
    if leader and normalized in {
        "leader",
        str(leader.get("name") or "").lower(),
        str(leader.get("profile_name") or "").lower(),
    }:
        return leader["agent_id"]
    raise ValueError(f"from_agent_id not found: {from_agent_id}")


@mcp.tool()
def list_workers() -> list[dict]:
    """列出当前注册的所有 worker agent（供 leader 进行任务分派时发现下属）。

    返回的字段包含 agent_id / name / description / status / current_task / load，
    不包含 leader 自身，避免 leader 把任务派给自己。
    """
    from .services import mcp_installer

    workers = []
    for agent in store.snapshot()["agents"]:
        if agent.get("role") != "worker":
            continue
        if (agent.get("readiness_status") or "ready") != "ready":
            continue
        item = {
            key: agent.get(key)
            for key in (
                "agent_id",
                "profile_name",
                "name",
                "role",
                "description",
                "status",
                "current_task",
                "load",
                "readiness_status",
                "readiness_message",
                "queue_depth",
            )
        }
        item["mcps"] = mcp_installer.mcp_summary(agent["profile_name"])
        workers.append(item)
    return workers


@mcp.tool()
def dispatch_parallel(
    assignments: list[dict],
    from_agent_id: str,
    summary_instruction: str = "",
) -> dict:
    """兼容入口：leader 一次性创建一批 Kanban worker 子任务。

    任务执行完全由 Hermes Kanban/gateway 负责，本工具不会 prompt ACP session。

    参数：
    - assignments: 子任务数组，每项包含 to_agent_id / content
    - from_agent_id: 本 leader 自己的 agent_id
    - summary_instruction: 所有 worker 返回后 leader 应如何汇总
    """
    return create_kanban_worker_tasks(
        assignments=assignments,
        from_agent_id=from_agent_id,
        summary_instruction=summary_instruction,
    )


@mcp.tool()
def create_kanban_worker_tasks(
    assignments: list[dict],
    from_agent_id: str,
    parent_task_id: str = "",
    user_task_id: str = "",
    summary_instruction: str = "",
) -> dict:
    """leader 创建一批 Hermes Kanban worker 子任务。"""
    if not assignments:
        raise ValueError("assignments is required")
    sender_agent_id = _resolve_sender_agent_id(from_agent_id)
    sender = store.find_agent(sender_agent_id)
    if sender is None or sender.get("role") != "leader":
        raise ValueError("from_agent_id must be a leader agent")
    resolved_user_task_id = _resolve_user_task_id(sender_agent_id, user_task_id)
    parent_task_id = (parent_task_id or "").strip()
    user_task = store.find_user_task(resolved_user_task_id) if resolved_user_task_id else None
    current_round = int((user_task or {}).get("current_round") or 1)
    max_rounds = int((user_task or {}).get("max_rounds") or 5)
    continuation = bool(user_task and (user_task.get("status") in {"ready_to_review", "reviewing"}))
    target_round = current_round + 1 if continuation else current_round
    if user_task and target_round > max_rounds:
        raise ValueError("max rounds reached for this user task")
    if not parent_task_id and resolved_user_task_id:
        parent_link = store.find_kanban_task_link(
            local_type="user_task",
            local_id=resolved_user_task_id,
            kanban_role="parent",
        )
        if parent_link:
            parent_task_id = parent_link["kanban_task_id"]
    logger.warning(
        "[agent-mcp] create_kanban_worker_tasks from=%s user_task=%s parent=%s round=%s assignments=%s",
        sender_agent_id,
        resolved_user_task_id,
        parent_task_id,
        target_round,
        len(assignments),
    )
    existing_dispatch = _existing_worker_dispatch(resolved_user_task_id, parent_task_id, target_round)
    if existing_dispatch:
        return {
            "ok": True,
            "idempotent": True,
            "delegation_id": existing_dispatch["delegation_id"],
            "status": "waiting_workers",
            "from_agent_id": sender_agent_id,
            "user_task_id": resolved_user_task_id,
            "parent_task_id": parent_task_id,
            "round": target_round,
            "max_rounds": max_rounds,
            "continuation": continuation,
            "dispatched_count": len(existing_dispatch["assignments"]),
            "pending_count": len(existing_dispatch["assignments"]),
            "parent_completed": False,
            "assignments": existing_dispatch["assignments"],
            "note": "同一用户任务已存在 Kanban worker 子任务；已返回现有派发结果，避免重复创建。",
        }
    for assignment in assignments:
        worker_id = (assignment.get("to_agent_id") or "").strip()
        if not worker_id:
            raise ValueError("assignment.to_agent_id is required")
        worker = store.find_agent(worker_id)
        if worker is None:
            raise ValueError(f"target agent not found: {worker_id}")
        if (worker.get("readiness_status") or "ready") != "ready":
            raise ValueError(f"target agent is not ready: {worker_id}")
    if resolved_user_task_id and continuation:
        store.advance_user_task_round(resolved_user_task_id)
    delegation = store.create_delegation(
        leader_agent_id=sender_agent_id,
        assignments=assignments,
        summary_instruction=summary_instruction,
        user_task_id=resolved_user_task_id,
        round_number=target_round,
    )
    dispatched = []
    for assignment in delegation["assignments"]:
        worker = store.find_agent(assignment["worker_agent_id"]) or {}
        task_title = _assignment_title(assignments, assignment)
        kanban_task = kanban_service.create_task(
            task_title,
            body=_format_worker_kanban_body(
                assignment=assignment,
                delegation=delegation,
                user_task_id=resolved_user_task_id,
                leader_agent_id=sender_agent_id,
            ),
            assignee=worker["profile_name"],
            parent=parent_task_id or None,
            workspace=workspace_for_agent(worker),
            priority=_assignment_priority(assignments, assignment),
            idempotency_key=_worker_idempotency_key(
                user_task_id=resolved_user_task_id,
                parent_task_id=parent_task_id,
                assignment=assignment,
                round_number=target_round,
            ),
        )
        kanban_task_id = extract_task_id(kanban_task)
        store.upsert_kanban_task_link(
            local_type="assignment",
            local_id=assignment["assignment_id"],
            kanban_task_id=kanban_task_id,
            kanban_role="worker",
            kanban_status=task_status(kanban_task) or "ready",
            assignee_profile=worker["profile_name"],
            parent_local_id=resolved_user_task_id or delegation["delegation_id"],
            metadata={
                "delegation_id": delegation["delegation_id"],
                "task_title": task_title,
                "parent_task_id": parent_task_id,
                "user_task_id": resolved_user_task_id,
                "round": target_round,
                "kind": "worker",
                "continuation": continuation,
            },
        )
        store.attach_assignment_message(
            delegation["delegation_id"],
            assignment["assignment_id"],
            kanban_task_id,
        )
        dispatched.append(
            {
                "assignment_id": assignment["assignment_id"],
                "message_id": None,
                "kanban_task_id": kanban_task_id,
                "to_agent_id": assignment["worker_agent_id"],
                "to_name": assignment["worker_name"],
                "assignee_profile": worker["profile_name"],
            }
        )
    if resolved_user_task_id:
        store.close_user_task_dispatch(resolved_user_task_id)
    parent_completed = _complete_parent_dispatch_task(
        parent_task_id=parent_task_id,
        user_task_id=resolved_user_task_id,
        delegation_id=delegation["delegation_id"],
        dispatched=dispatched,
        round_number=target_round,
        continuation=continuation,
    )
    dispatch_worker.trigger_async()
    return {
        "ok": True,
        "idempotent": False,
        "delegation_id": delegation["delegation_id"],
        "status": "waiting_workers",
        "from_agent_id": sender_agent_id,
        "user_task_id": resolved_user_task_id,
        "parent_task_id": parent_task_id,
        "round": target_round,
        "max_rounds": max_rounds,
        "continuation": continuation,
        "dispatched_count": len(dispatched),
        "pending_count": len(dispatched),
        "parent_completed": parent_completed,
        "assignments": dispatched,
        "note": "已创建 Kanban worker 子任务；gateway 会执行，平台会在全部完成后创建 leader review 任务。",
    }


def _resolve_user_task_id(leader_agent_id: str, user_task_id: str) -> str | None:
    if user_task_id:
        return user_task_id.strip()
    snapshot = store.snapshot()
    active = [
        item
        for item in snapshot["user_tasks"]
        if item.get("leader_agent_id") == leader_agent_id
        and item.get("status") in {"running", "waiting_workers", "ready_to_review", "reviewing"}
    ]
    if not active:
        return None
    active.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return active[0]["user_task_id"]


def _existing_worker_dispatch(
    user_task_id: str | None,
    parent_task_id: str,
    round_number: int | None,
) -> dict | None:
    if not user_task_id and not parent_task_id:
        return None
    links = [
        link
        for link in store.snapshot().get("kanban_task_links", [])
        if link.get("kanban_role") == "worker"
        and (link.get("kanban_status") or "").lower() != "archived"
        and (round_number is None or int((link.get("metadata") or {}).get("round") or 1) == round_number)
        and (
            (user_task_id and link.get("parent_local_id") == user_task_id)
            or (parent_task_id and (link.get("metadata") or {}).get("parent_task_id") == parent_task_id)
        )
    ]
    if not links:
        return None
    assignments = []
    delegation_ids = []
    snapshot = store.snapshot()
    for link in links:
        metadata = link.get("metadata") or {}
        delegation_id = metadata.get("delegation_id") or ""
        if delegation_id and delegation_id not in delegation_ids:
            delegation_ids.append(delegation_id)
        assignment = _find_assignment(snapshot, delegation_id, link.get("local_id") or "")
        assignments.append(
            {
                "assignment_id": link.get("local_id"),
                "message_id": None,
                "kanban_task_id": link.get("kanban_task_id"),
                "to_agent_id": (assignment or {}).get("worker_agent_id"),
                "to_name": (assignment or {}).get("worker_name") or link.get("assignee_profile"),
                "assignee_profile": link.get("assignee_profile"),
            }
        )
    return {
        "delegation_id": delegation_ids[0] if len(delegation_ids) == 1 else ",".join(delegation_ids),
        "assignments": assignments,
    }


def _find_assignment(snapshot: dict, delegation_id: str, assignment_id: str) -> dict | None:
    if not delegation_id or not assignment_id:
        return None
    for delegation in snapshot.get("delegations", []):
        if delegation.get("delegation_id") != delegation_id:
            continue
        for assignment in delegation.get("assignments") or []:
            if assignment.get("assignment_id") == assignment_id:
                return assignment
    return None


def _worker_idempotency_key(
    *,
    user_task_id: str | None,
    parent_task_id: str,
    assignment: dict,
    round_number: int | None = None,
) -> str:
    content_hash = hashlib.sha1((assignment.get("content") or "").encode("utf-8")).hexdigest()[:12]
    if user_task_id:
        return f"user-task-worker:{user_task_id}:round:{round_number or 1}:{assignment['worker_agent_id']}:{content_hash}"
    if parent_task_id:
        return f"parent-worker:{parent_task_id}:{assignment['worker_agent_id']}:{content_hash}"
    return f"assignment:{assignment['assignment_id']}"


def _complete_parent_dispatch_task(
    *,
    parent_task_id: str,
    user_task_id: str | None,
    delegation_id: str,
    dispatched: list[dict],
    round_number: int,
    continuation: bool,
) -> bool:
    if not parent_task_id:
        return False
    if continuation:
        summary = f"第 {round_number - 1} 轮 review 已完成，已创建第 {round_number} 轮 {len(dispatched)} 个 worker 子任务。"
    else:
        summary = f"已创建第 {round_number} 轮 {len(dispatched)} 个 worker Kanban 子任务，等待全部完成后平台会创建 leader review 任务。"
    metadata = {
        "dispatch_phase_completed": True,
        "user_task_id": user_task_id,
        "delegation_id": delegation_id,
        "round": round_number,
        "continuation": continuation,
        "dispatched_count": len(dispatched),
        "assignments": [
            {
                "assignment_id": item.get("assignment_id"),
                "agent_id": item.get("to_agent_id"),
                "kanban_task_id": item.get("kanban_task_id"),
            }
            for item in dispatched
        ],
    }
    try:
        kanban_service.complete_task(
            parent_task_id,
            result=summary,
            summary=summary,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[agent-mcp] parent dispatch complete failed task=%s error=%s", parent_task_id, exc)
        store.push_event(
            "kanban.parent.complete.failed",
            "",
            parent_task_id,
            {"text": f"父 Kanban 任务调度阶段完成兜底失败：{exc}"},
        )
        return False
    parent_link = store.find_kanban_task_link(kanban_task_id=parent_task_id)
    if parent_link is not None:
        metadata_patch = dict(parent_link.get("metadata") or {})
        metadata_patch.update(
            {
                "dispatch_phase_completed": True,
                "delegation_id": delegation_id,
                "round": round_number,
                "continuation": continuation,
                "worker_task_ids": [item.get("kanban_task_id") for item in dispatched],
            }
        )
        store.update_kanban_task_link(
            parent_task_id,
            kanban_status="done",
            last_result=summary,
            last_summary=summary,
            metadata=metadata_patch,
        )
    store.push_event(
        "kanban.parent.dispatch.completed",
        "",
        parent_task_id,
        {"text": summary, "metadata": metadata},
    )
    return True


def _assignment_title(raw_assignments: list[dict], assignment: dict) -> str:
    raw = _matching_raw_assignment(raw_assignments, assignment)
    title = (raw.get("title") or "").strip()
    if title:
        return title
    content = assignment.get("content") or ""
    return f"Worker 子任务：{content[:80]}"


def _assignment_priority(raw_assignments: list[dict], assignment: dict) -> int | None:
    raw = _matching_raw_assignment(raw_assignments, assignment)
    value = raw.get("priority")
    return int(value) if value is not None else None


def _matching_raw_assignment(raw_assignments: list[dict], assignment: dict) -> dict:
    for raw in raw_assignments:
        if (raw.get("to_agent_id") or "").strip() == assignment["worker_agent_id"] and (
            raw.get("content") or ""
        ).strip() == assignment["content"]:
            return raw
    return {}


def _format_worker_kanban_body(
    *,
    assignment: dict,
    delegation: dict,
    user_task_id: str | None,
    leader_agent_id: str,
) -> str:
    return (
        "[KANBAN_WORKER_TASK]\n"
        f"delegation_id: {delegation['delegation_id']}\n"
        f"assignment_id: {assignment['assignment_id']}\n"
        f"user_task_id: {user_task_id or ''}\n"
        f"leader_agent_id: {leader_agent_id}\n\n"
        "请直接执行以下 worker 子任务。完成时必须先调用 kanban_complete(summary=...)，用 Kanban 任务结果说明结论、关键依据、是否完成/阻塞；不要只输出自然语言就结束。\n\n"
        "子任务内容：\n"
        f"{assignment['content']}"
    )


mcp_asgi_app = mcp.streamable_http_app()

# a2wsgi does not dispatch ASGI lifespan events, so FastMCP's session manager
# would never start. Run it in a dedicated background thread with its own loop.
_started = threading.Event()


def _run_session_manager() -> None:
    async def runner() -> None:
        async with mcp.session_manager.run():
            _started.set()
            await asyncio.Event().wait()

    asyncio.run(runner())


def start_session_manager() -> None:
    if _started.is_set():
        return
    threading.Thread(target=_run_session_manager, daemon=True).start()
    _started.wait(timeout=5)
