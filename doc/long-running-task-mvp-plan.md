# 长时任务 MVP 改造方案

本文档描述如何把当前“一轮拆分 + 一轮汇总”的 Hermes Agent Team 改造成可多轮推进的长时任务 MVP。

目标是做到可以直接进入开发：明确状态机、数据字段、接口语义、关键文件改动、测试用例和迁移策略。

## 1. 背景与结论

当前项目已经具备 Kanban 执行底座：

- 用户任务会创建 leader 父 Kanban 任务。
- leader 可通过 MCP 创建 worker Kanban 子任务。
- worker 结果会同步回本地 `Delegation / Assignment`。
- 所有 worker 完成后，系统会创建 leader 汇总 Kanban 任务。
- Kanban sync/dispatch worker 后台持续运行。

但当前编排语义是单轮闭环：

```text
user_task running
  -> leader dispatch
  -> waiting_workers
  -> ready_to_summarize
  -> summarizing
  -> completed
```

汇总任务提示词明确要求“只基于 worker 结果输出最终总结，不要重复派发”，并且 `mcp_server.py` 会拦截同一用户任务下的后续 worker 派发。因此它只能完成一次拆分和一次汇总，不支持 `plan -> execute -> observe -> replan -> execute` 的长时任务循环。

MVP 改造结论：

- 保留现有 Kanban 执行底座。
- 给 `user_task` 和 `delegation` 增加轮次概念。
- 把 leader 汇总任务改成“review/checkpoint 任务”。
- review 任务可以选择：
  - 完成用户任务；
  - 继续创建下一轮 worker 子任务；
  - 阻塞任务并说明原因。
- 加最大轮次保护，避免无限循环。

## 2. MVP 范围

### 2.1 目标

MVP 需要支持：

1. 同一个 `user_task` 下允许多轮 `delegation`。
2. 每轮 worker 全部结束后，创建一个 leader review Kanban 任务。
3. leader review 可以继续调用 `mcp_agent_bus_create_kanban_worker_tasks` 创建下一轮 worker 任务。
4. leader review 如果判断目标已完成，则调用 `kanban_complete(summary=...)` 完成 review 任务，系统将 `user_task` 标记为 `completed`。
5. 如果达到最大轮次，系统不再允许继续派发，并要求 leader 输出最终总结或阻塞说明。
6. 保持现有单轮任务兼容：不需要继续推进的任务仍然一轮完成。

### 2.2 非目标

MVP 暂不做：

- 复杂 UI 任务树重构。
- 人工 checkpoint 审批。
- 预算管理、token 预算、费用统计。
- 自动压缩长上下文。
- worker 自动重试策略重构。
- 多 leader 协同。
- 完整数据库 migration 框架。

这些能力可以在 MVP 稳定后迭代。

## 3. 当前关键代码路径

### 3.1 用户任务创建

文件：`app/services/messages.py`

入口：`send_user_task(...)`

当前行为：

1. 创建 `user_task`，状态为 `running`。
2. 创建 leader 父 Kanban 任务，角色为 `parent`。
3. 父任务状态为 `pending_dispatch`。
4. 自动触发 `dispatch_worker.trigger_async()`。

关键问题：

- `_format_user_task(...)` 提示 leader 创建 worker 后必须关闭父任务。
- 提示词要求汇总任务不要再次派发。

### 3.2 worker 子任务创建

文件：`app/mcp_server.py`

入口：`create_kanban_worker_tasks(...)`

当前行为：

1. 解析当前 active `user_task`。
2. `_existing_worker_dispatch(...)` 检查同一 `user_task` 或父任务是否已有 worker 子任务。
3. 如果存在，直接返回旧派发结果，避免重复创建。
4. 创建 `delegation`。
5. 创建 worker Kanban 子任务。
6. `store.close_user_task_dispatch(user_task_id)` 关闭派发阶段。
7. `_complete_parent_dispatch_task(...)` 完成父 Kanban 任务。

关键问题：

- `_existing_worker_dispatch(...)` 以整个 `user_task` 为粒度去重，导致后续轮次无法创建。
- `close_user_task_dispatch(...)` 把当前用户任务推进到等待汇总路径。
- `_worker_idempotency_key(...)` 使用 `user-task-worker:{user_task_id}:{worker_agent_id}`，同一用户任务同一 worker 只能有一张任务卡。

### 3.3 worker 完成后创建汇总任务

文件：`app/services/kanban_sync.py`

入口：

- `_sync_worker_link(...)`
- `_create_ready_summary_tasks(...)`
- `_format_summary_body(...)`

当前行为：

1. worker Kanban 任务 done 后，调用 `store.complete_assignment(...)`。
2. 所有 assignment 完成后，`user_task` 进入 `ready_to_summarize`。
3. `_create_ready_summary_tasks(...)` 创建唯一一个 `kanban_role="summary"` 的 leader 汇总任务。
4. 汇总任务完成后 `_sync_summary_link(...)` 直接 `mark_user_task_completed(...)`。

