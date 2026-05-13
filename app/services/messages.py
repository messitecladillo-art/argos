from __future__ import annotations

import logging

from ..models.store import RuntimeStore
from .agent_status import agent_dispatch_block_reason, is_agent_dispatchable
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
            and is_agent_dispatchable(agent)
        ),
        None,
    )
    if leader is None:
        raise ValueError("ready leader agent not found")
    return leader["agent_id"]


def _find_ready_agent(runtime_store: RuntimeStore, agent_id: str) -> dict:
    agent_id = (agent_id or "").strip()
    if not agent_id:
        raise ValueError("to_agent_id is required")
    agent = runtime_store.find_agent(agent_id)
    if agent is None:
        raise ValueError("target agent not found")
    reason = agent_dispatch_block_reason(agent)
    if reason:
        raise ValueError(f"target agent is not dispatchable: {reason}")
    return agent


def _format_user_task(content: str, leader_id: str) -> str:
    return (
        "[USER_TASK]\n"
        "你是团队 Leader。这个任务由 Hermes Kanban 调度执行。\n"
        f"你的 agent_id 是：{leader_id}\n"
        f"调用 mcp_agent_bus_create_kanban_worker_tasks 时，from_agent_id 必须精确填写 `{leader_id}`，不要填写 leader、名称或其他别名。\n"
        "执行规则：\n"
        "0. 当前父 Kanban 任务必须以 kanban_complete(summary=...) 或 kanban_block(...) 结束；不要只输出自然语言就退出。\n"
        "1. 先调用 mcp_agent_bus_list_workers() 获取当前可用 worker。\n"
        "2. 需要 worker 协作时，只能调用 mcp_agent_bus_create_kanban_worker_tasks 创建平台可追踪的 worker Kanban 子任务。\n"
        "3. from_agent_id 必须填写你自己的 agent_id。\n"
        "4. 创建 worker 子任务后，必须立即调用 kanban_complete(summary=...) 关闭当前规划/复盘任务；这个 complete 只表示“本轮调度或复盘完成”，不是用户最终答复。\n"
        "5. 收到 review/checkpoint 任务时，请基于 worker 结果判断用户目标是否完成：已完成则 kanban_complete(summary=最终答复)；未完成且未达到最大轮次则继续创建下一轮 worker；无法继续则 kanban_block(reason=...) 或 kanban_complete(summary=阻塞说明)。\n"
        "6. 每次继续派发都必须带上 user_task_id 和当前 review task 的 parent_task_id；不要重复派发当前轮已完成的同一批任务，允许基于新发现创建下一轮任务。\n"
        "7. 只有任务不需要 worker 时，才直接调用 kanban_complete 完成当前 Kanban 任务，然后再给用户最终答复。\n"
        "8. 严禁使用内置 kanban_create / kanban_comment / kanban_assign 创建或模拟 worker 子任务；这些任务不会写入团队总线，也不会出现在 Web 团队看板里。\n"
        "9. 如果你已经用 kanban_create 创建了依赖任务，必须改为调用 mcp_agent_bus_create_kanban_worker_tasks；不要把内置 Kanban 任务当作 worker 派发结果。\n"
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


def _format_direct_worker_task(content: str, worker: dict) -> str:
    return (
        "[DIRECT_WORKER_TASK]\n"
        "这个任务由用户在 Web 看板中直接指派给你，请直接执行。\n"
        f"你的 agent_id 是：{worker.get('agent_id') or ''}\n"
        "执行规则：\n"
        "0. 当前 Kanban 任务必须以 kanban_complete(summary=...) 或 kanban_block(...) 结束；不要只输出自然语言就退出。\n"
        "1. 不要再把这个任务派回 Leader，除非任务明确要求团队协作。\n"
        f"{CONCISE_REPLY_RULES}"
        "用户原始任务：\n"
        f"{content}"
    )


def send_user_task(store: RuntimeStore, *, content: str, to_agent_id: str = "") -> dict:
    content = (content or "").strip()
    if not content:
        raise ValueError("content is required")
    target = _find_ready_agent(store, to_agent_id) if (to_agent_id or "").strip() else None
    leader_id = target["agent_id"] if target and target.get("role") == "leader" else find_leader_agent_id(store)
    if target and target.get("role") == "worker":
        return _send_direct_worker_task(store, content=content, leader_id=leader_id, worker=target)
    if target and target.get("role") != "leader":
        raise ValueError("target agent must be leader or worker")
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


def _send_direct_worker_task(store: RuntimeStore, *, content: str, leader_id: str, worker: dict) -> dict:
    user_task = store.create_user_task(leader_agent_id=leader_id, content=content)
    body = _format_direct_worker_task(content, worker)
    task_title = f"指派给 {worker.get('name') or worker['agent_id']}：{content[:60]}"
    kanban_task = kanban_service.create_task(
        task_title,
        body=(
            f"local_user_task_id: {user_task['user_task_id']}\n"
            f"direct_worker_agent_id: {worker['agent_id']}\n\n"
            f"{body}"
        ),
        assignee=worker["profile_name"],
        workspace=workspace_for_agent(worker),
        idempotency_key=f"direct_worker_task:{user_task['user_task_id']}:{worker['agent_id']}",
    )
    kanban_task_id = extract_task_id(kanban_task)
    store.upsert_kanban_task_link(
        local_type="user_task",
        local_id=user_task["user_task_id"],
        kanban_task_id=kanban_task_id,
        kanban_role="worker",
        kanban_status=task_status(kanban_task) or "ready",
        assignee_profile=worker["profile_name"],
        metadata={"task_title": task_title, "direct_worker": True, "assignee_agent_id": worker["agent_id"]},
    )
    store.push_event(
        "kanban.task.created",
        worker["agent_id"],
        user_task["user_task_id"],
        {
            "text": f"已创建 Worker 直派任务 {kanban_task_id}",
            "kanban_task_id": kanban_task_id,
            "assignee": worker["profile_name"],
        },
    )
    logger.warning(
        "[agent-message] send_direct_worker_task worker=%s user_task=%s kanban_task=%s content_len=%s",
        worker["agent_id"],
        user_task["user_task_id"],
        kanban_task_id,
        len(content),
    )
    dispatch_worker.trigger_async()
    return {
        "message_id": None,
        "content": content,
        "to_agent_id": worker["agent_id"],
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
    reason = agent_dispatch_block_reason(target)
    if reason:
        raise ValueError(f"target agent is not dispatchable: {reason}")
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
