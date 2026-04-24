from __future__ import annotations

import subprocess
import threading

from ..models.store import RuntimeStore


def _run_hermes_chat(profile_name: str, content: str) -> str:
    try:
        result = subprocess.run(
            ["hermes", "-p", profile_name, "chat", "-Q", "--ignore-rules", "-q", content],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("hermes CLI not found in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("hermes chat timed out") from exc
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "hermes chat failed").strip())
    return (result.stdout or "").strip()


def _dispatch(store: RuntimeStore, agent_id: str, content: str) -> None:
    agent = store.find_agent(agent_id)
    if agent is None:
        return
    profile_name = agent["profile_name"]

    store.update_agent(agent_id, status="busy", current_task="处理消息中")

    try:
        reply = _run_hermes_chat(profile_name, content)
    except RuntimeError as exc:
        store.update_agent(agent_id, status="idle", current_task="空闲")
        store.push_event(
            "agent.output.failed",
            agent_id,
            None,
            {"text": f"调用 hermes chat 失败：{exc}"},
        )
        return

    preview = (reply[:180] + "…") if len(reply) > 180 else (reply or "—")
    store.update_agent(
        agent_id,
        status="idle",
        current_task="空闲",
        last_output=preview,
    )
    store.push_event(
        "agent.output.final",
        agent_id,
        None,
        {"text": reply or "(空响应)"},
    )


def dispatch_async(store: RuntimeStore, agent_id: str, content: str) -> None:
    threading.Thread(
        target=_dispatch,
        args=(store, agent_id, content),
        daemon=True,
    ).start()