关键问题：

- summary 任务只有一个，按 `local_type=user_task + local_id=user_task_id + kanban_role=summary` 去重。
- summary 完成即用户任务完成。
- summary prompt 不允许继续派发。

### 3.4 Store 状态机

文件：

- `app/models/store/user_tasks.py`
- `app/models/store/delegations.py`
- `app/models/store/base.py`

当前用户任务状态：

```text
running
waiting_workers
ready_to_summarize
summarizing
completed
```

当前 delegation 状态：

```text
waiting_workers
ready_to_summarize
summarizing
summarized
```

关键问题：

- 没有 `reviewing` / `continuing` / `blocked`。
- 没有轮次字段。
- `_user_task_ready_to_summarize_locked(...)` 会基于所有 delegation 状态判断整个用户任务可汇总，不区分当前轮。

## 4. 新的 MVP 语义

### 4.1 概念定义

| 概念 | 含义 |
| --- | --- |
| user_task | 用户提交的顶层目标，跨多轮持续存在。 |
| round | 同一个 user_task 下的一轮执行，最小值为 1。 |
| delegation | 某一轮 leader 创建的一批 worker 子任务。 |
| assignment | delegation 下分配给单个 worker 的任务。 |
| review task | 某轮 worker 全部结束后创建给 leader 的复盘/决策 Kanban 任务。 |
| final summary | leader 判断目标完成后的最终输出。 |

### 4.2 状态机

MVP 用户任务状态建议：

```text
running
dispatching
waiting_workers
ready_to_review
reviewing
completed
blocked
```

含义：

| 状态 | 含义 |
| --- | --- |
| `running` | 用户任务刚创建，等待 leader 初始规划。 |
| `dispatching` | leader 正在创建本轮 worker 任务。MVP 可选，不一定单独落库。 |
| `waiting_workers` | 当前轮 worker 执行中。 |
| `ready_to_review` | 当前轮 worker 全部结束，等待创建 leader review 任务。 |
| `reviewing` | leader 正在复盘当前轮结果并决定下一步。 |
| `completed` | 用户目标已完成。 |
| `blocked` | 用户目标无法继续，需要人工或外部条件。 |

MVP delegation 状态建议：

```text
waiting_workers
ready_to_review
reviewing
reviewed
```

兼容说明：

- 可以保留旧值 `ready_to_summarize / summarizing / summarized`，但新代码内部统一写新值。
- 读取旧数据库时，将旧值映射到新语义：
  - `ready_to_summarize` -> `ready_to_review`
  - `summarizing` -> `reviewing`
  - `summarized` -> `reviewed`

### 4.3 多轮流程

```text
用户提交任务
  -> 创建 user_task round=1
  -> 创建 leader 父 Kanban 任务
  -> leader 初始规划
  -> create_kanban_worker_tasks(round=1)
  -> worker 子任务执行
  -> worker 全部完成
  -> 创建 leader review task(round=1)
  -> leader review:
       A. 已完成 -> kanban_complete -> user_task completed
       B. 未完成 -> create_kanban_worker_tasks(round=2) -> review task complete -> waiting_workers
       C. 阻塞 -> kanban_block -> user_task blocked
```

### 4.4 继续派发的触发方式

MVP 不新增复杂协议，让 leader 在 review Kanban 任务里继续调用已有 MCP 工具：

```python
mcp_agent_bus_create_kanban_worker_tasks(
    assignments=[...],
    from_agent_id="agent_leader",
    user_task_id="ut_0001",
    parent_task_id="<当前 review task id>",
    summary_instruction="..."
)
```

区别是：

- 工具内部识别当前 `user_task` 的 `current_round`。
- 如果当前处于 `reviewing`，则创建 `next_round = current_round + 1`。
- 新 worker 子任务的 parent 依赖当前 review task。
- review task 应在创建下一轮 worker 后被 `kanban_complete(summary=...)` 关闭，表示“本轮 review 完成，已进入下一轮执行”。

## 5. 数据模型改造

### 5.1 RuntimeStore 内存 dict 字段

`user_task` 新增字段：

```python
{
    "current_round": 1,
    "max_rounds": 5,
    "review_task_ids": [],
    "blocked_at": None,
    "block_reason": "",
}
```

字段说明：

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `current_round` | int | `1` | 当前执行轮次。 |
| `max_rounds` | int | `5` | 最大允许轮次。MVP 固定为 5，后续可配置。 |
| `review_task_ids` | list[str] | `[]` | 每轮 leader review Kanban 任务 ID。 |
| `blocked_at` | str/null | `None` | 阻塞时间。 |
| `block_reason` | str | `""` | 阻塞原因。 |

`delegation` 新增字段：

```python
{
    "round": 1,
    "review_task_id": None,
    "reviewed_at": None,
}
```

`kanban_task_link.metadata` 新增约定：

