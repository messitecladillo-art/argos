# Hermes Agents Team

基于 [Hermes Agent](https://hermes-agent.nousresearch.com/) profile 机制构建的多 Agent 协作 Web 系统。每个 Agent 是一个独立的 Hermes profile，拥有独立的人设、技能、记忆与工具，通过 Flask 中转完成任务拆解、分派与汇总。

- **后端**：Flask + Starlette/Uvicorn (ASGI)
- **通信协议**：MCP（Agent → 中枢）+ ACP（中枢 → Agent）
- **存储**：SQLite
- **前端**：原生 HTML/JS，实时展示多 Agent 对话过程

更多设计细节见 [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md) 和 [doc/design.md](doc/design.md)。

## 功能

- Leader / Specialist 两层 Agent 角色，自动任务拆解与汇总
- Web UI 实时观察多 Agent 对话、工具调用、子任务流转
- MCP Server 安装管理（headers/env 凭据自动脱敏存储）
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
| `FLASK_DEBUG` | `1` | 调试模式（自动 reload） |

### 4. 启动

```bash
python run.py
```

访问 [http://127.0.0.1:5050](http://127.0.0.1:5050)。

### 5. 运行测试

```bash
pytest
```

## 文档

- [架构设计](doc/ARCHITECTURE.md)
- [详细设计](doc/design.md)
- [MCP 管理](doc/mcp-management.md)
- [Skill 管理](doc/skills-management.md)

## License

MIT
