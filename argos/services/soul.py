from __future__ import annotations

import subprocess
import threading

from ..config import HERMES_HOME
from ..models.store import RuntimeStore
from .profiles import ProfileError


ROLE_HINTS = {
    "leader": "团队的协调者（Orchestrator），负责目标理解、任务拆解、路由分发和结果合成；不亲自执行具体任务。",
    "worker": "团队的执行专家（Specialist），只负责自己专业领域内的任务，任务完成后把结果回传给 Leader。",
}

LEADER_TOOL_HINT = (
    "## 工具使用（必须写入 SOUL.md 的 Behavioral Guidelines 或专门一节）\n"
    "- 团队工具来自 MCP server `agent_bus`，调用名带 `mcp_agent_bus_` 前缀。\n"
    "- 先用 `mcp_agent_bus_list_workers()` 获取 worker 的 agent_id / name / description。\n"
    "- 给 worker 的子任务只能用 `mcp_agent_bus_create_kanban_worker_tasks(assignments, from_agent_id, parent_task_id, user_task_id, summary_instruction)`；assignments 含 to_agent_id / content，可选 title / priority。\n"
    "- 禁用 `delegate_task`、内置 `kanban_create` / `kanban_comment` / `kanban_assign`、`send_message` / messaging；它们不是团队 Kanban 路由。\n"
    "- Leader 只负责理解、拆解、选择 worker、创建 Kanban 子任务、在 review/checkpoint 判断完成/继续/阻塞，不编造 worker 输出。\n"
    "- 创建 worker 子任务后立即 `kanban_complete(summary=...)` 关闭当前父任务；review 继续派发时必须传 `user_task_id` 和当前 review task 的 `parent_task_id`，不重复同轮任务并遵守 max_rounds。\n"
)


CONCISE_STYLE_HINT = (
    "## 默认回答风格（必须写入 SOUL.md 的 Behavioral Guidelines）\n"
    "- 先结论、少背景、不重复问题；普通答复 8 行内，优先 3-5 要点。\n"
    "- 能一句话说清就只说一句；除非用户要求详细/步骤/完整代码，否则不长篇输出。\n"
    "- Worker 返回 Leader 时只输出结论、关键依据、是否完成/阻塞。\n"
)


def _soul_prompt(name: str, role: str, description: str) -> str:
    role_hint = ROLE_HINTS.get(role, "")
    extra = LEADER_TOOL_HINT if role == "leader" else ""
    return (
        "你是一名多代理 AI 系统的架构师。请根据用户提供的信息，为一个 Hermes Profile 生成"
        " SOUL.md 文件内容。SOUL.md 定义该 Agent 的身份、职责、行为准则和说话风格。\n\n"
        "## 硬性要求\n"
        "- 只输出 markdown 正文，不要包裹代码块、不要任何解释或开场白。\n"
        "- 结构必须包含以下章节：`# SOUL: <Name>`、`## Identity`、`## Core Purpose`、"
        "`## Behavioral Guidelines`（含沟通风格 / 决策风格）、`## Constraints`、`## Success Metrics`。\n"
        "- 语气差异化：leader 结构化果断；worker 精确、专注。\n"
        "- 不要编造用户没说的项目细节，缺信息就写通用原则。\n\n"
        f"{extra}"
        f"{CONCISE_STYLE_HINT}"
        f"## Agent 信息\n- Name: {name}\n- Role: {role} — {role_hint}\n- Description: {description or '（未提供）'}\n"
    )


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def generate_soul_md(name: str, role: str, description: str) -> str:
    """Call `hermes chat` to generate a SOUL.md body. Raises ProfileError on failure."""
    prompt = _soul_prompt(name, role, description)
    try:
        result = subprocess.run(
            ["hermes", "chat", "-Q", "-q", prompt],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ProfileError(f"hermes chat failed: {exc}") from exc
    if result.returncode != 0:
        raise ProfileError((result.stderr or result.stdout or "hermes chat failed").strip())
    text = _strip_code_fence(result.stdout or "")
    if not text.startswith("#"):
        raise ProfileError("generated SOUL.md did not start with a markdown heading")
    return text + "\n"


def fallback_soul_md(name: str, role: str, description: str) -> str:
    return (
        f"# SOUL: {name}\n\n"
        f"## Identity\nYou are {name}, a {role} in a Hermes multi-agent team.\n\n"
        f"## Core Purpose\n{description or 'Describe this agent’s mission here.'}\n\n"
        "## Behavioral Guidelines\n- Stay within your role boundary.\n"
        "- Communicate clearly and concisely.\n"
        "- Start with the conclusion and avoid unnecessary background.\n"
        "- Keep normal replies within 8 lines and prefer 3-5 concise bullets.\n"
        "- Do not write long explanations unless explicitly requested.\n"
        "- When replying to a Leader, include only conclusion, key evidence, and completion/blocker status.\n\n"
        "## Constraints\n- Do not fabricate information.\n\n"
        "## Success Metrics\n- Outputs fit the role and the task requirement.\n"
    )


def generate_and_publish(
    store: RuntimeStore,
    *,
    agent_id: str,
    name: str,
    role: str,
    description: str,
    profile_name: str,
) -> None:
    """Run SOUL.md generation and file write, publishing SSE events for each stage."""
    soul_path = HERMES_HOME / "profiles" / profile_name / "SOUL.md"
    try:
        text = generate_soul_md(name, role, description)
        source = "llm"
    except ProfileError as exc:
        store.push_event(
            "agent.soul.failed",
            agent_id,
            None,
            {"text": f"SOUL.md 生成失败，写入模板兜底：{exc}"},
        )
        text = fallback_soul_md(name, role, description)
        source = "fallback"
    try:
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        store.update_agent(
            agent_id,
            readiness_status="failed",
            readiness_message="SOUL.md 写入失败",
            runtime_status="stopped",
            current_task="SOUL.md 写入失败",
        )
        store.push_event(
            "agent.soul.failed",
            agent_id,
            None,
            {"text": f"SOUL.md 写入失败：{exc}"},
        )
        return
    store.update_agent(
        agent_id,
        readiness_status="ready",
        readiness_message=f"SOUL.md 已生成（{source}）",
        current_task="空闲",
    )
    store.push_event(
        "agent.soul.ready",
        agent_id,
        None,
        {"text": f"SOUL.md 已生成（{source}）→ {soul_path}"},
    )
    from . import acp

    agent = store.find_agent(agent_id)
    if agent is not None:
        acp.pool.start(agent)


def spawn_generate(
    store: RuntimeStore,
    *,
    agent_id: str,
    name: str,
    role: str,
    description: str,
    profile_name: str,
) -> None:
    """Fire-and-forget wrapper that runs generate_and_publish in a daemon thread."""
    threading.Thread(
        target=generate_and_publish,
        kwargs={
            "store": store,
            "agent_id": agent_id,
            "name": name,
            "role": role,
            "description": description,
            "profile_name": profile_name,
        },
        daemon=True,
    ).start()
