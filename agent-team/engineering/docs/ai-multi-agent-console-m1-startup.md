# AI 多Agent Web 控制台启动文档（M1）

## repo目录结构建议
- `apps/web`：Next.js 前端控制台；包含 `app/`、`components/`、`features/agents`、`features/conversations`、`features/chat`、`features/realtime`、`lib/`。
- `apps/api`：NestJS BFF；包含 `modules/agents`、`modules/conversations`、`modules/messages`、`modules/dispatch`、`modules/events`、`modules/integrations`、`gateways/`、`prisma/`、`config/`。
- `apps/adapter`：Hermes console-adapter；包含 `providers/`、`collectors/`、`parsers/`、`publishers/`、`schedulers/`、`types/`。
- `packages/shared`：共享 DTO、API 类型、WebSocket 事件类型、Zod/Schema、数据库枚举。
- `packages/ui`：共享 UI 组件、主题、状态标签、聊天消息渲染组件。
- `packages/config`：共享 tsconfig、eslint、prettier、环境变量 schema。
- `infra/docker`：`docker-compose.yml`、Postgres 初始化、Redis 本地运行配置。
- `engineering/docs`：启动文档、架构说明、接口契约、实施计划。
- 根目录保留 `.env.example`、`pnpm-workspace.yaml`、根 `package.json`、`README.md`。
- 前端建议核心文件：`apps/web/features/realtime/ws-client.ts`、`apps/web/features/chat/api.ts`、`apps/web/features/agents/store.ts`。
- 后端建议核心文件：`apps/api/src/gateways/console.gateway.ts`、`apps/api/prisma/schema.prisma`、`apps/api/src/modules/integrations/adapter-ingest.controller.ts`。
- adapter 建议核心文件：`apps/adapter/src/providers/hermes-script.provider.ts`、`apps/adapter/src/collectors/agent-output.collector.ts`、`apps/adapter/src/parsers/output.parser.ts`。

## API契约初稿
- 通用约定：Base URL 为 `/api`；JSON 请求响应；时间字段统一 ISO 8601；列表接口返回 `data` + `page`；错误返回 `error`。
- `GET /api/agents`：查询 agent 列表；返回字段含 `id`、`name`、`role`、`profileName`、`status`、`currentSessionId`、`lastSeenAt`、`unreadCount`、`capabilities`。
- `GET /api/agents/:agentId`：查询单 agent 详情；返回字段补充 `profilePath`、`summary`。
- `GET /api/agents/:agentId/events?cursor=&limit=`：查询单 agent 事件流；返回 `eventId`、`type`、`agentId`、`conversationId`、`occurredAt`、`payload`。
- `GET /api/conversations?scope=&agentId=&cursor=&limit=`：查询会话列表；返回 `id`、`scope`、`title`、`participantAgentIds`、`lastMessagePreview`、`lastMessageAt`、`unreadCount`。
- `POST /api/conversations`：创建会话；请求字段 `scope`、`title`、`participantAgentIds`；响应返回 `id`、`createdAt`。
- `GET /api/conversations/:conversationId/messages?cursor=&limit=`：分页拉取消息；返回 `id`、`conversationId`、`senderType`、`senderId`、`content`、`contentFormat`、`seq`、`createdAt`、`deliveryStatus`。
- `POST /api/messages`：发送消息；请求字段 `targetScope`、`targetIds`、`conversationId?`、`content`、`contentFormat`；响应返回 `dispatchTaskId`、`conversationId`、`acceptedTargetCount`、`status`。
- `GET /api/dispatch-tasks/:taskId`：查询发送任务状态；返回 `id`、`targetScope`、`status`、`createdAt`、`targets[]`，子项含 `agentId`、`status`、`errorMessage`、`deliveredAt`。
- `POST /api/internal/adapter/events`：adapter 批量上报事件；请求字段 `source`、`events[]`；事件字段含 `eventId`、`type`、`agentId`、`conversationId`、`occurredAt`、`sourceId`、`payload`；响应返回 `accepted`、`deduplicated`、`failed`。
- `POST /api/internal/adapter/agents/snapshot`：adapter 上报 agent 状态快照；请求字段 `capturedAt`、`agents[]`；单项含 `id`、`name`、`status`、`currentSessionId`、`lastSeenAt`。
- `targetScope` 枚举：`direct | broadcast`。
- agent 状态枚举：`online | offline | busy | idle | degraded`。
- 消息发送方枚举：`user | agent | system`。
- M1 消息格式先固定 `contentFormat = text`。
- cursor 分页统一采用字符串游标；M1 不强制 offset 分页。
- 通用错误结构：`error.code`、`error.message`、`error.details`。

