from __future__ import annotations

from ..models.store import RuntimeStore
from . import chat
from .acp import pool


def send_message(
    store: RuntimeStore,
    *,
    content: str,
    to_agent_id: str,
    from_agent_id: str | None = None,
) -> dict:
    content = (content or "").strip()
    if not content:
        raise ValueError("content is required")
    if not to_agent_id:
        raise ValueError("to_agent_id is required")
    message = store.record_message(content, to_agent_id, from_agent_id=from_agent_id)
    if pool.is_running(to_agent_id):
        pool.prompt(to_agent_id, content, reply_to_leader=from_agent_id)
    else:
        # Fallback: one-shot `hermes chat -q` if ACP is not running.
        chat.dispatch_async(store, to_agent_id, content)
    return message
