# Hermes Kanban 改造方案

本文档说明如何借助 Hermes Kanban，把当前项目改造成“Leader Agent 接收任务、拆解任务、分派给多个 Worker、等待执行、最后汇总结果”的长期运行型多 Agent 协作系统。

## 1. 目标

当前项目已经有 Leader / Worker、多 Agent 注册、MCP 工具、ACP 会话池、消息和事件展示能力。下一步目标是把“任务调度、持久化、长时间运行、失败恢复”交给 Hermes Kanban。

最终形态：

```text
用户提交任务
  ↓
创建 Kanban 父任务，分配给 leader profile
  ↓
leader 分析任务并创建多个 Kanban 子任务
  ↓
Kanban dispatcher/gateway 分派子任务给 worker profiles
  ↓
worker 执行并写入结果
  ↓
所有子任务完成后，leader 汇总
  ↓
Web UI 展示全过程和最终结果
```

## 2. Hermes Kanban 原理

### 2.1 通俗理解

Hermes Kanban 可以理解成一个“带自动派工能力的任务看板”。

它不是简单的 UI 看板，而是一个持久化任务队列：

- 每张卡片是一项任务。
- 每个任务有状态，例如 `triage`、`todo`、`ready`、`running`、`done`、`blocked`。
- 每个任务可以指定负责人，也就是 Hermes profile。
- Dispatcher 会定期扫描可执行任务，把任务交给对应 profile 执行。
- Worker 执行过程、日志、结果都会被记录下来。
- 任务之间可以建立依赖关系，子任务会等待父任务完成。

所以它很适合做多 Agent 协作中的“任务中枢”。

### 2.2 核心概念

| 概念 | 通俗解释 | 在本项目中的意义 |
| --- | --- | --- |
| Board | 一个独立看板 | 一个项目、一个工作流或一个团队任务空间 |
| Task | 一张任务卡 | 用户任务、leader 汇总任务、worker 子任务 |
| Assignee | 任务负责人 | Hermes profile，例如 `leader`、`dev`、`tester` |
| Profile | 可运行的 Agent 身份 | 项目里的 Agent 运行实例 |
| Dispatcher | 派工员 | 扫描任务并启动对应 worker |
| Gateway | 长时间运行的后台服务 | 持续驱动 dispatcher，不依赖 Web 请求生命周期 |
| Dependency | 任务依赖 | 汇总任务等待所有 worker 子任务完成 |
| Result / Summary | 任务结果 | worker 输出和 leader 最终汇总 |
| Log / Runs | 执行日志和尝试记录 | UI 调试、失败排查、任务审计 |

### 2.3 任务状态

常见状态如下：

| 状态 | 含义 | 是否会执行 |
| --- | --- | --- |
| `triage` | 原始想法，等待细化 | 通常不会直接执行 |
| `todo` | 等待依赖或等待分配 | 不一定执行 |
| `ready` | 已准备好，等待 dispatcher 派发 | 会被执行 |
| `running` | worker 正在执行 | 正在执行 |
| `blocked` | 被阻塞，需要人工或外部输入 | 不会执行 |
| `done` | 已完成 | 不会再执行 |
| `archived` | 已归档 | 默认隐藏 |

一个任务要真正跑起来，一般要满足：

```text
有 assignee
依赖已完成
状态进入 ready
gateway/dispatcher 正在运行
对应 profile 可用
```

### 2.4 Profile 和 Worker 的关系

Kanban 的 worker 不是项目里单独发明的概念，本质上就是 Hermes profile。

例如：

```bash
hermes profile list
```

输出里可能有：

```text
leader
dev
tester
writer
```

那么创建任务时：

```bash
hermes kanban create "实现登录接口" --assignee dev
```

意思就是：这张任务卡交给 `dev` 这个 Hermes profile 执行。

### 2.5 Dispatcher / Gateway 的作用

Dispatcher 像“派工员”，它做几件事：

1. 找到已经 ready 的任务。
2. 判断任务有没有 assignee。
3. 启动对应 profile 的 worker。
4. 把任务上下文交给 worker。
5. 记录运行日志和结果。
6. 处理超时、失败、重试、阻塞等情况。

手动触发一次：

```bash
hermes kanban dispatch
```

长期运行推荐使用 gateway：

```bash
hermes gateway start
```

