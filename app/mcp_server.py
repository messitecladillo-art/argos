"""MCP server exposing the agent registry over Streamable HTTP.

Mounted into the Flask app at /mcp; lets a leader agent (running inside a
hermes CLI subprocess) call `list_agents` to discover available workers.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from mcp.server.fastmcp import FastMCP

from .models.store import store

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
    from .services.acp import pool
    from .services import mcp_installer, skill_installer

    workers = []
    for agent in store.snapshot()["agents"]:
        if agent.get("role") != "worker":
            continue
        if (agent.get("readiness_status") or "ready") != "ready":
            continue
        if not pool.is_running(agent.get("agent_id") or ""):
            continue
        item = dict(agent)
        item["skills"] = skill_installer.skill_summary(agent["profile_name"])
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
    result = dispatch_parallel(
        assignments=[{"to_agent_id": to_agent_id, "content": content}],
        from_agent_id=from_agent_id,
        summary_instruction="请基于 worker 的执行结果，面向用户输出最终总结。",
    )
    assignment = result["assignments"][0]
    return {
        "ok": True,
        "message_id": assignment["message_id"],
        "delegation_id": result["delegation_id"],
        "assignment_id": assignment["assignment_id"],
        "status": "waiting_workers",
        "to_agent_id": to_agent_id,
        "to_name": assignment["to_name"],
        "note": "任务已投递给 worker；系统会在同一用户任务的 worker 全部返回后自动请求 leader 汇总。",
    }


@mcp.tool()
def dispatch_parallel(
    assignments: list[dict],
    from_agent_id: str,
    summary_instruction: str = "",
) -> dict:
    """leader 一次性把同一批子任务派给多个 worker 并行执行。

    平台会创建 delegation 批次并收集所有 worker 结果；如果属于用户任务，
    系统会等待该用户任务下所有批次都完成后，再把一次性汇总请求发回 leader。
    leader 收到汇总请求后只做最终总结，不要重复派发同一批任务。

    参数：
    - assignments: 子任务数组，每项包含 to_agent_id / content
    - from_agent_id: 本 leader 自己的 agent_id
    - summary_instruction: 所有 worker 返回后 leader 应如何汇总
    """
    from .services.messages import send_message
    from .services.acp import pool

    if not assignments:
        raise ValueError("assignments is required")
    sender_agent_id = _resolve_sender_agent_id(from_agent_id)
    user_task_id = pool.current_user_task_id(sender_agent_id)
    logger.warning(
        "[agent-mcp] dispatch_parallel from=%s user_task=%s assignments=%s",
        sender_agent_id,
        user_task_id,
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
        if not pool.is_running(worker_id):
            raise ValueError(f"target agent session is not running: {worker_id}")
    delegation = store.create_delegation(
        leader_agent_id=sender_agent_id,
        assignments=assignments,
        summary_instruction=summary_instruction,
        user_task_id=user_task_id,
    )
    dispatched = []
    for assignment in delegation["assignments"]:
        message = send_message(
            store,
            content=assignment["content"],
            to_agent_id=assignment["worker_agent_id"],
            from_agent_id=sender_agent_id,
            delegation_id=delegation["delegation_id"],
            assignment_id=assignment["assignment_id"],
            user_task_id=user_task_id,
            dispatch=False,
        )
        store.attach_assignment_message(
            delegation["delegation_id"],
            assignment["assignment_id"],
            message["message_id"],
        )
        pool.prompt(
            assignment["worker_agent_id"],
            message["prompt_content"],
            reply_to_leader=sender_agent_id,
            delegation_id=delegation["delegation_id"],
            assignment_id=assignment["assignment_id"],
            user_task_id=user_task_id,
        )
        dispatched.append(
            {
                "assignment_id": assignment["assignment_id"],
                "message_id": message["message_id"],
                "to_agent_id": assignment["worker_agent_id"],
                "to_name": assignment["worker_name"],
            }
        )
    return {
        "ok": True,
        "delegation_id": delegation["delegation_id"],
        "status": "waiting_workers",
        "from_agent_id": sender_agent_id,
        "user_task_id": user_task_id,
        "dispatched_count": len(dispatched),
        "pending_count": len(dispatched),
        "assignments": dispatched,
        "note": "已并行投递；系统会在同批 worker 全部返回后自动请求 leader 汇总。",
    }


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
