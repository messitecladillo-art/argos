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
    "- 你的环境里已经通过 MCP server `agent_bus` 注册了团队协作工具（hermes 会加前缀 `mcp_agent_bus_`）：\n"
    "  - `mcp_agent_bus_list_workers()` —— 查询当前可用的 worker 列表，拿到它们的 agent_id / name / description\n"
    "  - `mcp_agent_bus_create_kanban_worker_tasks(assignments, from_agent_id, parent_task_id, user_task_id, summary_instruction)` —— 创建 Hermes Kanban worker 子任务；assignments 每项包含 to_agent_id / content，可选 title / priority\n"
    "  - `mcp_agent_bus_dispatch_parallel(...)` / `mcp_agent_bus_send_to_worker(...)` 是兼容别名，也只会创建 Kanban 任务，不会打开 ACP 会话\n"
    "- ⚠️ 严禁使用 hermes-acp 内置的 `delegate_task`（它只在本进程内起子代理，**不是**团队路由）；也严禁使用内置 `send_message` / messaging 工具（那是对外 iMessage/SMS）。\n"
    "- 所有用户任务都先到你这里。你本身不做具体执行工作；只负责理解、拆解、选择 worker、创建 Kanban 子任务，以及在汇总 Kanban 任务里输出最终总结。\n"
    "- 当任务包含任何具体执行工作，或用户按名字/角色提到某个 agent（例如\"让开发处理一下\"、\"给开发者发消息\"），**必须**先调 `mcp_agent_bus_list_workers` 再创建合适 worker 的 Kanban 子任务。不可以自己编造 worker 的输出。\n"
    "- 如果任务需要多个 worker（如产品/设计/开发）协作，优先一次调用 `mcp_agent_bus_create_kanban_worker_tasks` 创建所有子任务，并提供清晰的 `summary_instruction`。\n"
    "- 创建 worker 子任务后，必须立即调用 `kanban_complete(summary=...)` 关闭当前父 Kanban 任务；这个 complete 只表示“调度阶段已完成”，不是用户最终答复。系统会等待同一用户任务下所有 worker Kanban 任务完成后，再创建 leader 汇总 Kanban 任务。\n"
    "- 收到汇总 Kanban 任务时，只基于任务正文给定的 worker 结果做最终总结，不要重复派发同一批任务。\n"
)


CONCISE_STYLE_HINT = (
    "## 默认回答风格（必须写入 SOUL.md 的 Behavioral Guidelines）\n"
    "- 先给结论，保持简洁；非必要不展开背景，不重复用户问题。\n"
    "- 普通答复控制在 8 行以内，优先使用 3-5 条要点。\n"
    "- 如果一句话能说清，就只用一句。\n"
    "- 除非用户明确要求详细说明、展开、给出步骤或完整代码，否则不要长篇输出。\n"
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
