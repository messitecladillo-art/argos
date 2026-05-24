# Hermes Agents Team

基于 [Hermes Agent](https://hermes-agent.nousresearch.com/) profile 机制构建的多 Agent 协作 Web 系统。每个 Agent 是一个独立的 Hermes profile，拥有独立的人设、技能、记忆与工具，通过 Web 中枢、MCP、ACP 与 Hermes Kanban 完成任务拆解、分派、执行、审查与汇总。

> 1. 本项目是社区实验项目，不是 Nous Research 或 Hermes Agent 官方项目。
> 2. 当前仅建议在本机或可信内网环境运行，不要在未加鉴权、访问控制和 HTTPS 保护的情况下直接暴露到公网。
> 3. 所有 Agent profile、MCP、Skill、数据库与运行时配置均仅保存在本机环境中，项目不会将这些数据上传到云端，可放心在本地配置和使用。
> 4. 系统实际能力取决于本机 Hermes Agent 所配置和调用的模型。

- **后端**：Flask + Starlette/Uvicorn (ASGI)，生产级安全中间件
- **通信协议**：MCP（Agent → 中枢）+ ACP（中枢 → Agent）+ Hermes Kanban
- **存储**：SQLite（Alembic 版本化迁移）
- **前端**：原生 HTML/JS，实时展示多 Agent 对话、终端输出与任务流转
- **部署**：Docker 多阶段构建，非 root 运行，内置健康检查

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
- SOUL.md 人设编辑与重新生成
- 生产级安全中间件：API Token 鉴权、CORS、滑动窗口速率限制
- 自进化学习系统：执行追踪、记忆库、主动学习引擎、A/B 评估
- 健康检查端点 `/api/argos/status`（DB 连接 / Hermes CLI / 环境变量）
- 管理 CLI：`argos-cli check|backup|info|migrate`（基于 rich 美化终端输出）
- 终端 UI 仪表盘：`argos-tui`（基于 Textual，实时展示 Agent 状态 / 事件 / Kanban）
- Docker 支持：多阶段构建、非 root 用户、内置健康检查
- 密钥管理：.env 加载 + Docker secrets + API Key 脱敏

## 目录结构

```
argos/           Argos 应用
  asgi.py        ASGI 入口，挂载 Flask + MCP Server + WebSocket
  cli.py         管理命令行工具（check / backup / info / migrate）
  config.py      环境变量与路径配置
  controllers/   HTTP 路由控制器
  db/            ORM 模型 + Alembic 迁移
  learning/      自进化学习引擎（追踪 / 记忆 / 反馈 / 主动学习 / A/B 评估）
  middleware/    安全中间件（鉴权 / CORS / 速率限制 / 错误处理）
  models/        运行时状态存储 + 持久化桥接
  services/      业务逻辑（Agent 管理 / 模型配置 / 密钥管理 / 技能安装）
  tui/           终端 UI 仪表盘（Textual，Agent 状态 / 事件 / Kanban）
data/            SQLite 数据库（运行时生成，已 gitignore）
doc/             架构 / 设计 / 管理文档
tests/           pytest 测试（168 项）
Dockerfile       多阶段生产镜像
docker-compose.yml 容器编排配置
manage.py        管理 CLI 入口
pyproject.toml   项目配置（构建 / pytest / mypy / ruff）
run.py           本地开发启动入口
run_tui.py       终端 UI 启动入口
```

## 快速开始

### 1. 环境要求

- 操作系统：Linux / macOS（依赖 `pexpect`，**不支持原生 Windows**；Windows 用户请使用 WSL2）
- Python 3.11+
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
| `DATABASE_URL` | `sqlite:///data/argos.db` | 数据库连接串 |
| `HERMES_AGENTS_MCP_URL` | `http://127.0.0.1:5050/mcp/` | MCP Bus 地址 |
| `PORT` | `5050` | HTTP 服务端口 |
| `FLASK_DEBUG` | `0` | 调试日志开关（不启用自动 reload） |
| `AUTO_START_AGENTS` | `1` | 项目启动时自动启动所有已就绪 Agent；设为 `0` 可关闭 |
| `KANBAN_BOARD` | `argos` | Hermes Kanban board 名称 |
| `KANBAN_POLL_INTERVAL` | `2` | Kanban 状态同步轮询间隔（秒） |
| `KANBAN_DEFAULT_WORKSPACE` | `scratch` | Kanban 任务默认 workspace |
| `KANBAN_AUTO_DISPATCH` | `0` | 首次无持久化设置时，自动 Dispatch 开关的默认值 |
| `SECRET_KEY` | (空) | 应用密钥，生产环境必填。未设置时生产模式会输出警告 |
| `API_TOKEN` | (空) | API 鉴权 Token。设置后除 `/`、`/static/*`、`/mcp/*`、健康检查外均需鉴权 |
| `CORS_ORIGINS` | (空) | 允许的跨域来源，逗号分隔。生产模式下未设置则拒绝所有跨域请求 |
| `RATE_LIMIT_MAX` | `100` | 每个 IP 在时间窗口内的最大请求数；设为 `0` 禁用限流 |
| `RATE_LIMIT_WINDOW` | `60` | 速率限制时间窗口（秒） |
| `LOG_LEVEL` | `INFO` | 日志级别 (`DEBUG`/`INFO`/`WARNING`/`ERROR`) |
| `LOG_FORMAT` | `text` | 日志格式，设为 `json` 启用结构化日志 |
| `LOG_DIR` | (空) | 日志文件目录。不设置则输出到控制台 |
| `LEARN_ENABLED` | `1` | 是否启用在职学习引擎；设为 `0` 可关闭 |
| `LEARN_EMBED_PROVIDER` | (空) | 嵌入向量 provider，支持 `ollama`。不设置则用随机向量回退 |

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

### 6. Docker 部署

```bash
# 构建镜像
docker build -t argos .

# 使用 docker-compose
cp .env.example .env     # 编辑 .env 填入实际配置
docker-compose up -d
```

Docker 健康检查自动访问 `/api/argos/status`，`docker-compose ps` 可查看状态。

### 7. 管理 CLI

```bash
python manage.py check      # 检查 Hermes CLI 和数据库状态
python manage.py backup     # 备份 SQLite 数据库
python manage.py info       # 显示当前配置信息
python manage.py migrate    # 数据库升级到最新版本
```

所有 CLI 命令均使用 `rich` 美化终端输出（表格 / 面板 / 图标 / 彩色状态）。

### 8. 终端 UI 仪表盘

```bash
python run_tui.py           # 启动终端仪表盘
# 或通过 console script：
argos-tui
```

基于 `textual` 构建，实时展示 Agent 运行状态、事件日志、Kanban 任务流转。支持键盘快捷键操作。

### 9. 运行测试

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