```python
{
    "user_task_id": "ut_0001",
    "delegation_id": "dlg_0001",
    "round": 1,
    "kind": "parent|worker|review",
    "parent_task_id": "...",
    "review_task_id": "...",
    "continuation": true
}
```

### 5.2 SQLite 字段

MVP 推荐最小侵入方式：

1. `user_tasks` 表新增：
   - `current_round INTEGER DEFAULT 1`
   - `max_rounds INTEGER DEFAULT 5`
   - `review_task_ids_json TEXT DEFAULT '[]'`
   - `blocked_at VARCHAR(40) NULL`
   - `block_reason TEXT DEFAULT ''`
2. `delegations` 表新增：
   - `round INTEGER DEFAULT 1`
   - `review_task_id VARCHAR(120) NULL`
   - `reviewed_at VARCHAR(40) NULL`

备选方案：

- 如果不想改表，可以先全部放进已有 `metadata_json`，但当前 `user_tasks` 和 `delegations` 没有 metadata 字段，所以最终会绕很多逻辑。建议 MVP 直接加列。

### 5.3 SQLite 兼容迁移

当前 `app/db/repositories.py` 使用 `Base.metadata.create_all(bind=engine)`，不会自动给已有表加列。

MVP 需要在 SQLite 初始化后做轻量 schema patch：

建议新增：

```text
app/db/migrations.py
```

提供：

```python
def ensure_runtime_schema(engine) -> None:
    ...
```

逻辑：

1. 查询 `PRAGMA table_info(user_tasks)`。
2. 如果缺列，执行 `ALTER TABLE user_tasks ADD COLUMN ...`。
3. 查询 `PRAGMA table_info(delegations)`。
4. 如果缺列，执行 `ALTER TABLE delegations ADD COLUMN ...`。

在 `SQLitePersistence.__init__` 或初始化路径中：

```python
Base.metadata.create_all(bind=engine)
ensure_runtime_schema(engine)
```

测试也要覆盖已有旧库启动。

## 6. 关键文件改造方案

### 6.1 `app/services/messages.py`

#### 需要修改的函数

- `_format_user_task(...)`
- `send_user_task(...)`

#### Prompt 改造

当前第 4/5 条规则要求一轮结束后最终汇总。改为：

```text
4. 创建 worker 子任务后，必须立即调用 kanban_complete(summary=...) 关闭当前规划/复盘任务；这个 complete 只表示“本轮调度或复盘完成”，不是用户最终答复。
5. 收到 review/checkpoint 任务时，请基于 worker 结果判断用户目标是否完成：
   - 如果已完成：调用 kanban_complete(summary=最终答复)，不要再派发。
   - 如果未完成且未达到最大轮次：调用 mcp_agent_bus_create_kanban_worker_tasks 创建下一轮 worker 子任务。
   - 如果无法继续：调用 kanban_block(reason=...) 或 kanban_complete(summary=阻塞说明)，并明确阻塞原因。
6. 每次继续派发都必须带上 user_task_id 和当前 review task 的 parent_task_id。
7. 不要重复派发当前轮已完成的同一批任务；允许基于新发现创建下一轮任务。
```

#### `send_user_task(...)`

创建 `user_task` 时需要初始化：

```python
"current_round": 1,
"max_rounds": DEFAULT_MAX_ROUNDS,
"review_task_ids": [],
"blocked_at": None,
"block_reason": "",
```

如果 `store.create_user_task(...)` 内部处理默认值，则 `send_user_task(...)` 不需要额外 patch。

### 6.2 `app/services/soul.py`

#### 需要修改

- `LEADER_TOOL_HINT`

#### 改造目标

同步 leader profile 的长期任务规则，否则新创建的 leader SOUL.md 仍会教模型只做一轮。

新增/替换要点：

```text
- 用户任务可能是长时任务。你要以“多轮 checkpoint”方式推进，而不是默认一轮结束。
- 每轮 worker 全部完成后，系统会给你创建 review Kanban 任务。
- review 时先判断原始目标是否完成；未完成则创建下一轮 worker 子任务。
- 不要重复派发同一轮同一批任务；允许创建下一轮更具体的任务。
- 必须遵守 max_rounds，达到上限后输出当前最佳结果或阻塞说明。
```

### 6.3 `app/models/store/user_tasks.py`

#### 新增常量

```python
DEFAULT_MAX_TASK_ROUNDS = 5
```

#### `create_user_task(...)`

新增字段：

```python
"current_round": 1,
"max_rounds": DEFAULT_MAX_TASK_ROUNDS,
"review_task_ids": [],
"blocked_at": None,
"block_reason": "",
```

#### `close_user_task_dispatch(...)`

当前名字可以保留，但语义改为“关闭本轮 dispatch”。

当前逻辑：

- 无 delegation -> completed
- delegation 全完成 -> ready_to_summarize
- 否则 waiting_workers

