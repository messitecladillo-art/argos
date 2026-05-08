from __future__ import annotations

import logging

from ..models.store import RuntimeStore
from .kanban import extract_task_id, kanban_service, task_status
from .kanban_dispatch import dispatch_worker
from .kanban_workspace import workspace_for_agent


logger = logging.getLogger("hermes.agent_state")


CONCISE_REPLY_RULES = (
    "默认回答风格：先给结论，保持简洁；非必要不展开背景。\n"
    "普通答复控制在 8 行以内，优先使用 3-5 条要点；能一句话说清就只说一句。\n"
    "除非用户明确要求详细说明、步骤或完整代码，否则不要长篇解释。\n"
)


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
        "你是团队 Leader。这个任务由 Hermes Kanban 调度执行。\n"
        f"你的 agent_id 是：{leader_id}\n"
        f"调用 mcp_agent_bus_create_kanban_worker_tasks 时，from_agent_id 必须精确填写 `{leader_id}`，不要填写 leader、名称或其他别名。\n"
        "执行规则：\n"
        "0. 只要要面向用户输出最终答复，必须先调用 kanban_complete(summary=...) 标记当前 Kanban 任务完成；不要只输出自然语言就结束。\n"
        "1. 先调用 mcp_agent_bus_list_workers() 获取当前可用 worker。\n"
        "2. 需要 worker 协作时，调用 mcp_agent_bus_create_kanban_worker_tasks 创建 Kanban 子任务。\n"
        "3. from_agent_id 必须填写你自己的 agent_id。\n"
        "4. 创建 worker 子任务后不要把任务当作最终完成；平台会在 worker Kanban 任务完成后创建 leader 汇总任务。\n"
        "5. 收到汇总任务时，只基于任务正文里的 worker 结果输出最终总结，不要重复派发同一批任务。\n"
        "6. 只有任务不需要 worker 时，才直接调用 kanban_complete 完成当前 Kanban 任务，然后再给用户最终答复。\n"
        f"{CONCISE_REPLY_RULES}"
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
        f"{CONCISE_REPLY_RULES}"
        "Worker 返回给 Leader 时只输出：结论、关键依据、是否完成/阻塞。\n"
        f"{content}"
    )


def send_user_task(store: RuntimeStore, *, content: str) -> dict:
    content = (content or "").strip()
    if not content:
        raise ValueError("content is required")
    leader_id = find_leader_agent_id(store)
    user_task = store.create_user_task(leader_agent_id=leader_id, content=content)
    leader = store.find_agent(leader_id) or {}
    body = _format_user_task(content, leader_id)
    task_title = f"用户任务：{content[:80]}"
    kanban_task = kanban_service.create_task(
        task_title,
        body=(
            f"local_user_task_id: {user_task['user_task_id']}\n"
            f"leader_agent_id: {leader_id}\n\n"
            f"{body}"
        ),
        assignee=None,
        workspace=workspace_for_agent(leader),
        idempotency_key=f"user_task:{user_task['user_task_id']}",
    )
    kanban_task_id = extract_task_id(kanban_task)
    store.upsert_kanban_task_link(
        local_type="user_task",
        local_id=user_task["user_task_id"],
        kanban_task_id=kanban_task_id,
        kanban_role="parent",
        kanban_status="pending_dispatch",
        assignee_profile=leader["profile_name"],
        metadata={"task_title": task_title, "pending_dispatch": True},
    )
    store.push_event(
        "kanban.task.created",
        leader_id,
        user_task["user_task_id"],
        {
            "text": f"已创建 Kanban 父任务 {kanban_task_id}",
            "kanban_task_id": kanban_task_id,
            "assignee": leader["profile_name"],
        },
    )
    logger.warning(
        "[agent-message] send_user_task_kanban leader=%s user_task=%s kanban_task=%s content_len=%s",
        leader_id,
        user_task["user_task_id"],
        kanban_task_id,
        len(content),
    )
    dispatch_worker.trigger_async()
    return {
        "message_id": None,
        "content": content,
        "to_agent_id": leader_id,
        "user_task_id": user_task["user_task_id"],
        "kanban_task_id": kanban_task_id,
    }


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
    return {**message, "prompt_content": final_content} if not dispatch else message