在长期任务场景下，应该依赖 gateway 持续运行，而不是依赖 Web 请求线程。

## 3. 当前项目现状

当前项目已经具备一部分多 Agent 编排能力。

### 3.1 已有能力

| 已有模块 | 作用 |
| --- | --- |
| Agent Registry | 维护 leader / worker 列表 |
| Hermes Profile | 每个 agent 对应一个 profile |
| MCP Server | 给 leader 暴露团队协作工具 |
| ACP Pool | 启动并维护 Hermes 会话 |
| UserTask | 用户提交的顶层任务 |
| Delegation | leader 创建的一批分发任务 |
| Assignment | 分配给某个 worker 的子任务 |
| Event Store | 前端实时展示状态变化 |
| Dashboard | 展示 agent、消息、事件和运行状态 |

### 3.2 当前问题

当前项目的问题不是“没有 leader/worker 概念”，而是调度层偏自研：

- Worker 执行依赖 ACP session 是否在线。
- 长时间任务容易受 Web 进程、线程、会话状态影响。
- 失败恢复、重试、日志、运行记录需要自己维护。
- 任务状态和 Kanban 状态是两套系统，容易重复。
- 项目已有 `UserTask / Delegation / Assignment`，但缺少成熟的持久化派工引擎。

### 3.3 改造原则

不建议推翻当前项目。推荐方式是：

```text
当前项目负责：Web UI、Agent 管理、用户入口、事件展示、Kanban 状态同步
Hermes Kanban 负责：任务队列、状态机、依赖关系、长时间调度、worker 执行日志
```

也就是：当前项目从“自研调度器”转为“Kanban 的可视化控制台 + Leader 工作台”。

## 4. 目标架构

### 4.1 新架构图

```text
┌─────────────────────────────────────────────┐
│                 Web UI                      │
│  提交任务 / 查看看板 / 查看日志 / 最终结果     │
└─────────────────────┬───────────────────────┘
                      │ HTTP / SSE
┌─────────────────────▼───────────────────────┐
│              Flask Backend                  │
│                                             │
│  Agent Registry                             │
│  KanbanService                              │
│  Kanban Sync Worker                         │
│  Event Store                                │
│  MCP Server                                 │
└──────────────┬────────────────────┬─────────┘
               │                    │
               │ hermes kanban CLI  │ MCP tools
               │                    │
┌──────────────▼────────────────────▼─────────┐
│             Hermes Kanban                   │
│  boards / tasks / dependencies / logs / runs │
└─────────────────────┬───────────────────────┘
                      │ dispatcher / gateway
┌─────────────────────▼───────────────────────┐
│             Hermes Profiles                 │
│  leader / dev / tester / writer / reviewer   │
└─────────────────────────────────────────────┘
```

### 4.2 数据流

#### 用户提交任务

```text
Web UI
  → Flask API
  → KanbanService.create_task(..., assignee="leader")
  → Kanban 父任务 created
  → gateway 调度 leader
```

#### Leader 拆解任务

```text
leader profile
  → 调用 MCP 工具 create_worker_tasks
  → Flask MCP Server
  → KanbanService 创建多个子任务
  → 每个子任务 assignee 不同 worker
```

#### Worker 执行任务

```text
Kanban dispatcher
  → 找到 ready worker 子任务
  → 启动 assignee profile
  → worker 执行
  → Kanban 记录 result / summary / log / run
```

#### Leader 汇总结果

```text
Kanban Sync Worker
  → 发现所有 worker 子任务 done
  → 创建 leader 汇总任务，依赖所有子任务
  → gateway 调度 leader
  → leader 读取 worker summaries
  → 输出最终结果
```

## 5. 核心映射关系

### 5.1 项目模型到 Kanban

| 当前项目模型 | Kanban 模型 | 说明 |
| --- | --- | --- |
| `AgentRecord` | Hermes profile / assignee | profile_name 用作 assignee |
| `UserTaskRecord` | 父任务 | 用户原始任务 |
| `DelegationRecord` | 子任务批次或任务分组 | 可逐步弱化，使用 Kanban parent/dependency 替代 |
| `AssignmentRecord` | worker 子任务 | 每个 assignment 变成一张 Kanban task |
| `MessageRecord` | task comment / event | 可保留用于 UI，也可同步 Kanban events |
| `EventRecord` | task events / logs | 前端事件投影 |

