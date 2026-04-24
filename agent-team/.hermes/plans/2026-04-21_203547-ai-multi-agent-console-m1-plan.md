# AI 多Agent Web 控制台 M1 实施计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 产出一版可直接启动开发的 M1 实施计划，覆盖目录、模块、接口、事件、数据、adapter 与任务拆解。

**Architecture:** 采用 monorepo 组织 console-web、console-bff、console-adapter 三个核心应用。前端通过 REST + WebSocket 与 BFF 通信，BFF 负责持久化、聚合与转发，adapter 负责把 Hermes 现有脚本/tmux 运行态转成标准事件流。

**Tech Stack:** Next.js/React, NestJS, PostgreSQL, Redis, WebSocket, Prisma/TypeORM（二选一，建议 Prisma）, pnpm workspace。

---

## 当前上下文 / 假设
- 已确认 MVP 目标：查看多个 agent 状态、聊天记录、agent 间跳转、向单个或全部 agent 发消息。
- 已确认技术栈：Next.js/React + NestJS/BFF + PostgreSQL + Redis + WebSocket。
- Hermes 现阶段主要通过 tmux + shell scripts 运转，MVP 不改 Hermes 核心链路。
- 默认本地部署优先，先服务内部团队使用，不先做复杂多租户与细权限。

## 目录结构建议
- `apps/console-web`：前端控制台，承载 agent 列表、聊天面板、状态侧栏。
- `apps/console-bff`：NestJS 聚合层，承接 REST、WebSocket、鉴权、存储访问。
- `apps/console-adapter`：Hermes 集成层，负责轮询脚本、解析输出、推送标准事件。
- `packages/ui`：共享 UI 组件、主题、状态标签、聊天消息渲染单元。
- `packages/shared-types`：共享 DTO、事件类型、枚举、Zod schema。
- `packages/config`：eslint、tsconfig、环境变量 schema、公共常量。
- `infra/docker`：本地 Postgres/Redis/docker-compose 与启动脚本。
- `docs/architecture`：架构图、事件流、接口说明、启动说明。

建议初版树：
```text
agent-console/
  apps/
    console-web/
      app/
      components/
      features/
      lib/
      hooks/
    console-bff/
      src/
        modules/
        gateways/
        prisma/
        common/
    console-adapter/
      src/
        collectors/
        parsers/
        publishers/
        providers/
  packages/
    ui/
    shared-types/
    config/
  infra/docker/
  docs/architecture/
  .env.example
  pnpm-workspace.yaml
```

## 前后端模块设计

### 前端 console-web
- `features/agents`：agent 列表、在线状态、当前选中 agent。
- `features/conversations`：会话列表、未读数、历史分页、跳转入口。
- `features/chat`：消息流、发送框、广播发送、重试提示。
- `features/activity`：日志/事件侧栏，展示 status/log/task/message 事件。
- `features/layout`：三栏布局、顶部连接状态、全局过滤器。
- `lib/ws-client`：WebSocket 连接、重连、订阅管理。
- `lib/api-client`：REST 请求封装、错误处理、分页参数。

### 后端 console-bff
- `agents` 模块：agent 列表、详情、状态快照、能力信息。
- `conversations` 模块：会话查询、创建、最近活跃会话。
- `messages` 模块：消息写入、分页读取、广播分发结果。
- `dispatch` 模块：发送到单 agent / 多 agent，跟踪任务状态。
- `events` 模块：事件入库、回放、按 agent / conversation 查询。
- `gateway` 模块：WebSocket 握手、订阅、增量推送、重连补发。
- `integrations` 模块：接收 adapter 上报，做格式校验、幂等落库。

### adapter 模块
- `providers/hermes-script-provider`：封装 `send-to-agent.sh`、`read-agent-output.sh`、`collect-team-output.sh`。
- `collectors/agent-status-collector`：采集 agent session、最近活跃时间、在线态。
- `collectors/agent-output-collector`：抓取输出增量并切分消息/日志事件。
- `parsers/output-parser`：把 shell 输出解析为标准 AgentEvent / MessageCandidate。
- `publishers/bff-publisher`：将事件 POST 或 WS 推送到 BFF ingest 端点。
- `providers/profile-reader`：读取 `~/.hermes/profiles/<name>` 与团队目录元数据。

