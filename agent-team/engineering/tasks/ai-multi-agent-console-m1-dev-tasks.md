# AI 多Agent Web 控制台 M1 开发任务单

## 1) M1目标
- 建成可运行的 AI 多Agent Web 控制台 M1。
- 支持查看 agent 列表、在线状态、最近会话、消息历史。
- 支持向单个 agent 发消息，并看到发送结果。
- 支持通过 WebSocket 接收状态变更、消息新增、发送任务更新。
- 支持通过 Hermes console-adapter 采集脚本输出并落库。
- 支持本地联调与最小验收演示。

## 2) 开发任务分组
- 后端/API
- adapter
- 前端
- 实时层
- 联调

## 3) 每组任务项

### A. 后端/API

#### 任务 A1：建立 API 工程骨架
- 目标：初始化 NestJS BFF、模块目录、基础配置。
- 涉及目录：`apps/api/src`、`apps/api/prisma`、`packages/config`
- 前置依赖：monorepo 初始化完成。
- 完成标志：`apps/api` 可启动；模块骨架包含 agents/conversations/messages/dispatch/integrations/gateways。

#### 任务 A2：建立数据库模型与 migration
- 目标：落地 agents、conversations、messages、agent_events、dispatch_tasks、dispatch_task_targets 表。
- 涉及目录：`apps/api/prisma/schema.prisma`、`apps/api/prisma/migrations`
- 前置依赖：API 工程骨架完成。
- 完成标志：本地可执行 migration；数据库表成功创建。

#### 任务 A3：实现只读查询接口
- 目标：完成 `GET /api/agents`、`GET /api/agents/:agentId`、`GET /api/conversations`、`GET /api/conversations/:conversationId/messages`。
- 涉及目录：`apps/api/src/modules/agents`、`apps/api/src/modules/conversations`、`apps/api/src/modules/messages`
- 前置依赖：数据库模型完成。
- 完成标志：接口可返回真实数据；支持 cursor/limit 基础分页。

#### 任务 A4：实现消息发送与 dispatch 接口
- 目标：完成 `POST /api/messages`、`GET /api/dispatch-tasks/:taskId`。
- 涉及目录：`apps/api/src/modules/messages`、`apps/api/src/modules/dispatch`
- 前置依赖：adapter 发消息能力可调用。
- 完成标志：发送请求后生成 dispatch task；可查询任务状态与 per-agent 结果。

#### 任务 A5：实现 adapter ingest 接口
- 目标：完成 `POST /api/internal/adapter/events`、`POST /api/internal/adapter/agents/snapshot`。
- 涉及目录：`apps/api/src/modules/integrations`、`apps/api/src/modules/events`
- 前置依赖：共享事件契约已确定。
- 完成标志：adapter 可成功写入事件和状态快照；支持基础去重。

### B. adapter

#### 任务 B1：建立 adapter 工程骨架
- 目标：初始化 console-adapter 服务、配置、scheduler、provider 结构。
- 涉及目录：`apps/adapter/src`、`packages/shared`
- 前置依赖：monorepo 初始化完成。
- 完成标志：`apps/adapter` 可启动；具备独立配置与定时轮询入口。

#### 任务 B2：封装 Hermes 脚本 provider
- 目标：封装 `send-to-agent.sh`、`read-agent-output.sh`、`collect-team-output.sh` 调用。
- 涉及目录：`apps/adapter/src/providers`
- 前置依赖：adapter 工程骨架完成；脚本路径确认。
- 完成标志：provider 可返回标准调用结果；失败时返回结构化错误。

#### 任务 B3：实现 agent 状态采集
- 目标：采集 agent 在线态、session、最近活跃时间。
- 涉及目录：`apps/adapter/src/collectors/agent-status.collector.ts`、`apps/adapter/src/providers/tmux.provider.ts`
- 前置依赖：脚本 provider 或 tmux provider 可用。
- 完成标志：可生成 agent snapshot 并上报 API。

