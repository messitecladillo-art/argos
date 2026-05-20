# 多 Agent Web 项目设计文档

本文档描述当前代码实现，而不是早期规划草案。

## 1. 项目概述

Hermes Agents Team 是一个本地 Web 控制台，用于创建、管理、观察和驱动多个 Hermes Profile Agent。

当前实现具备：

- 创建 / 删除 Leader 与 Worker Agent。
- 启动、停止、重启单个或全部 Agent。
- 用户向团队或指定 Worker 提交任务。
- 使用 Hermes Kanban 持久化任务、子任务、依赖和运行结果。
- Leader 通过 MCP 查询 Worker 并创建 Worker Kanban 子任务。
- Web UI 实时展示 Agent 状态、事件、消息、Kanban 任务和终端输出。
- 管理每个 Agent 的 MCP servers、skills、SOUL.md 和模型配置。
- 团队导入 / 导出。

非目标：

- 多租户权限系统。
- 公网安全网关。
- 分布式多机调度。
- 长期记忆治理或向量检索。

---

## 2. 角色模型

### 2.1 Agent

一个 Agent 是平台中的逻辑实体，对应一个 Hermes profile。

实际字段见 `app/db/models.py::AgentRecord`，主要包括：

| 字段 | 说明 |
|---|---|
| `agent_id` | 平台内唯一 ID，按 profile 生成。 |
| `profile_name` | Hermes profile 名称。 |
| `name` | 展示名称。 |
| `role` | `leader` 或 `worker`。 |
| `description` | 职责描述。 |
| `is_leader` | 是否为 Leader。 |
| `workspace_path` | Agent 工作区路径。 |
| `status` | 业务状态，如 `idle`、`busy`、`waiting`。 |
| `runtime_status` | 运行时状态，如 `stopped`、`running`。 |
| `interaction_state` | 人机交互状态。 |
| `orchestration_state` | 编排状态。 |
| `queue_depth` | 队列深度。 |
| `readiness_status` | `ready`、`preparing`、`failed` 等就绪状态。 |
| `model_summary` | 快照中动态读取的模型摘要。 |

当前只允许一个 Leader。

### 2.2 Hermes Profile

每个 profile 独立保存：

- `config.yaml`
- `SOUL.md`
- `team-meta.json`
- `skills/`
- `memories/`
- MCP server 配置

创建 Agent 时会 clone 当前 Hermes profile，使新 Agent 继承基础模型与配置。

### 2.3 UserTask / Delegation / Assignment

| 模型 | 说明 |
|---|---|
| `UserTask` | 用户提交的顶层任务。 |
| `Delegation` | Leader 一轮派发产生的一组 Worker 子任务。 |
| `Assignment` | 单个 Worker 的子任务记录。 |
| `KanbanTaskLink` | 本地对象与 Hermes Kanban task id 的映射。 |

长时任务通过 `current_round`、`max_rounds`、`review_task_ids` 跟踪多轮执行。

---

## 3. 总体架构

```text
Web UI
  ├─ REST API
  ├─ SSE: /api/events/stream
  └─ Terminal WS: /api/agents/<agent_id>/terminal/ws

Starlette / Uvicorn
  ├─ Flask App
  │   ├─ Agent / Message / Kanban / MCP / Skill / Model / Transfer APIs
  │   ├─ RuntimeStore
  │   └─ SQLite
  └─ FastMCP App: /mcp/

Hermes
  ├─ profile runtime
  └─ kanban CLI / dispatcher / gateway
```

启动入口是 `run.py`，默认监听 `127.0.0.1:5050`。

---

## 4. 通信设计

### 4.1 用户入口

`POST /api/messages` 调用 `messages.send_user_task(...)`。

行为：

1. 校验任务内容。
2. 如果指定 Worker，则创建 Worker 直派 Kanban 任务。
3. 如果未指定或指定 Leader，则创建给 Leader 的 Kanban 父任务。
4. 写入本地 `UserTask` 和 `KanbanTaskLink`。
5. 推送 `kanban.task.created` 事件。
6. 触发项目内 dispatch worker。