### 5.2 状态映射

| 当前状态 | Kanban 状态 | 说明 |
| --- | --- | --- |
| `running` | `running` | 正在执行 |
| `waiting_workers` | `todo` / 等依赖 | 等待子任务完成 |
| `ready_to_summarize` | 汇总任务 `ready` | 子任务全部完成后触发 leader |
| `summarizing` | `running` | leader 正在汇总 |
| `completed` | `done` | 完成 |
| `failed` | `blocked` 或 run failed | 失败或阻塞 |

### 5.3 Agent 到 Profile

| 项目字段 | Kanban 使用方式 |
| --- | --- |
| `agent_id` | UI 内部 ID |
| `profile_name` | Kanban `--assignee` |
| `role=leader` | 接收用户父任务和汇总任务 |
| `role=worker` | 接收 worker 子任务 |
| `description` | leader 选择 worker 时的能力说明 |

## 6. 关键设计

### 6.1 KanbanService

新增服务层，集中封装 Hermes Kanban 命令。

建议文件：

```text
app/services/kanban.py
```

职责：

- 创建 board。
- 切换或指定 board。
- 创建任务。
- 查询任务列表。
- 查询任务详情。
- 查询日志和 runs。
- 归档任务。
- 触发 dispatch。
- 解析 JSON 输出。
- 统一错误处理。

建议接口：

```python
create_task(title, body, assignee, parent=None, workspace="scratch", skills=None)
list_tasks(status=None, assignee=None, archived=False)
show_task(task_id)
complete_task(task_id, result, summary=None, metadata=None)
archive_task(task_id)
dispatch_once(max_workers=None)
```

实现上先用 `subprocess.run(["hermes", "kanban", ...])`，后续如果 Hermes 提供 Python API 再替换。

### 6.2 Board 策略

推荐每个项目使用一个 board。

默认 board：

```text
hermes-agents-team
```

启动时确保存在：

```bash
hermes kanban boards create hermes-agents-team --name "Hermes Agents Team" --switch
```

也可以不切全局 board，而是所有命令都显式传：

```bash
hermes kanban --board hermes-agents-team list
```

推荐后者，避免影响用户其他 Hermes 工作流。

### 6.3 用户任务创建

用户从 Web UI 提交任务时，不再只写入本项目数据库，而是创建 Kanban 父任务。

示例：

```bash
hermes kanban --board hermes-agents-team create \
  "用户任务：实现登录功能" \
  --body "用户原始需求..." \
  --assignee leader \
  --workspace scratch \
  --json
```

注意：不要使用 `--triage`，否则任务停在 triage，不会直接执行。

### 6.4 Leader 拆解工具

当前 MCP 工具有 `dispatch_parallel`，未来可改成 Kanban 版本。

建议新增工具：

```text
mcp_agent_bus_create_kanban_tasks
```

输入：

```json
{
  "from_agent_id": "agent_leader",
  "parent_task_id": "t_xxx",
  "assignments": [
    {
      "to_agent_id": "agent_dev",
      "title": "实现登录接口",
      "content": "具体要求...",
      "priority": 10
    },
    {
      "to_agent_id": "agent_tester",
      "title": "补充登录测试",
      "content": "具体要求...",
      "priority": 5
    }
  ],
  "summary_instruction": "所有 worker 完成后，请给用户输出最终交付说明。"
}
```

工具内部逻辑：

1. 校验 from_agent_id 是 leader。
2. 根据 to_agent_id 找到 worker 的 profile_name。
3. 为每个 assignment 创建 Kanban 子任务。
4. 子任务 `--assignee <worker_profile>`。
5. 子任务 `--parent <parent_task_id>` 或写入 metadata 关联。
6. 保存本地映射关系。
7. 返回已创建的 task_id 列表。

### 6.5 汇总任务设计

有两种方案。

#### 方案 A：平台创建汇总任务

平台 watcher 发现所有 worker 子任务完成后，自动创建 leader 汇总任务。

优点：

- 可控性强。
- 不依赖 leader 自己记住什么时候汇总。
- UI 容易展示“汇总中”。

缺点：

- 需要实现 watcher。

推荐使用方案 A。

#### 方案 B：让 leader 自己通过依赖关系等待

leader 创建一个汇总任务，并让它依赖所有 worker 子任务。