## API草案

### Agents
- `GET /api/agents`：返回 agent 列表、在线态、最后活跃时间、未读数。
- `GET /api/agents/:agentId`：返回单 agent 详情、profile 摘要、最近状态。
- `GET /api/agents/:agentId/events?cursor=`：返回该 agent 最近事件流。

### Conversations
- `GET /api/conversations?scope=&agentId=&cursor=`：返回会话列表。
- `POST /api/conversations`：创建会话，body 包含 `scope`、`participantAgentIds`、`title`。
- `GET /api/conversations/:conversationId/messages?cursor=`：分页获取消息。

### Messages / Dispatch
- `POST /api/messages`：发送消息，body 包含 `targetScope`、`targetIds`、`content`、`conversationId?`。
- `GET /api/dispatch-tasks/:taskId`：查询某次单发/广播任务结果。
- `POST /api/messages/:messageId/retry`：重试失败发送。

### Adapter ingest
- `POST /api/internal/adapter/events`：adapter 批量上报标准事件。
- `POST /api/internal/adapter/agents/snapshot`：adapter 上报 agent 当前状态快照。
- `POST /api/internal/adapter/conversations/sync`：可选，回补解析出的历史消息。

### 示例响应骨架
```json
{
  "data": {
    "id": "agt_engineer",
    "name": "engineer",
    "status": "online",
    "lastSeenAt": "2026-04-21T20:30:00Z",
    "unreadCount": 3
  }
}
```

## WebSocket事件模型
- 统一信封：`type`、`version`、`eventId`、`occurredAt`、`agentId?`、`conversationId?`、`payload`。
- `agent.status.updated`：agent 上下线、busy/idle、session 变化。
- `conversation.updated`：会话新建、标题变化、参与者变化、最后消息时间变化。
- `message.created`：新消息进入会话，可来自 user/agent/system。
- `dispatch.updated`：某次群发/单发任务状态变化，支持 pending/sent/partial_failed/failed/succeeded。
- `agent.log.appended`：增量日志片段，主要用于活动侧栏，不默认进入消息流。
- `sync.snapshot`：重连后全量快照，携带 agents、conversations、unreadCounts。

建议事件示例：
```json
{
  "type": "message.created",
  "version": 1,
  "eventId": "evt_001",
  "occurredAt": "2026-04-21T20:35:00Z",
  "agentId": "agt_engineer",
  "conversationId": "conv_001",
  "payload": {
    "messageId": "msg_001",
    "senderType": "agent",
    "content": "已完成第一版方案整理",
    "seq": 18
  }
}
```

## 数据模型草案

### agents
- `id`：字符串主键，建议 `agt_<name>`。
- `name`：agent 名称，如 engineer / qa。
- `role`：角色类型。
- `profile_path`：Hermes profile 目录。
- `status`：online/offline/busy/idle。
- `current_session_id`：当前运行 session。
- `last_seen_at`：最近活动时间。
- `capabilities_json`：能力标签与说明。

### conversations
- `id`、`scope`、`title`、`source`、`created_at`、`last_message_at`。
- `scope` 先支持 `direct` / `broadcast`。
- `source` 区分 `console` / `adapter-imported`。

### conversation_participants
- `conversation_id`、`agent_id`、`joined_at`、`last_read_seq`。
- 用于多 agent 会话与未读计算。

### messages
- `id`、`conversation_id`、`sender_type`、`sender_id`、`content`、`content_format`、`seq`、`created_at`、`source_id`。
- `source_id` 用于去重，映射 Hermes 原始采集来源。

### agent_events
- `id`、`agent_id`、`conversation_id?`、`event_type`、`payload_json`、`occurred_at`、`ingested_at`。
- 既支持界面回放，也支持排障与审计。

### dispatch_tasks / dispatch_task_targets
- 一张主表记录广播任务；一张子表记录每个 agent 的发送结果。
- 状态建议：pending / running / succeeded / partial_failed / failed。

