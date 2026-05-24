# Hermes Kanban 集成说明

本文档说明当前项目如何借助 Hermes Kanban 实现 Leader / Worker 多 Agent 协作和长时间任务执行。

## 1. 当前架构

当前任务主路径已经交给 Hermes Kanban：

```text
用户提交任务
  -> Flask Backend 创建 user_task
  -> 创建 leader 父 Kanban 任务
  -> leader 通过 MCP 创建 worker Kanban 子任务
  -> Kanban dispatch/gateway 执行 worker profile
  -> Kanban Sync Worker 同步结果
  -> 平台创建 leader review 任务
  -> leader 完成、继续下一轮或阻塞
  -> Web UI 展示全过程和最终结果
```

项目定位：

```text
Hermes Kanban = 持久化任务队列 + 派工系统 + 日志系统
Hermes Agents Team = 多 Agent Dashboard + Profile/Skills/MCP 管理台 + Kanban 状态可视化层
```

## 2. 核心概念映射

| 项目模型 | Kanban 模型 | 说明 |
| --- | --- | --- |
| `AgentRecord` | Hermes profile / assignee | `profile_name` 用作 Kanban assignee |
| `UserTaskRecord` | 父任务 | 用户提交的顶层目标 |
| `DelegationRecord` | 一轮 worker 分发批次 | 记录本地批次、轮次和 review 状态 |
| `AssignmentRecord` | worker 子任务 | 每个 assignment 对应一张 worker Kanban task |
| `kanban_task_links` | 本地映射表 | 关联本地对象和 Kanban task |
| `EventRecord` | UI 事件投影 | 前端 SSE 和状态展示使用 |

Kanban task 角色：

| `kanban_role` | 含义 |
| --- | --- |
| `parent` | leader 初始规划任务 |
| `worker` | 分配给 worker profile 的子任务 |
| `review` | 当前轮 worker 完成后的 leader checkpoint 任务 |
| `summary` | 旧命名兼容，当前按 review 语义处理 |

## 3. 关键文件

| 文件 | 作用 |
| --- | --- |
| `argos/services/kanban.py` | Hermes Kanban CLI 适配层 |
| `argos/services/kanban_sync.py` | Kanban 状态同步和 review 任务创建 |
| `argos/services/kanban_dispatch.py` | 项目内 Kanban dispatch worker |
| `argos/controllers/kanban.py` | Kanban 查询、归档、unblock、dispatch、设置 API |
| `argos/models/store/kanban.py` | 本地 Kanban task link 存储 |
| `argos/mcp_server.py` | Leader 可调用的团队协作 MCP 工具 |

## 4. KanbanService

`argos/services/kanban.py` 当前通过 `subprocess` 调用 Hermes CLI，并统一加上 `--board <KANBAN_BOARD>`。

已封装能力：

- `ensure_board()`
- `reset_board()`
- `create_task(...)`
- `list_tasks(...)`
- `show_task(task_id)`
- `runs(task_id)`
- `log(task_id, tail=None)`
- `context(task_id)`
- `complete_task(task_id, result, summary=None, metadata=None)`
- `dispatch_once(max_workers=None)`
- `dispatch_one(task_id, assignee=...)`
- `assign_task(task_id, profile)`
- `unblock_task(task_id)`
- `archive_task(task_id)`
- `archive_tasks(task_ids)`

默认 board：

```text
KANBAN_BOARD=argos
```

默认 workspace：

```text
KANBAN_DEFAULT_WORKSPACE=scratch
```

## 5. 用户任务与 Worker 子任务

用户提交任务后，`argos/services/messages.py` 会创建：

1. 本地 `user_task`。
2. 分配给 leader profile 的父 Kanban task。
3. 本地 `kanban_task_links` 记录。

Leader 拆解任务时调用：

```text
mcp_agent_bus_create_kanban_worker_tasks
```

该工具会：

1. 校验调用者是 `role=leader`。
2. 校验目标 worker 可派发。
3. 创建本地 `delegation` 和 `assignment`。
4. 为每个 assignment 创建 worker Kanban task，assignee 使用 worker 的 `profile_name`。
5. 写入 `kanban_task_links`。
6. 完成父任务或当前 review 任务。
7. 在自动派发开启时触发 dispatch worker。

