# 多 Agent Web 项目设计文档

## 1. 项目概述

### 1.1 项目目标

构建一个基于 Flask 的多 Agent 协作 Web 系统，支持在页面中创建、管理、观察和驱动多个基于 Hermes Profile 的智能体，并实现以下能力：

- 在 Web 页面创建 Agent，并绑定到 Hermes Profile
- 支持将某个 Agent 设置为 Leader Agent
- 支持用户向指定 Agent 发送消息
- 支持 Agent 之间通过平台中转进行协作通信
- 实时展示 Agent 的输入、输出、工具调用和状态变化
- 提供 MCP 能力供 Agent 调用系统工具
- 通过 ACP/进程控制驱动 Hermes Agent 执行任务

### 1.2 设计原则

- Agent 不直接互连，统一通过平台总线转发
- Web 前端可观察所有关键事件
- Leader 负责调度，Specialist 负责执行
- Hermes Profile 是 Agent 运行时的最小隔离单元
- 通信结构化，便于追踪、回放和审计
- 先单机可用，再逐步演进到持久化和分布式

### 1.3 非目标

当前阶段不优先解决以下问题：

- 多机分布式调度
- 强一致任务队列
- 复杂权限审批流
- 企业级租户隔离
- 长期记忆治理与向量检索系统

---

## 2. 用户场景

### 2.1 管理员场景

- 在页面创建一个新 Agent
- 为 Agent 指定名称、角色、描述、技能标签和 Hermes Profile
- 将某个 Agent 设为 Leader
- 查看所有 Agent 的运行状态和最近活动
- 启动、停止、重启指定 Agent

### 2.2 普通用户场景

- 选择一个 Agent 发起对话
- 给 Leader 发送复杂任务，由 Leader 自动分解并委派
- 查看每个 Agent 的输入、输出、处理中状态和最终结果
- 观察 Agent 之间的协作过程

### 2.3 Agent 协作场景

- Leader 查询当前可用 Agent 列表
- Leader 根据任务类型选择 Specialist
- Specialist 完成子任务后将结果回传给 Leader
- 普通 Agent 也可以通过 MCP 工具向其他 Agent 发送结构化消息

---

## 3. 总体架构

### 3.1 架构分层

系统分为四层：

1. Web 前端层
2. Flask 平台层
3. Agent Runtime 层
4. Hermes Profile 层

### 3.2 架构图

```text
┌─────────────────────────────────────────────────────┐
│                     Web Frontend                    │
│  Agent 列表 / 创建页 / 对话页 / 实时事件面板         │
└───────────────────────┬─────────────────────────────┘
                        │ HTTP / SSE / WS
┌───────────────────────▼─────────────────────────────┐
│                    Flask Backend                    │
│                                                     │
│  REST API     SSE Hub     MCP Server     Scheduler  │
│      │           │            │              │      │
│      └───────────┴──────┬─────┴──────────────┘      │
│                         │                            │
│              Agent Registry / Message Bus            │
│              Session Store / Event Store             │
└─────────────────────────┬────────────────────────────┘
                          │ ACP / stdio / subprocess
┌─────────────────────────▼────────────────────────────┐
│                  Agent Runtime Manager               │
│        ACP Client Pool / Profile Process Manager     │
└─────────────────────────┬────────────────────────────┘
                          │
         ┌────────────────┼────────────────┐
         │                │                │
┌────────▼──────┐ ┌───────▼────────┐ ┌────▼─────────┐
│ hermes -p     │ │ hermes -p      │ │ hermes -p    │
│ leader acp    │ │ analyst acp    │ │ writer acp   │
└───────────────┘ └────────────────┘ └──────────────┘
```

### 3.3 核心组件职责

- Web Frontend：展示状态、消息流、事件流，并提供 Agent 管理界面
- Flask API：处理创建 Agent、发送消息、查询状态等 HTTP 请求
- MCP Server：向 Agent 暴露平台工具
- Agent Registry：维护 Agent 元数据、状态、角色和负载
- Message Bus：统一消息路由和事件广播
- Runtime Manager：启动和维护 Hermes ACP 进程
- Event Store：保存消息、事件和任务关系

---

## 4. 核心概念模型

### 4.1 Agent

