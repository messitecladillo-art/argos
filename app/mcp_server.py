"""MCP server exposing the agent registry over Streamable HTTP.

Mounted into the Flask app at /mcp; lets a leader agent (running inside a
hermes CLI subprocess) call `list_agents` to discover available workers.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from mcp.server.fastmcp import FastMCP

from .config import KANBAN_DEFAULT_WORKSPACE
from .models.store import store
from .services.kanban import extract_task_id, kanban_service, task_status

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
        item = dict(agent)
        item["mcps"] = mcp_installer.mcp_summary(agent["profile_name"])
        workers.append(item)
    return workers


@mcp.tool()
def send_to_worker(to_agent_id: str, content: str, from_agent_id: str) -> dict:
    """leader 把子任务派给指定 worker agent。

    ⚠️ 这是团队内通信专用工具，不同于 hermes-acp 内置的 `delegate_task`
    （后者是在本进程内生成子代理，与团队路由无关）。团队协作**必须**用这个。

    立即返回"已投递"；如果这是用户任务中的 worker 派发，平台会等待同一用户
    任务下所有 worker 完成后，再自动请求 leader 做一次最终汇总。

    参数：
    - to_agent_id: 目标 worker 的 agent_id（先调 list_workers 获取）
    - content: 任务正文
    - from_agent_id: 本 leader 自己的 agent_id，用于结果回推
    """
    result = create_kanban_worker_tasks(
        assignments=[{"to_agent_id": to_agent_id, "content": content}],
        from_agent_id=from_agent_id,
        summary_instruction="请基于 worker 的执行结果，面向用户输出最终总结。",
    )
    assignment = result["assignments"][0]
    return {
        "ok": True,
        "message_id": assignment.get("message_id"),
        "kanban_task_id": assignment.get("kanban_task_id"),
        "delegation_id": result["delegation_id"],
        "assignment_id": assignment["assignment_id"],
        "status": "waiting_workers",
        "to_agent_id": to_agent_id,
        "to_name": assignment["to_name"],
        "note": "已创建 Kanban worker 子任务；gateway 会执行，平台会在全部完成后创建 leader 汇总任务。",
    }


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
    if not parent_task_id and resolved_user_task_id:
        parent_link = store.find_kanban_task_link(
            local_type="user_task",
            local_id=resolved_user_task_id,
            kanban_role="parent",
        )
        if parent_link:
            parent_task_id = parent_link["kanban_task_id"]
    logger.warning(
        "[agent-mcp] create_kanban_worker_tasks from=%s user_task=%s parent=%s assignments=%s",
        sender_agent_id,
        resolved_user_task_id,
        parent_task_id,
        len(assignments),
    )
    for assignment in assignments:
        worker_id = (assignment.get("to_agent_id") or "").strip()
        if not worker_id:
            raise ValueError("assignment.to_agent_id is required")
        worker = store.find_agent(worker_id)
        if worker is None:
            raise ValueError(f"target agent not found: {worker_id}")
        if (worker.get("readiness_status") or "ready") != "ready":
            raise ValueError(f"target agent is not ready: {worker_id}")
    delegation = store.create_delegation(
        leader_agent_id=sender_agent_id,
        assignments=assignments,
        summary_instruction=summary_instruction,
        user_task_id=resolved_user_task_id,
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
            workspace=KANBAN_DEFAULT_WORKSPACE,
            priority=_assignment_priority(assignments, assignment),
            idempotency_key=f"assignment:{assignment['assignment_id']}",
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
            metadata={"delegation_id": delegation["delegation_id"], "task_title": task_title},
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
    return {
        "ok": True,
        "delegation_id": delegation["delegation_id"],
        "status": "waiting_workers",
        "from_agent_id": sender_agent_id,
        "user_task_id": resolved_user_task_id,
        "parent_task_id": parent_task_id,
        "dispatched_count": len(dispatched),
        "pending_count": len(dispatched),
        "assignments": dispatched,
        "note": "已创建 Kanban worker 子任务；gateway 会执行，平台会在全部完成后创建 leader 汇总任务。",
    }


def _resolve_user_task_id(leader_agent_id: str, user_task_id: str) -> str | None:
    if user_task_id:
        return user_task_id.strip()
    snapshot = store.snapshot()
    active = [
        item
        for item in snapshot["user_tasks"]
        if item.get("leader_agent_id") == leader_agent_id
        and item.get("status") in {"running", "waiting_workers"}
    ]
    if not active:
        return None
    active.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return active[0]["user_task_id"]


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
        "请直接执行以下 worker 子任务。完成时用 Kanban 任务结果说明结论、关键依据、是否完成/阻塞。\n\n"
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