改为：

- 无 delegation：
  - 初始 leader 父任务直接完成时，可以 `completed`。
- 当前轮 delegation 全完成：
  - `status = "ready_to_review"`
- 当前轮 delegation 未完成：
  - `status = "waiting_workers"`

注意：判断必须只看当前轮，不看历史轮。

新增 helper：

```python
def _current_round_delegations_locked(self, task: dict) -> list[dict]:
    ...

def _current_round_ready_to_review_locked(self, task: dict) -> bool:
    ...
```

逻辑：

```python
current_round = int(task.get("current_round") or 1)
delegations = [
    self._find_delegation_locked(delegation_id)
    for delegation_id in task["delegation_ids"]
    if int(delegation.get("round") or 1) == current_round
]
return bool(delegations) and all(
    delegation["status"] in {"ready_to_review", "reviewing", "reviewed"}
    for delegation in delegations
)
```

#### `mark_user_task_summarizing(...)`

建议改名或新增包装：

```python
def mark_user_task_reviewing(self, user_task_id: str, review_task_id: str = "") -> dict:
    ...
```

为了减少改动，可保留旧函数并内部调用新函数。

行为：

- `task["status"] = "reviewing"`
- 如果传入 `review_task_id`，追加到 `review_task_ids`。
- 仅把当前轮 `ready_to_review / waiting_workers` 的 delegation 标为 `reviewing`。
- 不再把所有历史 delegation 都改掉。

#### `mark_user_task_completed(...)`

保留，完成时：

- `task["status"] = "completed"`
- 只把未 `reviewed` 的 delegation 标为 `reviewed`。

#### 新增 `advance_user_task_round(...)`

用于 leader review 创建下一轮 worker 后推进轮次：

```python
def advance_user_task_round(self, user_task_id: str) -> dict:
    task["current_round"] += 1
    task["status"] = "waiting_workers"
    task["dispatch_closed"] = True
```

约束：

- 如果 `current_round >= max_rounds`，抛出 `ValueError("max rounds reached")`。
- 只允许在 `reviewing` 或 `ready_to_review` 状态调用。

#### 新增 `mark_user_task_blocked(...)`

MVP 可选，但建议加：

```python
def mark_user_task_blocked(self, user_task_id: str, reason: str) -> None:
    task["status"] = "blocked"
    task["blocked_at"] = now_iso()
    task["block_reason"] = reason
```

### 6.4 `app/models/store/delegations.py`

#### `create_delegation(...)`

新增参数：

```python
round_number: int | None = None
```

如果传入 `user_task_id`：

```python
task = self._find_user_task_locked(user_task_id)
round_number = round_number or int(task.get("current_round") or 1)
```

delegation 新增：

```python
"round": round_number,
"review_task_id": None,
"reviewed_at": None,
```

状态：

```python
"status": "waiting_workers"
```

#### `complete_assignment(...)`

当前所有 assignment 完成后写：

```python
delegation["status"] = "ready_to_summarize"
```

改为：

```python
delegation["status"] = "ready_to_review"
```

如果有 `user_task_id`，只判断当前轮是否都 ready：

```python
if self._current_round_ready_to_review_locked(task):
    task["status"] = "ready_to_review"
    completed_user_task = dict(task)
```

#### `mark_delegation_summarizing / summarized`

建议新增新名字并保留旧名字兼容：

```python
def mark_delegation_reviewing(...)
def mark_delegation_reviewed(...)
```

旧函数：

```python
def mark_delegation_summarizing(...):
    return self.mark_delegation_reviewing(...)
```

### 6.5 `app/models/store/base.py`

#### `_user_task_ready_to_summarize_locked(...)`

保留兼容，但内部改为调用：

```python
return self._current_round_ready_to_review_locked(task)
```

新增：

```python
def _current_round_delegations_locked(self, task: dict) -> list[dict]:
    ...

def _current_round_ready_to_review_locked(self, task: dict) -> bool:
    ...
```

注意旧数据兼容：

```python
round_number = int(delegation.get("round") or 1)
```

### 6.6 `app/mcp_server.py`

这是 MVP 最关键的改动。

#### `create_kanban_worker_tasks(...)`

新增处理逻辑：

1. 解析 `resolved_user_task_id`。
2. 获取 `user_task`。
3. 计算目标轮次：

```python
current_round = int(user_task.get("current_round") or 1)
if user_task["status"] in {"reviewing", "ready_to_review"}:
    target_round = current_round + 1
else:
    target_round = current_round
```

4. 如果 `target_round > max_rounds`：

```python
raise ValueError("max rounds reached for this user task")
```

5. `_existing_worker_dispatch(...)` 必须按 `round` 去重。
6. `store.create_delegation(..., round_number=target_round)`。
7. worker link metadata 写入 `round`。
8. worker idempotency key 加入 round。
9. 如果是 continuation：
   - 调用 `store.advance_user_task_round(user_task_id)`。
   - 不要把整个 user_task completed。
