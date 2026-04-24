from __future__ import annotations

from ..models.store import RuntimeStore
from .acp import pool


def find_leader_agent_id(runtime_store: RuntimeStore) -> str:
    leader = next(
        (agent for agent in runtime_store.snapshot()["agents"] if agent.get("role") == "leader"),
        None,
    )
    if leader is None:
        raise ValueError("leader agent not found")
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
        "5. 收到 `[SYSTEM_DELEGATION_SUMMARY_REQUEST]` 时，只基于给定 worker 结果总结，不要重复派发同一批任务。\n"
        "6. 只有任务不需要 worker 时，才可以直接回复用户。\n"
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
    return send_message(
        store,
        content=content,
        to_agent_id=leader_id,
        prompt_content=_format_user_task(content, leader_id),
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
    summarize_delegation_id: str | None = None,
) -> dict:
    content = (content or "").strip()
    if not content:
        raise ValueError("content is required")
    if not to_agent_id:
        raise ValueError("to_agent_id is required")
    if not pool.is_running(to_agent_id):
        raise ValueError("target agent session is not running")
    message = store.record_message(
        content,
        to_agent_id,
        from_agent_id=from_agent_id,
        delegation_id=delegation_id,
        assignment_id=assignment_id,
    )
    final_content = prompt_content or _format_team_message(store, content, to_agent_id, from_agent_id)
    pool.prompt(
        to_agent_id,
        final_content,
        reply_to_leader=from_agent_id,
        delegation_id=delegation_id,
        assignment_id=assignment_id,
        summarize_delegation_id=summarize_delegation_id,
    )
    return message