### 4.2 Leader 到 Worker

Leader 不直接调用 Worker 网络接口，也不直接通过 ACP 投递子任务。

Leader 在 Kanban 任务中调用 MCP：

```text
mcp_agent_bus_list_workers()
mcp_agent_bus_create_kanban_worker_tasks(...)
```

平台随后：

1. 创建 `Delegation`。
2. 创建多条 `Assignment`。
3. 创建多个 Worker Kanban 子任务。
4. 记录 `KanbanTaskLink`。
5. 触发 dispatch。

### 4.3 人工输入

Agent 需要用户决策或补充信息时，调用：

```text
mcp_agent_bus_request_human_input(...)
```

平台会创建人工处理 Kanban 任务，用户在 Web UI 中回答后，相关任务会被 unblock 并继续执行。

---

## 5. MCP 工具

当前 MCP 工具定义如下：

| 工具 | 参数摘要 | 说明 |
|---|---|---|
| `list_workers` | 无 | 返回可调度 Worker 列表。 |
| `create_kanban_worker_tasks` | `assignments`, `from_agent_id`, `parent_task_id`, `user_task_id`, `summary_instruction` | 创建一批 Worker Kanban 子任务。 |
| `dispatch_parallel` | `assignments`, `from_agent_id`, `summary_instruction` | 兼容入口，内部转到 `create_kanban_worker_tasks`。 |
| `request_human_input` | `question`, `from_agent_id`, `context`, `options`, `parent_task_id`, `user_task_id` | 创建人工输入任务。 |

早期文档中的 `list_agents`、`delegate_task`、`send_to_agent`、`report_progress` 不属于当前 MCP 实现。

---

## 6. 后端模块

```text
app/
  asgi.py                 Starlette ASGI 入口，挂载 Flask、MCP、终端 WebSocket
  mcp_server.py           Agent 可调用的 MCP 工具
  config.py               环境变量配置
  controllers/            HTTP API 蓝图
  services/               业务服务
  db/                     SQLAlchemy 模型、session、轻量迁移
  models/store/           RuntimeStore 与内存状态 mixin
  static/                 前端资源
  templates/              页面模板
```

关键服务：

| 服务 | 说明 |
|---|---|
| `services/agents.py` | Agent 创建、删除、工作区清理。 |
| `services/messages.py` | 用户任务入口，创建 Kanban 父任务或直派 Worker 任务。 |
| `services/kanban.py` | Hermes Kanban CLI 适配层。 |
| `services/kanban_dispatch.py` | 项目内 dispatch worker。 |
| `services/kanban_sync.py` | Kanban 状态同步与多轮 review 编排。 |
| `services/mcp_installer.py` | Agent MCP server 管理。 |
| `services/skill_installer.py` | Agent skill 安装、查看、卸载、重装。 |
| `services/model_configs.py` | 模型配置管理。 |
| `services/transfer.py` | 团队导入导出。 |
| `services/acp/` | Agent 运行时进程与终端连接。 |

---

## 7. API 设计

### 7.1 Agent

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/dashboard` | 获取页面快照。 |
| `GET` | `/api/profiles` | 列出 Hermes profiles。 |
| `GET` | `/api/hermes/status` | 检查 Hermes CLI。 |
| `POST` | `/api/agents` | 创建 Agent。 |
| `DELETE` | `/api/agents/<agent_id>` | 删除 Agent。 |
| `POST` | `/api/agents/<agent_id>/start` | 启动 Agent。 |
| `POST` | `/api/agents/<agent_id>/stop` | 停止 Agent。 |
| `POST` | `/api/agents/<agent_id>/restart` | 重启 Agent。 |
| `POST` | `/api/agents/runtime` | 批量 start / stop / restart。 |
| `POST` | `/api/agents/initialize` | 初始化团队运行状态，可清空工作区和历史。 |

创建 Agent 请求：

```json
{
  "name": "开发 Agent",
  "profile_name": "dev",
  "role": "worker",
  "description": "负责代码实现"
}
```

`role` 只能是 `leader` 或 `worker`。

### 7.2 消息与事件

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/messages` | 提交用户任务。 |
| `GET` | `/api/events/stream` | SSE 事件流。 |

