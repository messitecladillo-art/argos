# 长时任务 MVP 实现说明

本文档说明当前长时任务 MVP 的实际实现。早期“一轮拆分 + 一轮汇总”的流程已经改为 Kanban 驱动的多轮 review/checkpoint 流程。

## 1. 当前结论

当前主流程：

```text
用户提交任务
  -> 创建 user_task
  -> 创建 leader 父 Kanban 任务
  -> leader 调用 MCP 创建 worker Kanban 子任务
  -> worker 由 Kanban gateway/dispatch 执行
  -> Kanban sync 同步 worker 结果
  -> 当前轮 worker 全部结束后创建 leader review 任务
  -> leader 选择完成、继续下一轮或阻塞
```

review 任务不是简单“汇总任务”，而是 checkpoint：

- 目标已完成：leader 调用 `kanban_complete(summary=最终答复)`，用户任务完成。
- 目标未完成且未达到最大轮次：leader 调用 `mcp_agent_bus_create_kanban_worker_tasks` 创建下一轮 worker，然后完成当前 review 任务。
- 无法继续或达到最大轮次：leader 完成 review 任务并输出当前最佳结果和原因；如果 review Kanban 任务进入失败类状态，平台会把用户任务标记为 `blocked`。

默认最大轮次为 `DEFAULT_MAX_TASK_ROUNDS = 10`。

## 2. 状态机

当前 `user_task` 主要状态：

| 状态 | 含义 |
| --- | --- |
| `running` | 用户任务刚创建，等待 leader 初始规划 |
| `waiting_workers` | 当前轮 worker 子任务执行中 |
| `ready_to_review` | 当前轮 worker 已全部结束，等待创建 leader review 任务 |
| `reviewing` | leader 正在 review 当前轮结果 |
| `completed` | 用户任务完成 |
| `blocked` | 用户任务被阻塞或 review 任务失败 |

当前 `delegation` 主要状态：

| 状态 | 含义 |
| --- | --- |
| `waiting_workers` | 本轮 worker 执行中 |
| `ready_to_review` | 本轮 worker 已全部结束 |
| `reviewing` | 本轮结果进入 leader review |
| `reviewed` | 本轮 review 已结束 |

兼容说明：代码仍保留 `ready_to_summarize`、`summarizing`、`summarized` 等旧命名的读取和包装函数，用于兼容历史数据和旧测试语义；新流程内部按 review/checkpoint 理解。

## 3. 关键代码路径

| 文件 | 作用 |
| --- | --- |
| `argos/services/messages.py` | `send_user_task(...)` 创建用户任务和 leader 父 Kanban 任务 |
| `argos/mcp_server.py` | 暴露 `create_kanban_worker_tasks(...)` 等 MCP 工具 |
| `argos/services/kanban_sync.py` | 同步 Kanban 状态，创建 review 任务，投影完成/阻塞状态 |
| `argos/services/kanban_dispatch.py` | 项目内 Kanban dispatch worker |
| `argos/models/store/user_tasks.py` | 用户任务状态、轮次和阻塞状态 |
| `argos/models/store/delegations.py` | delegation / assignment 状态 |
| `argos/models/store/kanban.py` | 本地对象与 Kanban task 的映射 |
| `argos/db/migrations.py` | SQLite 轻量字段补齐 |

## 4. 用户任务创建

入口：`argos/services/messages.py::send_user_task(...)`

当前行为：

1. 创建 `UserTaskRecord`，初始状态为 `running`。
2. 创建 leader 父 Kanban 任务，`kanban_role="parent"`。
3. 父任务初始状态为 `pending_dispatch`，随后触发 `dispatch_worker.trigger_async()`。
4. leader prompt 会要求使用 MCP 工具创建 worker 子任务，并在 review 阶段传递 `user_task_id` 和当前 review task id。

## 5. Worker 子任务创建

