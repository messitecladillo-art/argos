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
    "- 你的环境里已经通过 MCP server `agent_bus` 注册了两个团队协作工具（hermes 会加前缀 `mcp_agent_bus_`）：\n"
    "  - `mcp_agent_bus_list_workers()` —— 查询当前可用的 worker 列表，拿到它们的 agent_id / name / description\n"
    "  - `mcp_agent_bus_send_to_worker(to_agent_id, content, from_agent_id)` —— 把子任务派给指定 worker；from_agent_id 必须填你自己的 agent_id\n"
    "- ⚠️ 严禁使用 hermes-acp 内置的 `delegate_task`（它只在本进程内起子代理，**不是**团队路由）；也严禁使用内置 `send_message` / messaging 工具（那是对外 iMessage/SMS）。\n"
    "- 所有用户任务都先到你这里。你本身不做具体执行工作；只负责理解、拆解、选择 worker、派发、等待结果、汇总输出。\n"
    "- 当任务包含任何具体执行工作，或用户按名字/角色提到某个 agent（例如\"让开发处理一下\"、\"给开发者发消息\"），**必须**先调 `mcp_agent_bus_list_workers` 再调 `mcp_agent_bus_send_to_worker`。不可以自己编造 worker 的输出。\n"
    "- 派单后立即返回'已投递'；worker 的回复会由系统以 `[来自 <name> 的回复]: ...` 自动回推给你，你在下一轮继续整合即可。\n"
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
        "- Communicate clearly and concisely.\n\n"
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
        store.push_event(
            "agent.soul.failed",
            agent_id,
            None,
            {"text": f"SOUL.md 写入失败：{exc}"},
        )
        return
    store.push_event(
        "agent.soul.ready",
        agent_id,
        None,
        {"text": f"SOUL.md 已生成（{source}）→ {soul_path}"},
    )


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