### 7.3 Kanban

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/kanban/tasks` | 当前本地可见 Kanban 任务链接。 |
| `GET` | `/api/kanban/tasks/<task_id>/runs` | 任务运行记录。 |
| `GET` | `/api/kanban/tasks/<task_id>/log` | 任务日志。 |
| `GET` | `/api/kanban/tasks/<task_id>/details` | 任务详情、runs、context、log。 |
| `POST` | `/api/kanban/tasks/<task_id>/unblock` | 解除阻塞。 |
| `POST` | `/api/kanban/tasks/<task_id>/answer` | 回答人工输入任务。 |
| `POST` | `/api/kanban/tasks/<task_id>/dispatch` | 调度单个任务。 |
| `DELETE` | `/api/kanban/tasks/<task_id>` | 归档任务。 |
| `DELETE` | `/api/kanban/tasks/done` | 归档 done 列。 |
| `DELETE` | `/api/kanban/tasks/column/<column_key>` | 归档指定列。 |
| `POST` | `/api/kanban/dispatch` | 触发一次 dispatch。 |
| `GET/PUT` | `/api/kanban/settings` | Kanban 自动派发设置。 |

### 7.4 MCP / Skill / Model / Transfer

这些接口分别见：

- [mcp-management.md](mcp-management.md)
- [skills-management.md](skills-management.md)
- [model-config.md](model-config.md)
- [import-export.md](import-export.md)

---

## 8. 状态与事件

Agent 主要状态分为：

| 字段 | 典型值 |
|---|---|
| `status` | `idle`、`busy`、`waiting`、`offline` |
| `runtime_status` | `stopped`、`starting`、`running`、`error` |
| `interaction_state` | `idle`、`waiting_human` 等 |
| `orchestration_state` | `none`、`waiting_workers` 等 |
| `readiness_status` | `preparing`、`ready`、`failed` |

事件通过 RuntimeStore 推送到 SSE。终端输出属于高频 UI 状态，不作为持久审计事件保存。

---

## 9. 数据库

实际表：

- `agents`
- `user_tasks`
- `delegations`
- `assignments`
- `kanban_task_links`
- `settings`
- `model_configs`
- `messages`
- `events`
- `agent_skill_installs`
- `agent_mcp_servers`

SQLite 启动时会执行轻量迁移，补齐长时任务字段：

- `user_tasks.current_round`
- `user_tasks.max_rounds`
- `user_tasks.review_task_ids_json`
- `user_tasks.blocked_at`
- `user_tasks.block_reason`
- `delegations.round`
- `delegations.review_task_id`
- `delegations.reviewed_at`

---

## 10. 前端页面

当前前端是原生 HTML/JS：

- Agent 列表与状态。
- 用户任务输入。
- Kanban 任务列表与操作。
- 事件流与消息流。
- MCP / Skill / Model / SOUL / Transfer 管理弹窗。
- 终端面板，通过 WebSocket 连接运行中的 Agent。

---

## 11. 安全边界

当前定位是本地或可信内网使用：

- 没有内置用户登录和权限系统。
- 不建议裸露到公网。
- MCP stdio 会执行本机命令，配置前需要信任来源。
- 模型 API Key 和 MCP secret 保存在本机 profile/config 中。
- 导入导出会对部分 secret 做提示或占位化，但不能替代完整的密钥治理。

---

## 12. 当前执行闭环

```text
用户输入
  -> /api/messages
  -> UserTask + Kanban parent
  -> Leader 执行
  -> list_workers
  -> create_kanban_worker_tasks
  -> Worker Kanban tasks
  -> kanban_sync 发现全部完成
  -> Leader review task
  -> 完成 / 下一轮 / 阻塞
  -> UI 通过 SSE 展示状态
```