入口：`argos/mcp_server.py::create_kanban_worker_tasks(...)`

当前行为：

1. 校验 `from_agent_id` 必须是 leader。
2. 解析或推断当前 active `user_task_id`。
3. 如果当前用户任务处于 `ready_to_review` / `reviewing`，本次派发视为下一轮，`target_round = current_round + 1`。
4. 超过 `max_rounds` 时拒绝继续派发。
5. 用 `_existing_worker_dispatch(...)` 按 `user_task_id`、父任务和轮次做幂等检查，避免同轮重复创建。
6. 创建 `delegation` 和 worker Kanban 子任务。
7. 关闭用户任务派发阶段，完成父 Kanban 任务或当前 review 任务。
8. 返回已创建的 assignment / Kanban task 映射。

Worker 子任务的 idempotency key 包含轮次和内容 hash，因此同一轮同一 worker 可以接不同内容任务，同时不会因为上一轮任务阻止下一轮继续派发。

## 6. Review 任务创建与完成

入口：`argos/services/kanban_sync.py`

关键函数：

- `_sync_worker_link(...)`
- `_create_ready_review_tasks(...)`
- `_format_review_body(...)`
- `_sync_review_link(...)`

当前行为：

1. worker Kanban task 完成后，同步器调用 `store.complete_assignment(...)`。
2. 当前轮所有 assignment 都进入终态后，用户任务进入 `ready_to_review`。
3. `_create_ready_review_tasks(...)` 为当前轮创建 `kanban_role="review"` 的 leader review 任务。
4. review task 使用 `idempotency_key=f"review:{user_task_id}:round:{current_round}"`，避免重复创建。
5. review task body 会列出用户原始任务、当前轮 worker 结果、`round` 和 `max_rounds`，并明确三种决策。
6. review task done 后：
   - 如果已经存在下一轮 delegation，则标记当前轮 `reviewed`，用户任务继续等待 worker。
   - 如果没有下一轮 delegation，则标记用户任务 `completed`。
7. review task 进入 `blocked`、`failed`、`crashed`、`timed_out`、`gave_up` 等失败状态时，用户任务标记为 `blocked`。

`_create_ready_summary_tasks(...)` 和 `_format_summary_body(...)` 仍作为兼容包装存在，内部转到 review 语义。

## 7. 数据字段

长时任务相关字段已在模型和 SQLite 轻量迁移中落地：

```text
user_tasks.current_round
user_tasks.max_rounds
user_tasks.review_task_ids_json
user_tasks.blocked_at
user_tasks.block_reason
delegations.round
delegations.review_task_id
delegations.reviewed_at
```

本地 Kanban 映射表会记录：

- `local_type`
- `local_id`
- `kanban_task_id`
- `kanban_role`
- `kanban_status`
- `assignee_profile`
- `parent_local_id`
- `metadata`

## 8. MCP 工具约束

长时任务继续派发必须使用项目 MCP 工具：

```text
mcp_agent_bus_create_kanban_worker_tasks
```

review prompt 明确要求：

- 必须传 `user_task_id`。
- 必须把当前 review Kanban task id 作为 `parent_task_id`。
- 不要使用内置 `kanban_create`、`kanban_comment`、`kanban_assign` 模拟 worker 子任务，因为这些任务不会进入项目的 `kanban_task_links`，UI 无法稳定追踪。

如果必须由用户确认或补充信息才能继续，使用：

```text
mcp_agent_bus_request_human_input
```

## 9. 已覆盖测试

相关测试包括：

- `tests/test_mcp_kanban_tasks.py`
- `tests/test_kanban_sync.py`
- `tests/test_transfer.py`
- `tests/test_model_config_api.py`
- `tests/test_skill_api.py`
- `tests/test_mcp_installer.py`

这些测试覆盖 worker 子任务创建、Kanban 同步、多轮 review、导入导出、模型配置、Skills 和 MCP 管理等关键路径。