优点：

- 更 Kanban 原生。

缺点：

- 需要 leader 在拆解时一次性规划汇总任务。
- 如果后续动态追加子任务，处理复杂。

### 6.6 Kanban Sync Worker

当前项目需要一个后台同步器，把 Kanban 状态同步回本项目 UI。

建议职责：

- 定期执行 `hermes kanban list --json`。
- 对比本地记录，发现状态变化。
- 把变化写入 `EventRecord`。
- 同步任务结果、日志入口和运行记录。
- 检查是否所有 worker 子任务完成。
- 必要时创建 leader 汇总任务。

建议启动方式：

- 开发环境：随 Flask 启动一个 daemon thread。
- 生产环境：独立进程或 systemd/launchd 服务。

轮询间隔建议：

```text
2-5 秒：开发调试
10-30 秒：普通使用
60 秒：低频后台任务
```

### 6.7 长时间运行

长时间运行不建议依赖 Flask 请求线程，也不建议依赖当前 ACP session 常驻。

推荐依赖：

```bash
hermes gateway start
```

项目只做三件事：

1. 创建任务。
2. 查询和同步任务状态。
3. 展示日志和结果。

这样即使 Web UI 刷新、Flask 重启，只要 Kanban DB 和 gateway 还在，任务状态仍然存在。

## 7. 实施计划

### 阶段 0：确认前置条件

目标：确认 Hermes Kanban 在本机可用。

检查项：

```bash
hermes profile list
hermes kanban boards list
hermes gateway status
hermes kanban create "测试任务" --assignee default --json
hermes kanban dispatch
```

验收标准：

- 能创建任务。
- 能分配给 profile。
- 任务能进入执行并完成。
- 能查看 log 和 runs。

### 阶段 1：新增 Kanban 文档和适配层

目标：不影响现有流程，只增加 Kanban 封装能力。

改动：

- 新增 `app/services/kanban.py`。
- 新增配置项：
  - `KANBAN_BOARD`
  - `KANBAN_ENABLED`
  - `KANBAN_POLL_INTERVAL`
- 增加单元测试，mock `subprocess.run`。

验收标准：

- 可以通过 Python 服务创建 Kanban 任务。
- CLI 错误能被转换为明确异常。
- 现有测试不受影响。

### 阶段 2：Web UI 接入 Kanban 任务创建

目标：用户提交任务时，同时创建 Kanban 父任务。

改动：

- 修改用户任务入口。
- 保存 `user_task_id ↔ kanban_task_id` 映射。
- 页面展示 Kanban task id 和状态。

验收标准：

- Web UI 提交任务后，Kanban 看板出现父任务。
- 父任务 assignee 是 leader profile。
- 不影响现有 leader/worker 流程。

### 阶段 3：Leader 通过 MCP 创建 Kanban 子任务

目标：leader 拆解任务后，不再直接 prompt worker，而是创建 Kanban 子任务。

改动：

- 新增 MCP 工具 `create_kanban_worker_tasks`。
- 或扩展现有 `dispatch_parallel`，增加 `backend="kanban"`。
- 将 `to_agent_id` 映射为 worker `profile_name`。
- 创建 worker 子任务并记录映射。

验收标准：

- leader 能调用工具创建多个 Kanban 子任务。
- 子任务正确分配给不同 worker profile。
- Kanban dashboard 能看到子任务流转。

### 阶段 4：同步 Kanban 状态到项目 UI

目标：当前 Web UI 能展示 Kanban 任务状态。

改动：

- 新增 `KanbanSyncWorker`。
- 定期拉取 task list。
- 更新本地任务状态。
- 生成前端事件。
- 支持查看 task log / runs。

验收标准：

- Kanban 状态变化能在项目 UI 中看到。
- Worker 完成后，UI 能展示结果摘要。
- 失败、阻塞、超时能显示明确状态。

### 阶段 5：自动触发 Leader 汇总

目标：所有 worker 子任务完成后，自动让 leader 汇总。

改动：

- SyncWorker 检测子任务全部 done。
- 创建 leader 汇总任务。
- 汇总任务 body 包含所有 worker result / summary。
- 汇总任务 assignee 为 leader profile。

验收标准：

- 多个 worker 完成后自动创建汇总任务。
- leader 输出最终总结。
- 用户任务状态变为 completed。

