from __future__ import annotations

import hashlib

from .kanban import extract_task_id, kanban_service, task_status
from .kanban_dispatch import dispatch_worker
from .kanban_workspace import workspace_for_agent


def create_human_input_task(
    runtime_store,
    *,
    question: str,
    context: str = "",
    options: list[str] | None = None,
    from_agent_id: str,
    parent_task_id: str = "",
    user_task_id: str = "",
) -> dict:
    question = (question or "").strip()
    if not question:
        raise ValueError("question is required")
    requester = runtime_store.find_agent((from_agent_id or "").strip())
    if requester is None:
        raise ValueError("from_agent_id not found")
    normalized_options = [str(item).strip() for item in options or [] if str(item).strip()]
    title = f"人工处理：{question[:80]}"
    task = kanban_service.create_task(
        title,
        body=_format_human_input_body(
            question=question,
            context=context,
            options=normalized_options,
            requester=requester,
            parent_task_id=parent_task_id,
            user_task_id=user_task_id,
        ),
        assignee=None,
        parent=parent_task_id or None,
        workspace="scratch",
        idempotency_key=_human_input_idempotency_key(
            from_agent_id=requester["agent_id"],
            parent_task_id=parent_task_id,
            user_task_id=user_task_id,
            question=question,
        ),
    )
    human_task_id = extract_task_id(task)
    link = runtime_store.upsert_kanban_task_link(
        local_type="human_input",
        local_id=human_task_id,
        kanban_task_id=human_task_id,
        kanban_role="human_input",
        kanban_status="waiting_human",
        assignee_profile="",
        parent_local_id=user_task_id or parent_task_id or None,
        metadata={
            "kind": "human_input",
            "task_title": title,
            "question": question,
            "context": context or "",
            "options": normalized_options,
            "requester_agent_id": requester["agent_id"],
            "requester_profile": requester.get("profile_name") or "",
            "parent_task_id": parent_task_id or "",
            "user_task_id": user_task_id or "",
        },
    )
    runtime_store.push_event(
        "human_input.requested",
        requester["agent_id"],
        human_task_id,
        {
            "text": f"Agent 请求人工处理：{question}",
            "kanban_task_id": human_task_id,
            "user_task_id": user_task_id or "",
        },
    )
    return {
        "ok": True,
        "status": "waiting_human",
        "human_task_id": human_task_id,
        "link": link,
        "note": "已创建人工处理看板任务；请等待用户在 Web UI 中回答。",
    }


def answer_human_input_task(
    runtime_store,
    *,
    human_task_id: str,
    answer: str,
) -> dict:
    human_task_id = (human_task_id or "").strip()
    answer = (answer or "").strip()
    if not human_task_id:
        raise ValueError("human_task_id is required")
    if not answer:
        raise ValueError("answer is required")
    link = runtime_store.find_kanban_task_link(kanban_task_id=human_task_id)
    if link is None or link.get("kanban_role") != "human_input":
        raise ValueError("human input task not found")
    metadata = dict(link.get("metadata") or {})
    requester = runtime_store.find_agent(metadata.get("requester_agent_id") or "")
    if requester is None:
        raise ValueError("requester agent not found")
    continuation = kanban_service.create_task(
        f"继续执行：{metadata.get('question') or human_task_id}"[:100],
        body=_format_continuation_body(metadata=metadata, answer=answer, human_task_id=human_task_id),
        assignee=requester.get("profile_name") or None,
        parent=human_task_id,
        workspace=workspace_for_agent(requester),
        idempotency_key=f"human-input-answer:{human_task_id}",
    )
    continuation_task_id = extract_task_id(continuation)
    runtime_store.upsert_kanban_task_link(
        local_type="human_input",
        local_id=f"{human_task_id}:continuation",
        kanban_task_id=continuation_task_id,
        kanban_role="human_continuation",
        kanban_status=task_status(continuation) or "ready",
        assignee_profile=requester.get("profile_name") or "",
        parent_local_id=metadata.get("user_task_id") or metadata.get("parent_task_id") or None,
        metadata={
            "kind": "human_continuation",
            "task_title": f"继续执行：{metadata.get('question') or human_task_id}"[:100],
            "human_task_id": human_task_id,
            "answer": answer,
            "question": metadata.get("question") or "",
            "requester_agent_id": requester["agent_id"],
            "assignee_agent_id": requester["agent_id"],
            "user_task_id": metadata.get("user_task_id") or "",
            "parent_task_id": metadata.get("parent_task_id") or "",
        },
    )
    kanban_service.complete_task(
        human_task_id,
        result=answer,
        summary=f"人工已回答：{answer}",
        metadata={"human_answered": True},
    )
    runtime_store.update_kanban_task_link(
        human_task_id,
        kanban_status="done",
        last_result=answer,
        last_summary=f"人工已回答：{answer}",
        metadata={**metadata, "answer": answer, "answered": True, "continuation_task_id": continuation_task_id},
    )
    runtime_store.push_event(
        "human_input.answered",
        requester["agent_id"],
        human_task_id,
        {
            "text": "人工处理已完成，已创建 continuation 任务",
            "kanban_task_id": human_task_id,
            "continuation_task_id": continuation_task_id,
        },
    )
    dispatch_worker.trigger_async()
    return {
        "ok": True,
        "human_task_id": human_task_id,
        "continuation_task_id": continuation_task_id,
    }


def _format_human_input_body(
    *,
    question: str,
    context: str,
    options: list[str],
    requester: dict,
    parent_task_id: str,
    user_task_id: str,
) -> str:
    option_text = "\n".join(f"- {item}" for item in options) if options else "无固定选项，请直接回答。"
    return (
        "[HUMAN_INPUT_TASK]\n"
        f"requester_agent_id: {requester.get('agent_id') or ''}\n"
        f"requester_profile: {requester.get('profile_name') or ''}\n"
        f"user_task_id: {user_task_id or ''}\n"
        f"parent_task_id: {parent_task_id or ''}\n\n"
        "请用户处理以下问题。回答后平台会把答案交回给请求的 Agent 继续执行。\n\n"
        "问题：\n"
        f"{question}\n\n"
        "上下文：\n"
        f"{context or '(无)'}\n\n"
        "可选项：\n"
        f"{option_text}"
    )


def _format_continuation_body(*, metadata: dict, answer: str, human_task_id: str) -> str:
    return (
        "[HUMAN_INPUT_CONTINUATION]\n"
        f"human_task_id: {human_task_id}\n"
        f"user_task_id: {metadata.get('user_task_id') or ''}\n"
        f"parent_task_id: {metadata.get('parent_task_id') or ''}\n\n"
        "用户已经回答了你之前请求人工处理的问题，请基于答案继续执行原任务。\n"
        "结束前必须调用 kanban_complete(summary=...) 或 kanban_block(...）。\n\n"
        "你提出的问题：\n"
        f"{metadata.get('question') or ''}\n\n"
        "当时上下文：\n"
        f"{metadata.get('context') or '(无)'}\n\n"
        "用户回答：\n"
        f"{answer}"
    )


def _human_input_idempotency_key(*, from_agent_id: str, parent_task_id: str, user_task_id: str, question: str) -> str:
    base = parent_task_id or user_task_id or from_agent_id
    digest = hashlib.sha1(
        f"{from_agent_id}\n{parent_task_id}\n{user_task_id}\n{question}".encode("utf-8")
    ).hexdigest()[:12]
    return f"human-input:{base}:{digest}"
