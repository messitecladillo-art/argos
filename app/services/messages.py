from __future__ import annotations

import logging

from ..models.store import RuntimeStore
from .acp import pool


logger = logging.getLogger("hermes.agent_state")


def find_leader_agent_id(runtime_store: RuntimeStore) -> str:
    leader = next(
        (
            agent
            for agent in runtime_store.snapshot()["agents"]
            if agent.get("role") == "leader"
            and (agent.get("readiness_status") or "ready") == "ready"
        ),
        None,
    )
    if leader is None:
        raise ValueError("ready leader agent not found")
    return leader["agent_id"]


def _format_user_task(content: str, leader_id: str) -> str:
    return (
        "[USER_TASK]\n"
        "你是团队 Leader。所有用户任务必须由你先理解、拆解和调度。\n"
        f"你的 agent_id 是：{leader_id}\n"
        f"调用 mcp_agent_bus_send_to_worker 或 mcp_agent_bus_dispatch_parallel 时，from_agent_id 必须精确填写 `{leader_id}`，不要填写 leader、名称或其他别名。\n"
        "执行规则：\n"
        "1. 先调用 mcp_agent_bus_list_workers() 获取当前可用 worker。\n"
        "2. 如果任务需要多个 worker 并行协作，优先调用 "
        "mcp_agent_bus_dispatch_parallel(assignments, from_agent_id, summary_instruction) 一次性派发。\n"
        "3. 如果只需要一个 worker，才调用 "
        "mcp_agent_bus_send_to_worker(to_agent_id, content, from_agent_id) 派给合适 worker。\n"
        "3. from_agent_id 必须填写你自己的 agent_id。\n"
        "4. 并行派发后，平台会等待同一批 worker 全部完成，再把汇总请求发回给你。\n"
        "5. 如果你在同一个用户任务里分多次调用 worker，平台会把这些 worker 结果合并，等全部完成后再发汇总请求。\n"
        "6. 派发 worker 后不要把任务当作最终完成；收到 `[SYSTEM_USER_TASK_SUMMARY_REQUEST]` 或 `[SYSTEM_DELEGATION_SUMMARY_REQUEST]` 时，只基于给定 worker 结果总结，不要重复派发同一批任务。\n"
        "7. 只有任务不需要 worker 时，才可以直接回复用户。\n"
        "用户原始任务：\n"
        f"{content}"
    )


def _format_team_message(
    runtime_store: RuntimeStore,
    content: str,
    to_agent_id: str,
    from_agent_id: str | None,
) -> str:
    if not from_agent_id:
        return content
    sender = runtime_store.find_agent(from_agent_id) or {}
    target = runtime_store.find_agent(to_agent_id) or {}
    sender_name = sender.get("name") or from_agent_id
    target_name = target.get("name") or to_agent_id
    return (
        "[TEAM_MESSAGE]\n"
        f"From {sender_name}\n"
        f"To {target_name}\n"
        "请把以下内容视为团队内部任务或协作请求，并直接执行：\n"
        f"{content}"
    )


def send_user_task(store: RuntimeStore, *, content: str) -> dict:
    content = (content or "").strip()
    if not content:
        raise ValueError("content is required")
    leader_id = find_leader_agent_id(store)
    user_task = store.create_user_task(leader_agent_id=leader_id, content=content)
    logger.warning(
        "[agent-message] send_user_task leader=%s user_task=%s content_len=%s",
        leader_id,
        user_task["user_task_id"],
        len(content),
    )
    return send_message(
        store,
        content=content,
        to_agent_id=leader_id,
        prompt_content=_format_user_task(content, leader_id),
        user_task_id=user_task["user_task_id"],
    )


def send_message(
    store: RuntimeStore,
    *,
    content: str,
    to_agent_id: str,
    from_agent_id: str | None = None,
    prompt_content: str | None = None,
    delegation_id: str | None = None,
    assignment_id: str | None = None,
    user_task_id: str | None = None,
    summarize_delegation_id: str | None = None,
    summarize_user_task_id: str | None = None,
    dispatch: bool = True,
) -> dict:
    content = (content or "").strip()
    if not content:
        raise ValueError("content is required")
    if not to_agent_id:
        raise ValueError("to_agent_id is required")
    target = store.find_agent(to_agent_id)
    if target is None:
        raise ValueError("target agent not found")
    if (target.get("readiness_status") or "ready") != "ready":
        raise ValueError("target agent is not ready")
    if not pool.is_running(to_agent_id):
        raise ValueError("target agent session is not running")
    message = store.record_message(
        content,
        to_agent_id,
        from_agent_id=from_agent_id,
        delegation_id=delegation_id,
        assignment_id=assignment_id,
        user_task_id=user_task_id,
    )
    final_content = prompt_content or _format_team_message(store, content, to_agent_id, from_agent_id)
    logger.warning(
        "[agent-message] send_message to=%s from=%s message=%s delegation=%s assignment=%s user_task=%s prompt_len=%s dispatch=%s",
        to_agent_id,
        from_agent_id,
        message["message_id"],
        delegation_id,
        assignment_id,
        user_task_id,
        len(final_content),
        dispatch,
    )
    if not dispatch:
        return {**message, "prompt_content": final_content}
    pool.prompt(
        to_agent_id,
        final_content,
        reply_to_leader=from_agent_id,
        delegation_id=delegation_id,
        assignment_id=assignment_id,
        user_task_id=user_task_id,
        summarize_delegation_id=summarize_delegation_id,
        summarize_user_task_id=summarize_user_task_id,
    )
    return message
