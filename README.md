# Hermes Agents Team

基于 [Hermes Agent](https://hermes-agent.nousresearch.com/) profile 机制构建的多 Agent 协作 Web 系统。每个 Agent 是一个独立的 Hermes profile，拥有独立的人设、技能、记忆与工具，通过 Web 中枢、MCP、ACP 与 Hermes Kanban 完成任务拆解、分派、执行、审查与汇总。

> 1. 本项目是社区实验项目，不是 Nous Research 或 Hermes Agent 官方项目。
> 2. 当前仅建议在本机或可信内网环境运行，不要在未加鉴权、访问控制和 HTTPS 保护的情况下直接暴露到公网。
> 3. 所有 Agent profile、MCP、Skill、数据库与运行时配置均仅保存在本机环境中，项目不会将这些数据上传到云端，可放心在本地配置和使用。
> 4. 系统实际能力取决于本机 Hermes Agent 所配置和调用的模型。

- **后端**：Flask + Starlette/Uvicorn (ASGI)
- **通信协议**：MCP（Agent → 中枢）+ ACP（中枢 → Agent）+ Hermes Kanban
- **存储**：SQLite
- **前端**：原生 HTML/JS，实时展示多 Agent 对话、终端输出与任务流转

更多设计细节见 [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md) 和 [doc/design.md](doc/design.md)。

## 功能

- Leader / Specialist 两层 Agent 角色，自动任务拆解、执行、审查与汇总
- Web UI 实时观察多 Agent 对话、终端输出、工具调用与子任务流转
- Hermes Kanban 看板任务、自动派发、状态同步与任务归档
- Agent 初始化、批量启动 / 停止 / 重启
- 模型配置管理，可为不同 Agent 应用不同模型配置
- 团队导入 / 导出，支持迁移 Agent profile、skills 与可选 workspace
- MCP Server 安装管理，支持 `http` / `streamable_http` / `stdio`
- Skill 安装管理，支持从 frontmatter 解析元信息
- SOUL.md 人设编辑

## 目录结构

```
app/             Flask 应用（controllers / services / models / db / static / templates）
  asgi.py        ASGI 入口，挂载 Flask + MCP Server
  mcp_server.py  暴露给 Agent 的 MCP 工具
  config.py      环境变量与路径配置
data/            SQLite 数据库（运行时生成，已 gitignore）
doc/             架构 / 设计 / 管理文档
tests/           pytest 测试
run.py           本地开发启动入口
```

## 快速开始

### 1. 环境要求

- 操作系统：Linux / macOS（依赖 `pexpect`，**不支持原生 Windows**；Windows 用户请使用 WSL2）
- Python 3.10+
- 已安装并配置好的 [Hermes Agent](https://hermes-agent.nousresearch.com/docs/getting-started)
- Hermes Agent v0.12.0 及以上版本，Hermes CLI 需要支持 `profile`、`acp`、`kanban` 等子命令

### 2. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 配置环境变量（可选）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HERMES_HOME` | `~/.hermes` | Hermes profiles 根目录 |
| `AGENT_TEAM_WORKSPACE_ROOT` | `~/agent_team` | Agent 工作区根目录 |
| `DATABASE_URL` | `sqlite:///data/hermes_agent_team.db` | 数据库连接串 |
| `HERMES_AGENTS_MCP_URL` | `http://127.0.0.1:5050/mcp/` | MCP Bus 地址 |
| `PORT` | `5050` | HTTP 服务端口 |
| `FLASK_DEBUG` | `0` | 调试日志开关（不启用自动 reload） |
| `AUTO_START_AGENTS` | `1` | 项目启动时自动启动所有已就绪 Agent；设为 `0` 可关闭 |
| `KANBAN_BOARD` | `hermes-agents-team` | Hermes Kanban board 名称 |
| `KANBAN_POLL_INTERVAL` | `2` | Kanban 状态同步轮询间隔（秒） |
| `KANBAN_DEFAULT_WORKSPACE` | `scratch` | Kanban 任务默认 workspace |
| `KANBAN_AUTO_DISPATCH` | `0` | 首次无持久化设置时，自动 Dispatch 开关的默认值 |

### 4. 配置调整

需要关闭 Hermes Agent 的 `config.yaml` 中的 `dispatch_in_gateway`：

```yaml
kanban:
  dispatch_in_gateway: false
```

### 5. 启动

```bash
python run.py
```

访问 [http://127.0.0.1:5050](http://127.0.0.1:5050)。

### 6. 运行测试

```bash
pytest
```

## 文档

- [架构设计](doc/ARCHITECTURE.md)
- [详细设计](doc/design.md)
- [MCP 管理](doc/mcp-management.md)
- [Skill 管理](doc/skills-management.md)

## 维护说明

本项目作为开源项目发布，希望能为有需要的人提供参考和帮助。

由于个人时间和精力有限，本项目将以尽力而为的方式维护。我可能无法及时回复 Issue、审核 Pull Request，或提供持续的技术支持。

欢迎你根据自己的需要 Fork 本项目，并在此基础上自由修改和扩展。

## 作者

- 林克（Liu Wenbin）

## 示例

### 不同角色的描述

- **Leader Agent**：

```text
负责理解用户目标，拆解项目任务，选择合适的 worker 执行，并跟踪各环节结果。
```

- **产品 Agent**：

```text
负责把用户想法整理成清晰需求，定义功能范围、用户流程、优先级和验收标准。
```

- **开发 Agent**：

```text
负责根据需求完成技术方案、代码实现、接口设计等，不要做测试。
```

- **测试 Agent**：

```text
负责根据需求和实现设计测试用例，验证功能是否正确，并记录缺陷和风险。
```

- **设计 Agent**：

```text
负责页面结构、交互流程、视觉风格、组件规范和用户体验优化。
```

- **运维 Agent**：

```text
负责运行环境、部署流程、配置管理、日志排查、监控告警和上线风险控制。
```

### 任务提示词

发给 Leader Agent：

```text
请大家做一个自我介绍
```

```text
请组织团队分阶段协作，完成一个“待办清单”Web 项目。
目标：做成完整可用、适合快速演示的小功能，包含前端页面、后端接口和简单数据存储。页面风格是商务科技风格，风格要炫。使用未被占用的端口。
请严格分阶段执行：先只派产品 Agent 完成简短 PRD，并由 Leader review 通过后，才能派开发 Agent 实现前后端和存储；开发完成后再派测试 Agent 验证，测试 Agent 验证前必须先写测试用例文档再验证，再写测试报告。
完成标准：
1. 要有产品的 PRD 文档，开发的设计文档，开发的项目代码，测试的测试用例，和测试的测试报告。缺一不可，否则被定义为未完成
2. 务必在后台启动服务、确认可访问，并告诉我访问地址。
```

## 许可证

MIT

## 安全

安全注意事项见 [SECURITY.md](SECURITY.md)。

MCP headers/env 等敏感字段会在界面展示和导出时做脱敏处理；运行所需的真实凭据仍保存在本机 Hermes profile 配置中，请不要提交或公开这些本地配置文件。