一个 Agent 是平台中的逻辑实体，对应一个 Hermes Profile 运行实例。

建议字段：

- `agent_id`：平台内唯一 ID
- `name`：展示名称
- `profile_name`：Hermes Profile 名称
- `role`：`leader` / `specialist` / `custom`
- `description`：职责描述
- `skills`：能力标签列表
- `status`：运行状态
- `model_config`：模型配置摘要
- `is_leader`：是否为当前 Leader
- `created_at`
- `updated_at`

### 4.2 Hermes Profile

每个 Profile 独立保存以下内容：

- `config.yaml`
- `.env`
- `SOUL.md`
- 本地记忆与会话上下文
- 独立技能配置

平台中的 Agent 创建，本质上是：

1. 创建或绑定一个 Hermes Profile
2. 为其补齐配置文件
3. 启动对应的 `hermes -p <profile> acp`
4. 将运行实例注册进 Agent Registry

### 4.3 Task

Task 表示一项可被追踪的工作单元。

建议字段：

- `task_id`
- `title`
- `origin`：`user` / `agent`
- `creator_agent_id`
- `owner_agent_id`
- `parent_task_id`
- `task_type`
- `priority`
- `status`
- `expected_output`
- `result_summary`
- `created_at`
- `completed_at`

### 4.4 Message

Message 表示用户、平台或 Agent 之间传递的结构化消息。

建议字段：

- `message_id`
- `task_id`
- `from_type`：`user` / `agent` / `system`
- `from_id`
- `to_type`
- `to_id`
- `message_type`：`prompt` / `reply` / `delegate` / `event`
- `content`
- `payload`
- `reply_to`
- `created_at`

### 4.5 Event

Event 用于记录实时过程。

建议事件类型：

- `agent.status_changed`
- `agent.input`
- `agent.output.chunk`
- `agent.output.final`
- `agent.tool_call`
- `agent.tool_result`
- `task.created`
- `task.assigned`
- `task.completed`
- `message.sent`
- `message.delivered`
- `runtime.error`

---

## 5. Agent 状态设计

### 5.1 运行状态

建议统一使用以下状态：

- `offline`：未启动或不可用
- `starting`：启动中
- `idle`：空闲，可接受任务
- `busy`：正在处理任务
- `waiting`：等待其他 Agent 或外部输入
- `error`：运行异常
- `stopping`：停止中

### 5.2 状态迁移

```text
offline -> starting -> idle
idle -> busy
busy -> waiting
waiting -> busy
busy -> idle
busy -> error
idle -> stopping -> offline
error -> starting
```

### 5.3 前端展示要求

前端 Agent 卡片至少展示：

- 名称
- 角色
- 当前状态
- 当前任务
- 最近一条输入
- 最近一条输出
- 最近活跃时间

---

## 6. 通信设计

### 6.1 通信原则

- 用户与 Agent 之间通过 Flask API 通信
- Agent 与平台之间通过 MCP 通信
- 平台与 Agent Runtime 之间通过 ACP 通信
- Agent 之间不直接访问彼此网络接口

### 6.2 两类协议分工

#### MCP

用于 Agent 主动调用平台能力，适合暴露以下工具：

- `list_agents`
- `get_agent_status`
- `send_to_agent`
- `delegate_task`
- `list_tasks`
- `get_task_context`
- `report_progress`

#### ACP

用于平台主动驱动 Agent：

- 初始化会话
- 向 Agent 投递 Prompt
- 读取流式输出
- 接收工具调用事件
- 接收完成结果
- 中断正在执行的任务

### 6.3 推荐消息结构

```json
{
  "message_id": "msg_001",
  "task_id": "task_001",
  "from": "leader",
  "to": "writer",
  "message_type": "delegate",
  "task_type": "writing",
  "content": "请根据分析结果撰写总结",
  "expected_output": "一段 300 字以内摘要",
  "reply_to": "msg_000"
}
```

### 6.4 典型消息流

#### 用户发消息给 Leader

1. 前端调用 `POST /api/messages`
2. Flask 创建任务和消息记录
3. Runtime Manager 通过 ACP 向 Leader 投递 Prompt
4. Leader 输出流式返回
5. Flask 将事件写入 Event Store
6. SSE 将事件推送给前端

