# AI 多Agent Web 控制台技术方案

## 技术架构
- 前端采用 React + Next.js App Router，提供单页控制台体验，支持多栏切换 agent、会话与详情面板。
- 后端采用 Node.js + NestJS/BFF，统一承接 WebSocket 推送、REST 查询、消息转发与权限校验。
- 实时层使用 WebSocket 作为主通道，向前端推送 agent 状态、日志流、聊天消息与任务事件。
- 数据层 MVP 使用 PostgreSQL 存会话/消息/agent 元数据，Redis 做在线状态、订阅缓存与短期事件缓冲。
- Hermes 侧通过“console-adapter”进程对接 tmux/脚本/API，把现有多 agent 运行态映射成可订阅事件流。

## 模块划分
- 前端控制台：Agent 列表、会话列表、聊天窗口、全局广播栏、状态/日志侧栏。
- 前端状态管理：统一维护当前选中 agent、当前会话、未读数、在线态与跨 agent 跳转历史。
- 后端 API/BFF：提供 agent 列表、会话查询、消息发送、历史分页、搜索与权限校验接口。
- 后端实时网关：聚合 Hermes 事件并广播到订阅前端，负责断线重连、增量同步与心跳。
- 集成适配层：封装 Hermes profile、agent 进程发现、消息注入、日志采集、会话归档。
- 存储与审计层：保存消息、状态快照、操作记录，支持追溯“谁给哪个 agent 发了什么”。

## 数据模型与关键对象
- Agent：id、name、role、profile、status、current_session_id、last_seen_at、capabilities。
- Conversation：id、scope(单 agent/广播)、title、participants、source、created_at、last_message_at。
- Message：id、conversation_id、sender_type(user/agent/system)、sender_id、content、format、created_at、seq。
- AgentEvent：id、agent_id、event_type(status/log/task/message)、payload、occurred_at，用于实时推送与回放。
- DispatchTask：id、target_scope、target_ids、command_type、input_text、status、result_ref、created_by。
- JumpLink/ViewState：记录“从 agent A 跳到 agent B 的上下文入口”，保证控制台导航可回溯。

## Hermes集成思路
- 首期不改 Hermes 核心执行链，优先在外部增加 adapter，读取现有 tmux/script 输出并转成标准事件。
- 发送消息优先复用 `send-to-agent.sh` / `ask-agent.sh`，避免 MVP 阶段重写 agent 调度逻辑。
- 读取状态优先复用 `read-agent-output.sh` / `collect-team-output.sh`，再补充 agent 心跳与 session 元数据采集。
- profile 信息从 `~/.hermes/profiles/<name>` 与团队工作区配置中抽取，映射到 Agent.capabilities / role 描述。
- 会话归档采用“控制台侧持久化副本”策略：Hermes 原始输出保留，Web 控制台维护可检索索引与结构化消息表。
- 后续可逐步把 adapter 从脚本轮询升级为原生事件总线，但 MVP 先保证兼容现有团队运行方式。

## 阶段计划M1-M3
- M1：完成 agent 列表、在线状态、单 agent 消息发送、最近输出查看；以可用为先，不做复杂权限。
- M1：打通 Hermes adapter、Postgres 落库、WebSocket 推送、基础聊天 UI，支持单窗口查看多个 agent。
- M2：增加会话列表、历史消息分页、跨 agent 跳转、广播发送、未读计数与关键词搜索。
- M2：补齐操作审计、失败重试、断线重连、状态快照，提升控制台稳定性与可追溯性。
- M3：增加任务视图、agent 分组、过滤器、指标面板、简单权限模型，支持团队协作场景。
- M3：视 Hermes 演进情况，收敛 adapter 协议，逐步从脚本采集迁移到更稳定的原生集成接口。

## 技术风险与规避
- 风险：Hermes 当前以脚本/tmux 为主，事件语义不稳定。规避：先定义 adapter 标准事件模型，脚本输出做解析隔离。
- 风险：消息顺序与去重困难。规避：为消息和事件引入 seq/source_id/ingest_time，前后端统一幂等处理。
- 风险：实时连接多时前端状态容易错乱。规避：采用“快照 + 增量事件”同步模型，并提供重连后的全量补拉。
- 风险：广播到多个 agent 时失败不一致。规避：引入 DispatchTask 与 per-agent result，明确部分成功/失败状态。
- 风险：聊天记录可能包含敏感内容。规避：MVP 即加入本地部署、最小权限、操作审计与可配置数据保留策略。
- 风险：如果直接侵入 Hermes 核心，改动成本高。规避：MVP 严格走旁路适配，先验证控制台价值再决定是否深度内嵌。