#### 任务 B4：实现输出采集与解析
- 目标：抓取 agent 输出增量并解析为 message/log/status 三类事件。
- 涉及目录：`apps/adapter/src/collectors/agent-output.collector.ts`、`apps/adapter/src/parsers/output.parser.ts`、`apps/adapter/src/parsers/event-mapper.ts`
- 前置依赖：脚本 provider 可用；事件契约确定。
- 完成标志：可输出标准事件；同一输出不会重复采集。

#### 任务 B5：实现事件上报与幂等标识
- 目标：把 snapshot/event 按标准格式推送给 BFF，并生成 `sourceId`。
- 涉及目录：`apps/adapter/src/publishers/bff-http.publisher.ts`
- 前置依赖：BFF ingest 接口可用。
- 完成标志：事件可批量上报；BFF 返回 accepted/deduplicated/failed 结果。

### C. 前端

#### 任务 C1：建立前端工程骨架
- 目标：初始化 Next.js 控制台、基础 layout、状态管理和 API client。
- 涉及目录：`apps/web/app`、`apps/web/lib`、`apps/web/features`
- 前置依赖：monorepo 初始化完成。
- 完成标志：`apps/web` 可启动；具备基础三栏空壳页面。

#### 任务 C2：实现 agent 列表与状态展示
- 目标：展示 agent 列表、在线状态、当前选中 agent。
- 涉及目录：`apps/web/features/agents`、`apps/web/components/agent-list`
- 前置依赖：`GET /api/agents` 可用。
- 完成标志：页面可显示真实 agent 数据；状态标签正常刷新。

#### 任务 C3：实现会话列表与消息区
- 目标：展示会话列表、消息历史、最近消息摘要。
- 涉及目录：`apps/web/features/conversations`、`apps/web/features/chat`、`apps/web/components/conversation-list`、`apps/web/components/chat-panel`
- 前置依赖：会话与消息查询接口可用。
- 完成标志：切换会话后可加载消息；支持基础分页/刷新。

#### 任务 C4：实现发送消息交互
- 目标：完成单 agent 发送消息、发送状态提示、失败提示。
- 涉及目录：`apps/web/features/chat/api.ts`、`apps/web/features/chat/store.ts`
- 前置依赖：`POST /api/messages` 可用。
- 完成标志：页面可成功发送消息；收到 dispatch 状态反馈。

#### 任务 C5：实现活动侧栏
- 目标：展示 agent 日志、状态变化、发送任务事件。
- 涉及目录：`apps/web/components/activity-panel`、`apps/web/features/realtime/event-reducer.ts`
- 前置依赖：WebSocket 事件可用。
- 完成标志：侧栏可显示 `agent.log.appended`、`agent.status.updated`、`dispatch.updated`。

### D. 实时层

#### 任务 D1：建立共享事件类型
- 目标：定义 API DTO、事件信封、payload 类型、枚举。
- 涉及目录：`packages/shared/src/api`、`packages/shared/src/events`、`packages/shared/src/schemas`
- 前置依赖：契约已确认。
- 完成标志：前后端和 adapter 均复用同一套类型定义。

#### 任务 D2：实现 WebSocket 网关
- 目标：建立服务端网关，支持客户端连接、订阅、推送。
- 涉及目录：`apps/api/src/gateways`
- 前置依赖：BFF 工程骨架完成。
- 完成标志：客户端可连接并接收服务端事件。

#### 任务 D3：实现事件广播链路
- 目标：adapter ingest 后触发 BFF 内部事件分发，并推送到前端。
- 涉及目录：`apps/api/src/modules/events`、`apps/api/src/gateways/console-events.service.ts`
- 前置依赖：adapter ingest 接口可用。
- 完成标志：`message.created`、`agent.status.updated`、`dispatch.updated` 可实时下发。

#### 任务 D4：实现前端 ws client 与本地状态同步
- 目标：接入 WebSocket、处理重连、事件去重、本地 store 更新。
- 涉及目录：`apps/web/features/realtime/ws-client.ts`、`apps/web/features/realtime/subscriptions.ts`、`apps/web/features/realtime/event-reducer.ts`
- 前置依赖：服务端网关可用；共享事件类型完成。
- 完成标志：断线后可重连；页面状态能随事件实时变化。