10. 返回结果增加：

```python
"round": target_round,
"max_rounds": max_rounds,
"continuation": target_round > current_round,
```

#### `_existing_worker_dispatch(...)`

当前签名：

```python
def _existing_worker_dispatch(user_task_id: str | None, parent_task_id: str) -> dict | None:
```

改为：

```python
def _existing_worker_dispatch(
    user_task_id: str | None,
    parent_task_id: str,
    round_number: int | None,
) -> dict | None:
```

过滤条件增加：

```python
metadata_round = int((link.get("metadata") or {}).get("round") or 1)
metadata_round == round_number
```

这样同一 user_task 的第 1 轮 worker 不会阻止第 2 轮 worker。

#### `_worker_idempotency_key(...)`

当前：

```python
return f"user-task-worker:{user_task_id}:{assignment['worker_agent_id']}"
```

改为：

```python
return f"user-task-worker:{user_task_id}:round:{round_number}:{assignment['worker_agent_id']}"
```

如果同一轮同一个 worker 需要多个子任务，可进一步包含 normalized title/content hash：

```python
content_hash = sha1(assignment["content"].encode()).hexdigest()[:12]
return f"user-task-worker:{user_task_id}:round:{round_number}:{assignment['worker_agent_id']}:{content_hash}"
```

MVP 建议加入 `content_hash`，否则同一轮同一 worker 无法接多个不同子任务。

#### `_complete_parent_dispatch_task(...)`

当前只用于完成初始父任务。

MVP 需要兼容 review task 作为下一轮 parent：

- 如果 `parent_task_id` 是原始 parent，summary 写“第 N 轮 dispatch 已创建”。
- 如果 `parent_task_id` 是 review task，summary 写“第 N 轮 review 已完成，已创建第 N+1 轮 worker 子任务”。

metadata 增加：

```python
"round": round_number,
"continuation": continuation,
```

### 6.7 `app/services/kanban_sync.py`

#### `_sync_worker_link(...)`

当 worker 完成：

```python
completed = self.store.complete_assignment(...)
```

`completed` 现在表示当前轮 ready_to_review 的 user_task，而不是最终 summary。

逻辑可基本保留，但事件名建议从：

```text
user_task.ready_to_summarize
```

逐步替换为：

```text
user_task.ready_to_review
```

#### `_create_ready_summary_tasks(...)`

建议改名：

```python
_create_ready_review_tasks(...)
```

旧函数保留为 wrapper 或直接重命名并更新调用。

当前逻辑有两个问题：

1. 查找 existing summary link 只按 `user_task_id + kanban_role=summary`，导致只能创建一个。
2. assignments 取所有历史轮次。

MVP 改造：

```python
for user_task in snapshot["user_tasks"]:
    if user_task["status"] not in {"ready_to_review", "waiting_workers"}:
        continue

    current_round = int(user_task.get("current_round") or 1)

    existing = find review link where:
        local_type == "user_task"
        local_id == user_task_id
        kanban_role == "review"
        metadata.round == current_round

    assignments = _assignments_for_user_task_round(snapshot, user_task_id, current_round)
    if not assignments or not all(completed/failed):
        continue

    create review task
```

review task link：

```python
store.upsert_kanban_task_link(
    local_type="user_task",
    local_id=f"{user_task_id}:round:{current_round}",
    kanban_task_id=review_task_id,
    kanban_role="review",
    parent_local_id=user_task_id,
    metadata={
        "user_task_id": user_task_id,
        "round": current_round,
        "task_title": task_title,
    },
)
```

重要：由于 `kanban_task_links` 有唯一约束：

```text
UniqueConstraint("local_type", "local_id", "kanban_role")
```

如果 `local_id` 仍是 `user_task_id`，同一个用户任务只能有一个 `review` link。因此 MVP 必须：

- `local_id = f"{user_task_id}:round:{current_round}"`；
- `parent_local_id = user_task_id`；
- metadata 里保留真实 `user_task_id`。

#### `_format_summary_body(...)`

改名建议：

```python
_format_review_body(user_task, assignments, current_round, max_rounds)
```

提示词应明确三种选择：

```text
[KANBAN_LEADER_REVIEW_TASK]
user_task_id: ut_0001
round: 1
max_rounds: 5

这是长时任务 checkpoint。请基于用户原始目标和本轮 worker 结果判断下一步。

你必须选择一种行动：
1. 如果目标已经完成：调用 kanban_complete(summary=最终答复)。
2. 如果目标未完成且 round < max_rounds：调用 mcp_agent_bus_create_kanban_worker_tasks 创建下一轮 worker 子任务。
   - 必须传 user_task_id。
   - 必须传 parent_task_id=<当前 review Kanban task id>。
   - 子任务必须是下一轮需要的新工作，不要重复当前轮已经完成的同一批任务。
   - 创建后调用 kanban_complete(summary=本轮复盘和下一轮计划)。
3. 如果无法继续或已达到 max_rounds：调用 kanban_complete(summary=当前最佳结果和未完成/阻塞原因)，不要继续派发。
```

