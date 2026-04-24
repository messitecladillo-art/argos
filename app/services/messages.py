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


def _format_user_task(content: str) -> str:
    return (
        "[USER_TASK]\n"
        "你是团队 Leader。所有用户任务必须由你先理解、拆解和调度。\n"
        "执行规则：\n"
        "1. 先调用 mcp_agent_bus_list_workers() 获取当前可用 worker。\n"
        "2. 如果任务需要执行、开发、分析、写作、测试等具体工作，不要自己完成，必须调用 "
        "mcp_agent_bus_send_to_worker(to_agent_id, content, from_agent_id) 派给合适 worker。\n"
        "3. from_agent_id 必须填写你自己的 agent_id。\n"
        "4. worker 回复会以 `[来自 <worker_name> 的回复]: ...` 回到你这里；收到后再做汇总并面向用户输出。\n"
        "5. 只有任务不需要 worker 时，才可以直接回复用户。\n"
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
        prompt_content=_format_user_task(content),
    )


def send_message(
    store: RuntimeStore,
    *,
    content: str,
    to_agent_id: str,
    from_agent_id: str | None = None,
    prompt_content: str | None = None,
) -> dict:
    content = (content or "").strip()
    if not content:
        raise ValueError("content is required")
    if not to_agent_id:
        raise ValueError("to_agent_id is required")
    if not pool.is_running(to_agent_id):
        raise ValueError("target agent session is not running")
    message = store.record_message(content, to_agent_id, from_agent_id=from_agent_id)
    final_content = prompt_content or _format_team_message(store, content, to_agent_id, from_agent_id)
    pool.prompt(to_agent_id, final_content, reply_to_leader=from_agent_id)
    return message