#### 任务 D5：实现 snapshot 补拉机制
- 目标：首次连接和重连时补全 agents/conversations 状态。
- 涉及目录：`apps/api/src/gateways`、`apps/web/features/realtime`
- 前置依赖：WebSocket 基础链路完成。
- 完成标志：重连后列表和消息状态可恢复；减少状态错乱。

### E. 联调

#### 任务 E1：完成本地依赖与环境整合
- 目标：统一 `.env`、docker compose、服务启动命令。
- 涉及目录：`infra/docker`、根目录 `.env.example`、根 `README.md`
- 前置依赖：三个应用骨架完成。
- 完成标志：一套命令可启动 Postgres、Redis、api、adapter、web。

#### 任务 E2：打通查询闭环
- 目标：从 adapter 采集状态/事件，到 BFF 落库，再到前端展示。
- 涉及目录：`apps/adapter`、`apps/api`、`apps/web`
- 前置依赖：查询接口、ingest 接口、前端列表页完成。
- 完成标志：页面能看到真实 agent 状态、会话和消息数据。

#### 任务 E3：打通发送闭环
- 目标：前端发送消息 → BFF → adapter → Hermes 脚本 → 状态回写 → 前端展示。
- 涉及目录：`apps/web/features/chat`、`apps/api/src/modules/messages`、`apps/api/src/modules/dispatch`、`apps/adapter/src/providers`
- 前置依赖：发送接口、dispatch 模块、脚本 provider 完成。
- 完成标志：单 agent 消息发送成功；可看到任务状态变化。

#### 任务 E4：处理核心稳定性问题
- 目标：修复消息重复、顺序错乱、状态闪烁、重连丢消息。
- 涉及目录：`apps/adapter/src/parsers`、`apps/api/src/modules/events`、`apps/web/features/realtime`
- 前置依赖：实时链路已打通。
- 完成标志：重复率可控；消息按 seq 正常展示；重连后状态恢复正常。

#### 任务 E5：补测试与验收文档
- 目标：补最小测试、启动说明、验收清单、演示脚本。
- 涉及目录：`apps/api/test`、`apps/adapter/test`、`apps/web` 测试目录、`engineering/docs`
- 前置依赖：主要功能联调通过。
- 完成标志：关键链路有测试；M1 演示路径明确；可交付验收。

## 4) 建议开发顺序
- 第 1 步：先初始化 monorepo、三应用骨架、共享包、docker 依赖。
- 第 2 步：先完成 `packages/shared` 的 DTO、事件类型、枚举、schema。
- 第 3 步：完成 API 工程骨架与 Prisma 数据模型。
- 第 4 步：完成只读查询接口，先打通 agents / conversations / messages 查询。
- 第 5 步：完成 adapter 脚本 provider、状态采集、输出采集、事件解析。
- 第 6 步：完成 ingest 接口与事件落库，打通 adapter → BFF 链路。
- 第 7 步：完成 WebSocket 网关与事件广播链路。
- 第 8 步：完成消息发送接口与 dispatch task 闭环。
- 第 9 步：完成前端三栏布局、列表页、消息区、活动侧栏。
- 第 10 步：接入前端 WebSocket、重连、snapshot、去重逻辑。
- 第 11 步：完成全链路联调，重点修消息顺序、重复、状态同步问题。
- 第 12 步：补测试、启动说明、验收清单，形成 M1 可交付包。

## 5) 每阶段产出物
- 阶段 1：monorepo 工程骨架、docker 依赖、环境变量模板。
- 阶段 2：Prisma schema、migration、数据库初始化结果。
- 阶段 3：agents/conversations/messages 查询接口与基础 DTO。
- 阶段 4：Hermes script provider、状态采集器、输出采集器、事件解析器。
- 阶段 5：adapter ingest 接口、事件落库、状态快照落库。
- 阶段 6：消息发送接口、dispatch task 状态链路。
- 阶段 7：WebSocket 网关、事件广播服务、snapshot 补拉机制。
- 阶段 8：前端三栏页面、agent 列表、会话列表、消息区、活动侧栏。
- 阶段 9：全链路联调结果、问题清单、修复记录。
- 阶段 10：测试用例、启动说明、验收清单、演示脚本。