## WebSocket事件契约初稿
- 统一事件信封字段：`type`、`version`、`eventId`、`occurredAt`、`agentId?`、`conversationId?`、`payload`。
- `version` 在 M1 固定为 `1`，后续通过版本升级兼容事件变更。
- `agent.status.updated`：payload 含 `status`、`previousStatus`、`currentSessionId`、`lastSeenAt`。
- `conversation.updated`：payload 含 `id`、`scope`、`title`、`participantAgentIds`、`lastMessageAt`、`unreadCount`。
- `message.created`：payload 含 `messageId`、`senderType`、`senderId`、`content`、`contentFormat`、`seq`、`deliveryStatus`。
- `dispatch.updated`：payload 含 `dispatchTaskId`、`targetScope`、`status`、`targets[]`；子项含 `agentId`、`status`、`errorMessage?`。
- `agent.log.appended`：payload 含 `level`、`stream`、`chunk`、`sourceId`；用于活动侧栏，不默认写入聊天流。
- `sync.snapshot`：payload 含 `agents[]`、`conversations[]`、`serverTime`；用于重连后全量同步。
- `ingest.error`：payload 含 `source`、`stage`、`message`、`retryable`；用于 adapter 采集或解析失败可视化。
- 推荐订阅粒度：全局订阅 + 按 `agentId` / `conversationId` 前端本地过滤。
- 推荐顺序控制：消息事件 payload 内带 `seq`；事件存储带 `occurredAt` 与 `eventId`。
- 推荐幂等策略：前端按 `eventId` 去重；消息按 `messageId` 去重。
- `dispatch.updated.status` 枚举：`pending | running | succeeded | partial_failed | failed`。
- `agent.log.appended.level` 枚举：`info | warn | error`。
- `sync.snapshot` 只在首次连接或断线重连后下发，不替代增量事件流。
- 所有事件均要求可落库回放，便于历史审计与问题排查。

## M1里程碑与开发顺序
- M1 目标：实现 agent 列表、在线状态、最近会话、消息查看、单 agent 发消息、基础实时推送。
- 里程碑 1（1-2 天）：初始化 monorepo、`apps/web`、`apps/api`、`apps/adapter`、`packages/shared`、`infra/docker`、`.env.example`。
- 里程碑 2（2 天）：完成 Prisma schema 初版与数据库 migration；落地 agents、conversations、messages、dispatch、events 基础表。
- 里程碑 3（2 天）：完成 NestJS 模块骨架；实现 `GET /api/agents`、`GET /api/conversations`、`GET /api/conversations/:id/messages` 基础接口。
- 里程碑 4（2 天）：完成 adapter 脚本 provider；打通 `read-agent-output.sh`、`collect-team-output.sh`、`send-to-agent.sh` 调用。
- 里程碑 5（2 天）：完成输出解析与事件映射；接通 `POST /api/internal/adapter/events` 与快照上报。
- 里程碑 6（2 天）：完成 `POST /api/messages` 与 `GET /api/dispatch-tasks/:taskId`；打通单 agent 发送闭环。
- 里程碑 7（2 天）：完成 WebSocket 网关；支持 `agent.status.updated`、`message.created`、`dispatch.updated` 推送。
- 里程碑 8（2 天）：完成前端三栏布局；接入 agent 列表、会话列表、消息面板、活动侧栏。
- 里程碑 9（1-2 天）：完成前端发送消息、连接状态、未读数刷新、最近消息展示。
- 里程碑 10（1-2 天）：完成断线重连、`sync.snapshot` 补拉、消息去重、顺序修正。
- 里程碑 11（1-2 天）：补关键测试；至少覆盖 adapter parser、BFF ingest、dispatch service、前端 realtime store。
- 里程碑 12（1 天）：输出部署说明、联调说明、M1 验收清单、演示路径。
- 总体开发顺序：先定 `packages/shared` 契约，再做 `apps/api` 数据与接口，再做 `apps/adapter` 采集接入，再做消息发送闭环，最后接 `apps/web` 与联调。
- M1 默认不做复杂权限系统；按内部单用户控制台处理。
- M1 默认不深改 Hermes 核心；坚持旁路 adapter 方案。
- M1 验收标准：页面能看到多个 agent 状态、查看最近消息、向单 agent 发消息，并实时收到状态/消息更新。