#### Leader 委派任务给 Specialist

1. Leader 调用 MCP `list_agents`
2. 平台返回可用 Agent 列表
3. Leader 调用 MCP `delegate_task`
4. 平台生成子任务并投递给 Specialist
5. Specialist 输出过程持续广播
6. Specialist 完成后，平台把结果回投给 Leader

#### 普通 Agent 发送消息给其他 Agent

1. Agent 调用 MCP `send_to_agent`
2. 平台校验目标 Agent 状态
3. 平台写入消息并经 ACP 投递
4. 平台立即返回“已投递”
5. 后续结果通过新事件推送，不在同一次工具调用里阻塞等待

---

## 7. 后端设计

### 7.1 技术选型

- Web 框架：Flask
- 实时推送：SSE，后续可升级为 WebSocket
- 进程控制：Python `subprocess`
- 并发模型：线程 + 队列
- 持久化：SQLite 起步，后续可切 PostgreSQL
- ORM：SQLAlchemy
- 配置管理：Pydantic Settings 或原生配置类

### 7.2 后端模块划分

建议目录结构：

```text
app/
  __init__.py
  main.py
  config.py
  extensions.py
  api/
    agents.py
    messages.py
    tasks.py
    events.py
    runtime.py
  services/
    agent_registry.py
    runtime_manager.py
    message_bus.py
    task_service.py
    mcp_service.py
    event_service.py
  models/
    agent.py
    task.py
    message.py
    event.py
  schemas/
    agent.py
    task.py
    message.py
  runtime/
    acp_client.py
    profile_manager.py
  templates/
  static/
```

### 7.3 核心服务说明

#### AgentRegistryService

职责：

- 注册 Agent
- 更新 Agent 状态
- 查询可用 Agent
- 管理 Leader 标记

关键方法：

- `create_agent()`
- `set_leader(agent_id)`
- `list_agents()`
- `update_status(agent_id, status)`
- `get_available_agents(role=None)`

#### RuntimeManager

职责：

- 启动 Hermes ACP 进程
- 维护 ACPClient 池
- 接收流式输出
- 处理进程异常重连

关键方法：

- `start_agent(agent_id)`
- `stop_agent(agent_id)`
- `restart_agent(agent_id)`
- `send_prompt(agent_id, text, metadata=None)`
- `interrupt(agent_id, task_id=None)`

#### MessageBus

职责：

- 统一路由消息
- 生成事件
- 广播给前端订阅者
- 将 Agent 结果回投给上游 Agent

#### TaskService

职责：

- 创建任务树
- 建立父子任务关系
- 更新任务状态
- 汇总子任务结果

### 7.4 数据持久化建议

第一版建议至少持久化以下表：

- `agents`
- `tasks`
- `messages`
- `events`
- `agent_sessions`

其中：

- `messages` 负责保存业务消息
- `events` 负责保存流式过程
- `tasks` 负责保存任务拓扑

---

## 8. MCP 设计

### 8.1 MCP 工具清单

建议首版提供以下工具：

#### `list_agents`

用途：获取当前可用 Agent 列表。

输入：

- `role`：可选
- `only_available`：默认 `true`

输出：

- Agent 摘要列表

#### `get_agent_detail`

用途：获取指定 Agent 的详情。

输入：

- `agent_id`

#### `send_to_agent`

用途：发送普通消息给另一个 Agent。

输入：

- `to`
- `content`
- `task_id`
- `reply_to`

#### `delegate_task`

用途：Leader 向 Specialist 委派结构化任务。

输入：

- `to`
- `task_type`
- `content`
- `expected_output`
- `_from`
- `parent_task_id`

#### `report_progress`

用途：Agent 主动上报进度。

输入：

- `task_id`
- `progress_text`
- `progress_percent`

#### `list_tasks`

用途：查询当前上下文下的任务列表。

### 8.2 MCP 返回原则

- 工具调用应尽量快速返回
- 返回“已投递”或“已记录”即可
- 不在 MCP 工具里同步阻塞等待其他 Agent 完成
- 长过程通过事件机制反馈

---

## 9. Hermes Runtime 设计

### 9.1 Agent 创建流程

用户在页面创建 Agent 时：

