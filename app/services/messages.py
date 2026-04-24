from __future__ import annotations

from ..models.store import RuntimeStore
from . import chat


def send_message(store: RuntimeStore, *, content: str, to_agent_id: str) -> dict:
    content = (content or "").strip()
    if not content:
        raise ValueError("content is required")
    if not to_agent_id:
        raise ValueError("to_agent_id is required")
    message = store.record_message(content, to_agent_id)
    chat.dispatch_async(store, to_agent_id, content)
    return message