## 6. Review / Checkpoint

`KanbanSyncWorker` 会轮询并同步 Kanban 状态：

1. worker task 完成后，结果写回对应 assignment。
2. 当前轮所有 assignment 完成后，用户任务进入 `ready_to_review`。
3. 同步器创建 `kanban_role="review"` 的 leader review task。
4. leader review task 完成后：
   - 若已创建下一轮 delegation，则当前轮标记为 `reviewed`，任务继续执行；
   - 若没有下一轮 delegation，则用户任务标记为 `completed`；
   - 若 review task 进入失败类状态，则用户任务标记为 `blocked`。

review task 使用按轮次的 idempotency key：

```text
review:<user_task_id>:round:<current_round>
```

## 7. Dispatch

项目内有 `KanbanDispatchWorker`：

- 后台循环只有在 `auto_dispatch_enabled=true` 时执行。
- 每个 tick 至多释放一个 `pending_dispatch` 任务。
- 有本地可派发任务时才调用 `hermes kanban dispatch`。
- `/api/kanban/dispatch` 和任务创建路径复用同一把锁，避免并发派发。
- `/api/kanban/tasks/<task_id>/dispatch` 可手动派发单个 pending/ready 任务。

相关设置 API：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/kanban/settings` | 读取自动派发设置 |
| PUT | `/api/kanban/settings` | 设置 `auto_dispatch_enabled` |
| POST | `/api/kanban/dispatch` | 手动触发一次 dispatch |
| POST | `/api/kanban/tasks/<task_id>/dispatch` | 手动派发单个任务 |

## 8. Kanban API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/kanban/tasks` | 返回本地可见 Kanban links，并异步触发一次同步 |
| GET | `/api/kanban/tasks/<task_id>/runs` | 查看 Kanban runs |
| GET | `/api/kanban/tasks/<task_id>/log` | 查看任务日志 |
| GET | `/api/kanban/tasks/<task_id>/details` | 查看 task / runs / context / log |
| POST | `/api/kanban/tasks/<task_id>/unblock` | unblock 任务并触发同步和派发 |
| POST | `/api/kanban/tasks/<task_id>/answer` | 回答人工输入任务 |
| DELETE | `/api/kanban/tasks/<task_id>` | 归档单个任务 |
| DELETE | `/api/kanban/tasks/done` | 归档 done 列 |
| DELETE | `/api/kanban/tasks/column/<column_key>` | 归档指定列 |

UI 列映射：

| 列 | 状态 |
| --- | --- |
| `ready` | `pending_dispatch`、`ready`、`todo`、`triage` |
| `running` | `running` |
| `blocked` | `blocked`、`failed`、`crashed`、`timed_out`、`gave_up` |
| `done` | `done` |

## 9. 配置

| 配置 | 默认值 | 功能 |
| --- | --- | --- |
| `KANBAN_BOARD` | `argos` | 当前项目使用的 board slug |
| `KANBAN_POLL_INTERVAL` | `2` | 同步轮询间隔，单位秒 |
| `KANBAN_DEFAULT_WORKSPACE` | `scratch` | 创建 Kanban task 的默认 workspace |
| `KANBAN_AUTO_DISPATCH` | `0` | 初始自动派发开关 |

`KANBAN_AUTO_DISPATCH` 只决定启动时默认值；运行中可通过 `/api/kanban/settings` 修改。

## 10. 注意事项

- Kanban assignee 必须使用 Hermes `profile_name`，不能直接使用项目内 `agent_id`。
- 项目命令显式传 `--board <KANBAN_BOARD>`，避免依赖用户全局当前 board。
- Worker 子任务必须通过项目 MCP 工具创建，不能用通用 Kanban 命令绕过本地映射表。
- Sync worker 必须幂等；同一轮 review task 和同一批 worker task 都按 idempotency key / 本地 link 去重。
- 本地 `EventRecord` 仍保留，用于统一展示 Kanban、agent、MCP、skills 等不同类型事件。