#### `_sync_summary_link(...)`

建议改名：

```python
_sync_review_link(...)
```

MVP 关键逻辑：

当前 review task done 时，不能无条件 `mark_user_task_completed`。

需要判断是否已经创建下一轮 worker。

伪代码：

```python
def _sync_review_link(link, status, result, task):
    if status == "blocked":
        store.mark_user_task_blocked(user_task_id, result or _task_summary(task))
        return

    if status != "done":
        return

    user_task = store.find_user_task(user_task_id)
    round_number = metadata["round"]

    next_round = round_number + 1
    has_next_round_delegation = any(
        delegation.user_task_id == user_task_id
        and delegation.round == next_round
        for delegation in snapshot["delegations"]
    )

    if has_next_round_delegation:
        mark current round delegation reviewed
        ensure user_task.status == "waiting_workers"
        do not complete user_task
    else:
        store.mark_user_task_completed(user_task_id)
```

这条规则让 leader review 自然决定是否继续：

- 如果 leader 在 review 中创建了下一轮 worker，review done 不完成 user_task。
- 如果 leader 没创建下一轮 worker，review done 完成 user_task。

达到 `max_rounds` 时，review prompt 不允许继续派发；如果仍尝试派发，MCP 工具抛错。

#### `_assignments_for_user_task(...)`

新增：

```python
def _assignments_for_user_task_round(snapshot, user_task_id, round_number) -> list[dict]:
    ...
```

只返回当前轮 delegation 的 assignments。

### 6.8 `app/db/models.py`

新增字段：

```python
class UserTaskRecord(...):
    current_round: Mapped[int] = mapped_column(Integer, default=1)
    max_rounds: Mapped[int] = mapped_column(Integer, default=5)
    review_task_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    blocked_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    block_reason: Mapped[str] = mapped_column(Text, default="")

class DelegationRecord(...):
    round: Mapped[int] = mapped_column(Integer, default=1)
    review_task_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
```

注意：`round` 是 Python 内置函数名，但 SQLAlchemy 字段名可用。为避免可读性问题，Python 属性建议叫：

```python
round_number: Mapped[int] = mapped_column("round", Integer, default=1)
```

dict 字段仍用 `"round"`。

### 6.9 `app/db/repositories.py`

#### `upsert_user_task(...)`

写入新增字段：

```python
record.current_round = int(task.get("current_round") or 1)
record.max_rounds = int(task.get("max_rounds") or 5)
record.review_task_ids_json = _json_dumps(task.get("review_task_ids") or [])
record.blocked_at = task.get("blocked_at")
record.block_reason = task.get("block_reason") or ""
```

#### `_user_task_to_dict(...)`

读出新增字段。旧数据默认：

```python
"current_round": record.current_round or 1,
"max_rounds": record.max_rounds or 5,
"review_task_ids": _json_loads(record.review_task_ids_json, []),
"blocked_at": record.blocked_at,
"block_reason": record.block_reason or "",
```

#### `upsert_delegation(...)`

写入：

```python
record.round_number = int(delegation.get("round") or 1)
record.review_task_id = delegation.get("review_task_id")
record.reviewed_at = delegation.get("reviewed_at")
```

#### `_delegation_to_dict(...)`

读出：

```python
"round": record.round_number or 1,
"review_task_id": record.review_task_id,
"reviewed_at": record.reviewed_at,
```

并更新 interrupted 映射：

```python
if status in {"waiting_workers", "ready_to_review", "reviewing", "ready_to_summarize", "summarizing"}:
    status = "interrupted"
```

### 6.10 `app/static/app.js` 与 `app/templates/index.html`

MVP 可不做 UI 大改。

建议最小显示增强：

- 在 Kanban link 卡片中，如果 metadata 有 `round`，显示 `Round N`。
- review task 使用不同 label：`review`。
- user_task 当前状态如果在 bootstrap 中已有，可在未来增加展示。

如果不改 UI，功能仍可跑，只是多轮可观测性弱一些。

## 7. 幂等策略

长时任务最容易出错的是重复创建任务。MVP 需要明确幂等边界。

### 7.1 user_task 幂等

保持现状：

```text
user_task:{user_task_id}
```

用户每提交一次创建一个新的 user_task。

### 7.2 worker 任务幂等

新 key：

```text
user-task-worker:{user_task_id}:round:{round}:{worker_agent_id}:{content_hash}
```

理由：

- 同一用户任务可以多轮。
- 同一轮同一 worker 可以处理多个不同任务。
- 同一轮同一 worker 同一内容重复调用时可复用。

### 7.3 review 任务幂等

新 key：

```text
review:{user_task_id}:round:{round}
```

这样每轮最多一个 review task。