### 阶段 6：逐步替换旧 ACP 调度

目标：让 Kanban 成为主调度层。

改动：

- 默认使用 Kanban backend。
- 保留 ACP backend 作为兼容模式。
- 删除或弱化重复状态字段。
- 文档说明两种模式差异。

验收标准：

- 长任务不依赖 Web 请求生命周期。
- Flask 重启后任务仍可恢复展示。
- 旧功能可通过配置回退。

## 8. 风险与注意事项

### 8.1 不要把 triage 当作可执行任务

`triage` 适合“先让 specifier 细化需求”的场景。如果用户任务要 leader 立即处理，不要加 `--triage`。

### 8.2 assignee 必须是 profile 名

Kanban 执行任务依赖 assignee。

项目里的 `agent_id` 不能直接作为 assignee，必须映射到 `profile_name`。

### 8.3 不要依赖全局当前 board

推荐所有命令都显式传：

```bash
hermes kanban --board hermes-agents-team ...
```

避免影响用户其他看板。

### 8.4 注意并发和重复创建

创建任务时建议使用 `--idempotency-key`。

例如：

```text
user_task:<user_task_id>
assignment:<assignment_id>
summary:<user_task_id>
```

这样 Flask 重试或重启后不会创建重复任务。

### 8.5 Watcher 要幂等

Kanban Sync Worker 必须可以重复运行。

同一个状态变化不能重复创建汇总任务，也不能重复标记 completed。

### 8.6 保留本地事件表

即使 Kanban 有 events/logs，本项目仍建议保留 `EventRecord`。

原因：

- 前端 SSE 已经依赖本地事件。
- 可以统一展示 agent 创建、MCP 配置、skill 安装等非 Kanban 事件。
- 可以把 Kanban 事件转成前端友好的事件格式。

## 9. 推荐新增配置

```bash
KANBAN_ENABLED=1
KANBAN_BOARD=hermes-agents-team
KANBAN_POLL_INTERVAL=5
KANBAN_DEFAULT_WORKSPACE=scratch
KANBAN_AUTO_DISPATCH=0
```

说明：

| 配置 | 功能 |
| --- | --- |
| `KANBAN_ENABLED` | 是否启用 Kanban backend。 |
| `KANBAN_BOARD` | 当前项目使用的 board slug。 |
| `KANBAN_POLL_INTERVAL` | 同步轮询间隔。 |
| `KANBAN_DEFAULT_WORKSPACE` | 默认 workspace 类型。 |
| `KANBAN_AUTO_DISPATCH` | 是否由项目主动调用 dispatch；长期运行推荐交给 gateway。 |

## 10. 建议新增文件

```text
app/services/kanban.py              # Kanban CLI 适配层
app/services/kanban_sync.py         # Kanban 状态同步器
app/models/store/kanban_tasks.py    # 本地映射关系，可选
app/controllers/kanban.py           # Kanban 查询 API，可选
tests/test_kanban_service.py        # KanbanService 单测
tests/test_kanban_sync.py           # 状态同步单测
```

如果希望少改数据库，第一版可以把映射关系放入现有 `UserTaskRecord`、`AssignmentRecord` 的新增字段中。

建议新增字段：

```text
UserTaskRecord.kanban_task_id
AssignmentRecord.kanban_task_id
DelegationRecord.kanban_summary_task_id
```

## 11. 推荐第一版最小闭环

第一版不追求全量替换，只做最小可用闭环：

1. Web UI 提交任务。
2. 创建 Kanban 父任务给 leader。
3. leader 通过 MCP 创建两个 worker 子任务。
4. gateway 执行 worker 子任务。
5. watcher 发现 worker 全部完成。
6. watcher 创建 leader 汇总任务。
7. leader 完成汇总。
8. UI 展示最终结果。

这个闭环跑通后，再逐步替换旧的 ACP prompt 分发逻辑。

## 12. 总结

Kanban 非常适合作为本项目的长期任务调度层。

推荐定位：

```text
Hermes Kanban = 持久化任务队列 + 派工系统 + 日志系统
Hermes Agents Team = 多 Agent Dashboard + Leader 工作台 + 状态可视化层
```

这样改造后，系统会更稳定、更容易恢复、更适合长时间运行，也更接近真实的 Leader / Worker 多 Agent 协作模式。