## Hermes console-adapter 集成方案
- adapter 独立为 Node.js 服务，周期性轮询 Hermes 脚本并向 BFF 上报事件。
- 发送链路：BFF 接收到 `POST /api/messages` 后，调用 adapter；adapter 再调用 `send-to-agent.sh` 或 `ask-agent.sh`。
- 读取链路：adapter 定时调用 `read-agent-output.sh <agent>` 与 `collect-team-output.sh --lines N` 获取增量输出。
- 解析链路：先按 agent/session 分片，再区分“聊天消息 / 系统日志 / 状态变更 / 错误信息”。
- 状态链路：通过 tmux session/window 存活情况 + 最近输出时间，推断 online/offline/idle/busy。
- profile 采集：读取 `~/.hermes/profiles/<name>/SOUL.md`、团队目录上下文，生成 agent 展示摘要。
- 幂等策略：adapter 为每条采集结果生成 `source_id`，BFF 侧按 `source_id + agent_id` 去重。
- 故障策略：脚本失败不阻断服务；adapter 记录 error event，并让 BFF 标记 agent 状态为 degraded。

## M1开发任务拆解

### 第 1-2 天：工程初始化
- 创建 monorepo、pnpm workspace、基础 tsconfig/eslint/prettier。
- 初始化 `console-web`、`console-bff`、`console-adapter` 三个应用。
- 建立 `packages/shared-types` 与 `packages/config`。
- 搭建 Docker 本地依赖：Postgres、Redis。
- 输出 `.env.example`、`README.md`、启动脚本。

### 第 3-4 天：后端骨架与数据层
- 在 BFF 初始化 NestJS 模块：agents、conversations、messages、dispatch、gateway、integrations。
- 建立 Prisma schema 与首版 migration。
- 实现 `/api/agents`、`/api/conversations`、`/api/conversations/:id/messages` 空壳接口。
- 接通 Postgres 与 Redis，补 health check。

### 第 5-6 天：adapter MVP
- 封装 Hermes 脚本调用器。
- 完成 agent 状态采集与最近输出采集。
- 定义标准事件结构并接入 `/api/internal/adapter/events`。
- 完成基础解析器：把输出拆成 message/log/status 三类。

### 第 7-8 天：消息发送闭环
- 打通 `POST /api/messages` → adapter → Hermes script。
- 建立 dispatch_tasks 与 per-agent result 状态更新。
- 完成单 agent 发送结果回写与错误处理。
- 补充广播发送最小实现，但 UI 可先隐藏高级配置。

### 第 9-10 天：前端控制台 MVP
- 完成三栏布局：agent 列表 / 消息区 / 活动侧栏。
- 接入 agents、conversations、messages REST 查询。
- 接入 WebSocket，支持 `message.created` 与 `agent.status.updated`。
- 实现单 agent 消息发送、最近消息刷新、连接状态提示。

### 第 11-12 天：联调与验收
- 完成断线重连、快照补拉、未读数刷新。
- 修复消息去重、顺序与状态闪烁问题。
- 补最小测试：后端集成测试、adapter 解析测试、前端关键状态测试。
- 输出部署说明、演示脚本、M1 验收清单。

## 技术前置条件与风险

### 前置条件
- 需要确认项目仓库位置与是否新建独立 monorepo。
- 需要确认 Hermes 脚本调用权限、tmux session 命名规则、输出格式稳定性。
- 需要确认 Postgres/Redis 本地运行方式，建议统一 docker compose。
- 需要确认 agent 唯一标识规则，避免后续数据库主键和前端路由变动。

### 主要风险
- 脚本输出非结构化，消息解析误差高。规避：先定义 parser 规则与 fallback 日志通道。
- 同一输出被重复采集。规避：用 source_id、offset、采集水位去重。
- WebSocket 断线后状态错乱。规避：采用 snapshot + delta 模式。
- 广播发送存在部分成功。规避：从第一版起引入 dispatch_tasks 子状态。
- adapter 过度耦合现有脚本。规避：provider 层抽象，后续可替换为原生 Hermes API。
- 若后续要求权限与远程部署，当前数据模型需扩展 user/workspace 维度。

## 验证与启动检查
- `pnpm install` 可一次完成所有 workspace 依赖安装。
- `docker compose up -d` 能启动 Postgres/Redis。
- `pnpm --filter console-bff test` 至少能跑通模块基础测试。
- `pnpm --filter console-adapter test` 能验证输出解析与事件映射。
- `pnpm --filter console-web test` 能验证关键 UI 状态。
- 本地联调时，页面应能看到 agent 列表、在线状态、最近消息，并成功向单 agent 发消息。