1. 提交 Agent 基础信息
2. 后端生成 `agent_id`
3. 创建或绑定 Hermes Profile
4. 写入 `SOUL.md`、`config.yaml` 等配置
5. 注册到数据库和 Registry
6. 如选择自动启动，则立即启动 ACP 进程

### 9.2 Profile 配置模板

每个 Profile 至少包含：

- 人设定义
- MCP Server 地址
- 模型配置
- 工具开关
- 环境变量模板

Leader Profile 需额外强调：

- 先查可用 Agent 再做分配
- 不承担所有细节执行
- 尽量结构化委派任务

### 9.3 ACP Client 设计

每个运行中的 Agent 对应一个 ACPClient 实例，内部包含：

- 子进程句柄
- 标准输入输出流
- JSON-RPC 请求 ID 管理
- 读取线程
- 事件回调
- 心跳和错误恢复逻辑

### 9.4 容错策略

- 进程退出时将 Agent 状态设为 `error` 或 `offline`
- 支持手动重启
- 对短暂异常可做有限次数自动重连
- 对无法解析的事件做原始日志落盘

---

## 10. 前端设计

### 10.1 页面规划

建议首版包含以下页面：

#### Agent 管理页

- 查看所有 Agent
- 创建 Agent
- 编辑 Agent 基本信息
- 设置 Leader
- 启动/停止/重启 Agent

#### 对话协作页

- 左侧 Agent 列表
- 中间主对话区
- 右侧事件流面板
- 顶部任务状态区

#### Task 观察页

- 查看任务树
- 查看子任务执行状态
- 追踪任务关联消息

### 10.2 核心前端组件

- `AgentCard`
- `AgentStatusBadge`
- `CreateAgentForm`
- `ChatPanel`
- `MessageTimeline`
- `EventStreamPanel`
- `TaskTreePanel`
- `LeaderSelector`

### 10.3 实时更新方式

首版推荐使用 SSE：

- 后端实现简单
- 单向事件推送足够覆盖当前需求
- 适合消息流、状态流、工具流展示

订阅事件建议按以下维度过滤：

- 全局事件流
- 指定 Agent 事件流
- 指定 Task 事件流

### 10.4 展示要求

对每个 Agent 的输出应区分：

- 输入 Prompt
- 思考中的状态提示
- 工具调用事件
- 流式输出片段
- 最终回复

这样用户才能真正看清 Agent 在做什么，而不只是看到最终答案。

---

## 11. API 设计

### 11.1 Agent 管理接口

#### `POST /api/agents`

创建 Agent。

请求示例：

```json
{
  "name": "writer",
  "profile_name": "writer",
  "role": "specialist",
  "description": "负责撰写总结",
  "skills": ["writing", "summary"],
  "auto_start": true
}
```

#### `GET /api/agents`

查询 Agent 列表。

#### `GET /api/agents/<agent_id>`

查询 Agent 详情。

#### `POST /api/agents/<agent_id>/start`

启动 Agent。

#### `POST /api/agents/<agent_id>/stop`

停止 Agent。

#### `POST /api/agents/<agent_id>/restart`

重启 Agent。

#### `POST /api/agents/<agent_id>/set-leader`

将指定 Agent 设为 Leader。

### 11.2 消息接口

#### `POST /api/messages`

发送消息给 Agent。

请求示例：

```json
{
  "to_agent_id": "leader_001",
  "content": "请帮我分析这个需求，并安排协作执行",
  "task_type": "general"
}
```

#### `GET /api/messages`

按任务或 Agent 查询消息。

### 11.3 任务接口

#### `GET /api/tasks`

查询任务列表。

#### `GET /api/tasks/<task_id>`

查询任务详情和子任务。

### 11.4 实时事件接口

#### `GET /api/events/stream`

SSE 订阅事件流。

事件格式建议：

```json
{
  "event_type": "agent.output.chunk",
  "agent_id": "writer_001",
  "task_id": "task_001",
  "timestamp": "2026-04-24T10:00:00Z",
  "data": {
    "text": "正在生成摘要..."
  }
}
```

---

## 12. Leader 设计

### 12.1 Leader 职责

- 接收用户总任务
- 查询可用 Agent
- 拆分子任务
- 决定委派对象
- 汇总结果
- 向用户输出最终答复