### 7.4 existing dispatch 判断

`_existing_worker_dispatch(...)` 必须只查当前目标轮次。

不能再以整个 user_task 为粒度拦截。

## 8. 最大轮次与失败保护

### 8.1 默认最大轮次

MVP 固定：

```python
DEFAULT_MAX_TASK_ROUNDS = 5
```

后续可接入 settings。

### 8.2 达到上限后的行为

当 `current_round >= max_rounds` 且 leader review 尝试继续派发：

```python
raise ValueError("max rounds reached for this user task")
```

review prompt 应要求 leader：

- 输出当前最佳结果；
- 标明未完成部分；
- 不再继续派发。

### 8.3 worker 失败

MVP 继承现有行为：

- `blocked / failed / crashed / timed_out / gave_up` 都会让 assignment 进入 failed。
- 当前轮所有 assignment 都是 completed/failed 后，仍进入 review。
- leader 在 review 中决定是否补派下一轮。

## 9. 兼容策略

### 9.1 旧状态兼容

读旧数据时：

| 旧状态 | 新语义 |
| --- | --- |
| `ready_to_summarize` | `ready_to_review` |
| `summarizing` | `reviewing` |
| `summarized` | `reviewed` |

可以先不迁移历史值，只在判断集合里同时接受新旧状态。

### 9.2 旧 summary link 兼容

已有 `kanban_role="summary"` 的 link 继续由旧逻辑处理。

新建任务使用 `kanban_role="review"`。

`_sync_link(...)` 中：

```python
elif link.get("kanban_role") in {"summary", "review"}:
    self._sync_review_link(...)
```

旧 summary done 仍可 completed。

### 9.3 旧数据库兼容

新增列必须有默认值。

加载旧记录时不能因缺字段崩溃。

## 10. 测试方案

### 10.1 Store 单元测试

文件：`tests/test_runtime_store_persistence.py` 或新增 `tests/test_long_running_store.py`

用例：

1. `create_user_task` 初始化 `current_round=1`、`max_rounds=5`。
2. 第 1 轮 delegation 完成后，user_task 进入 `ready_to_review`。
3. review 中创建第 2 轮 delegation 后，user_task `current_round=2`、状态 `waiting_workers`。
4. 第 2 轮完成后，只根据第 2 轮 assignments 判断 `ready_to_review`。
5. `mark_user_task_completed` 将任务 completed。
6. 达到 max_rounds 时 `advance_user_task_round` 抛错。

### 10.2 MCP 工具测试

文件：`tests/test_mcp_kanban_tasks.py`

新增/调整：

1. 同一 user_task 第 1 轮重复调用同样 assignments，返回 idempotent。
2. user_task 进入 `reviewing` 后，再调用创建 worker，应创建第 2 轮新任务。
3. 第 2 轮 worker idempotency key 不复用第 1 轮任务。
4. 同一轮同一 worker 不同 content 创建不同任务。
5. 达到 max_rounds 后继续调用报错。

### 10.3 Kanban sync 测试

文件：`tests/test_kanban_sync.py`

新增/调整：

1. 第 1 轮 worker done 后创建 `review:{user_task_id}:round:1`。
2. 已有第 1 轮 review 时不会重复创建。
3. 第 1 轮 review done 且没有第 2 轮 delegation，user_task completed。
4. 第 1 轮 review done 且已有第 2 轮 delegation，user_task 不 completed，状态保持 waiting_workers。
5. 第 2 轮 worker done 后创建 `review:{user_task_id}:round:2`。
6. blocked review task 会把 user_task 标为 blocked。

### 10.4 Persistence 测试

新增：

1. 新字段能写入 SQLite 并读回。
2. 旧数据库缺列时 `ensure_runtime_schema` 自动补列。
3. 旧 delegation 无 round 时读出 round=1。

### 10.5 Prompt 内容测试

文件：`tests/test_messages_kanban.py`

检查：

1. `_format_user_task` 包含 `review/checkpoint`。
2. 不再包含“不要重复派发同一批任务”这种全局禁止继续派发的表达。
3. 包含 `max_rounds` 或最大轮次说明。
4. 包含继续派发必须传 `user_task_id` / `parent_task_id`。

## 11. 开发步骤

建议按以下顺序开发，减少一次性改动风险。

### Step 1：数据字段与兼容读取

改动：

- `app/db/models.py`
- `app/db/repositories.py`
- 新增 `app/db/migrations.py`
- `app/models/store/user_tasks.py`
- `app/models/store/delegations.py`

验收：

- 新旧数据库都能启动。
- store snapshot 中 user_task/delegation 都有 round 相关字段。
- 现有测试通过。

### Step 2：状态机改为 review 语义

改动：

- `app/models/store/base.py`
- `app/models/store/user_tasks.py`
- `app/models/store/delegations.py`

验收：

- worker 完成后进入 `ready_to_review`。
- 旧 `ready_to_summarize` 判断仍兼容。