### 12.2 Leader 决策流程

1. 读取任务目标
2. 调用 `list_agents`
3. 识别可用 Specialist
4. 拆分任务并打标签
5. 逐个委派
6. 追踪结果是否返回完整
7. 汇总生成最终回复

### 12.3 Leader 选择规则

优先按以下维度排序：

- 角色匹配度
- 技能匹配度
- 状态可用性
- 当前负载
- 默认优先级

### 12.4 Leader 限制

- 不应假设系统里固定有哪些 Agent
- 不应绕过 Registry 直接猜测路由
- 不应把所有任务都自己做完

---

## 13. 安全与约束

### 13.1 基础约束

- Agent 间通信必须经过平台
- 平台统一记录消息和事件
- 停止状态的 Agent 不允许接收新任务
- 设为 Leader 时需保证全局唯一

### 13.2 输入校验

- 校验 `profile_name` 合法性
- 校验 `agent_id` 是否存在
- 校验目标 Agent 当前状态
- 校验消息大小和结构

### 13.3 后续可扩展安全能力

- MCP 工具级权限控制
- 特定 Agent 白名单通信
- 敏感工具审批
- 审计日志与操作回放

---

## 14. 部署方案

### 14.1 第一阶段部署

建议单机部署：

- 1 个 Flask 服务
- N 个 Hermes Profile 进程
- 1 个 SQLite 数据库
- 1 个 Web 前端

### 14.2 运行要求

- 本机已安装 Hermes CLI
- 已准备好模型 API Key
- Flask 服务可被 Profile 中的 MCP 配置访问
- 服务器具备创建子进程权限

### 14.3 后续升级方向

- SQLite 升级 PostgreSQL
- SSE 升级 WebSocket
- 单机 Runtime 升级为分布式 Worker
- 引入 Redis 做事件总线与状态同步

---

## 15. 开发阶段建议

### Phase 1：最小可用版本

目标：

- 手动预置 2 到 3 个 Profile
- 可启动 Agent
- 可给 Agent 发消息
- 可看到实时输出

交付：

- Agent 列表页
- 对话页
- SSE 事件流
- ACP Runtime Manager

### Phase 2：多 Agent 协作

目标：

- 增加 Leader Agent
- 增加 MCP 工具
- 支持 Leader 委派任务
- 支持子任务和任务树展示

### Phase 3：平台化管理

目标：

- 页面创建 Agent
- 自动创建 Hermes Profile
- 持久化历史消息和事件
- 增加错误恢复和重启能力

### Phase 4：增强能力

目标：

- 权限体系
- 更复杂调度策略
- 多机部署
- 历史回放与分析

---

## 16. 风险与应对

### 16.1 Hermes 进程稳定性

风险：

- ACP 进程退出
- 输出事件格式变化

应对：

- 封装 Runtime Adapter
- 保留原始事件日志
- 实现重启与降级处理

### 16.2 消息风暴

风险：

- 多 Agent 互相频繁发消息

应对：

- 设置单任务消息数阈值
- 增加委派深度限制
- 对重复事件做去重

### 16.3 Leader 误调度

风险：

- 将任务发给不适合的 Agent

应对：

- Registry 提供结构化能力描述
- 限制 Leader 必须先查 `list_agents`
- 前端保留调度过程便于排查

---

## 17. 最终建议

这个项目最合理的落地方式是：

- 用 Flask 做平台中枢
- 用 Hermes Profile 做 Agent 隔离
- 用 ACP 驱动 Agent 执行
- 用 MCP 暴露平台工具给 Agent
- 用 SSE 把全过程实时呈现到前端
- 用 Leader + Specialist 模式组织多 Agent 协作

首版不必追求过度复杂，先确保以下闭环跑通：

1. 页面创建 Agent
2. 启动 Hermes Profile
3. 给 Agent 发消息
4. 实时看到输入输出
5. Leader 成功委派给其他 Agent
6. 前端能看到完整协作过程

---

## 18. 一句话方案结论

这是一个以 Flask 为中枢、Hermes Profile 为运行单元、MCP 为 Agent 工具入口、ACP 为执行驱动通道、Leader 为调度核心的多 Agent 可观测协作平台。