### Step 3：MCP 多轮派发

改动：

- `app/mcp_server.py`

验收：

- 同一 user_task 第 2 轮能创建新 worker 任务。
- 同一轮重复调用仍幂等。
- worker idempotency key 包含 round。

### Step 4：Kanban review task

改动：

- `app/services/kanban_sync.py`

验收：

- 每轮创建一个 review task。
- review done 无下一轮则 completed。
- review done 有下一轮则不 completed。

### Step 5：Prompt 与 SOUL

改动：

- `app/services/messages.py`
- `app/services/soul.py`

验收：

- 新 leader 任务提示可指导多轮 checkpoint。
- 新生成 SOUL.md 的 leader 知道长时任务规则。

### Step 6：最小 UI 标识

改动：

- `app/static/app.js`
- 必要时 `app/templates/index.html`

验收：

- Kanban 卡片能看到 review 和 round。
- 不要求完整任务树。

## 12. 验收场景

### 场景 A：单轮完成

输入：

```text
请让团队分析这个项目是否支持长时任务，并给出结论。
```

期望：

1. leader 创建第 1 轮 worker。
2. worker 完成。
3. 创建 round 1 review task。
4. leader 判断已完成并 complete。
5. user_task completed。

### 场景 B：两轮完成

输入：

```text
请让团队先分析项目长时任务现状，再根据分析结果继续给出 MVP 改造方案。
```

期望：

1. round 1 worker 做现状分析。
2. round 1 review 判断还需要方案设计。
3. round 1 review 创建 round 2 worker。
4. round 2 worker 完成方案设计。
5. round 2 review 输出最终结果。
6. user_task completed。

### 场景 C：达到最大轮次

设置：

```python
max_rounds = 2
```

期望：

1. round 2 review 尝试创建 round 3 worker。
2. MCP 工具返回 max rounds reached。
3. leader 输出当前最佳结果或阻塞说明。
4. user_task completed 或 blocked。

### 场景 D：worker 失败后补派

期望：

1. round 1 某 worker failed。
2. round 1 review 能看到失败结果。
3. leader 创建 round 2 补救任务。
4. round 2 完成后 user_task completed。

## 13. 风险与注意事项

### 13.1 review task 完成时的判定竞态

leader 在 review 中调用 MCP 创建下一轮 worker，然后再 `kanban_complete`。如果 sync worker 在下一轮 delegation 落库前看到 review done，可能误判为 completed。

缓解：

- MCP 创建下一轮 delegation 是同步落库，通常先于 leader complete。
- `_sync_review_link(...)` 可以在判定 completed 前重新读取最新 snapshot。
- 可增加 metadata 标记 `continuation=True` 到 review task complete metadata，但 Hermes Kanban result metadata 不一定稳定可读，MVP 不依赖它。

### 13.2 parent dependency

下一轮 worker 的 parent 应该是当前 review task，这样 review complete 后 worker 才会执行。

如果 leader 没传 `parent_task_id`：

- MCP 工具可以尝试从当前 user_task 的 `review_task_ids[-1]` 推断。
- 但 prompt 必须要求传入，避免推断错误。

### 13.3 旧 summary 与新 review 共存

为了降低风险：

- 新任务使用 `review`。
- 旧任务仍接受 `summary`。
- 不要一次性删除旧函数，可先 wrapper。

### 13.4 模型行为不稳定

长时任务依赖 leader 遵守 checkpoint 协议。MVP 通过 prompt 约束，不做结构化输出强校验。

后续产品版建议新增专门 MCP 工具：

```python
complete_user_task(...)
continue_user_task(...)
block_user_task(...)
```

让 leader 显式提交决策，而不是靠“有没有创建下一轮 delegation”推断。

## 14. 后续产品版方向

MVP 跑通后，建议继续做：

1. 新增结构化 decision MCP 工具。
2. UI 展示 user_task 多轮时间线。
3. settings 支持配置默认 max_rounds。
4. 人工 approval checkpoint。
5. 长上下文压缩，把历史轮次总结成 compact memory。
6. 按 worker 能力和失败率动态选择 worker。
7. 任务预算：最大时长、最大成本、最大工具调用数。

## 15. 最小改动清单

必须改：

- `app/services/messages.py`
- `app/services/soul.py`
- `app/mcp_server.py`
- `app/services/kanban_sync.py`
- `app/models/store/base.py`
- `app/models/store/user_tasks.py`
- `app/models/store/delegations.py`
- `app/db/models.py`
- `app/db/repositories.py`
- 新增 `app/db/migrations.py`
- 相关 tests

可选改：

- `app/static/app.js`
- `app/templates/index.html`

MVP 的核心验收标准：

```text
同一个 user_task 能在第 1 轮 worker 完成后，由 leader review 创建第 2 轮 worker；
第 2 轮 worker 完成后，再由 leader review 最终完成 user_task。
```
