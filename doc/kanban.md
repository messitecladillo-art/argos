# Hermes Kanban 命令速查

Hermes Kanban 是基于 SQLite 的任务看板，任务会分配给 Hermes profile，由 dispatcher/gateway 调度 worker 执行。

## 通用用法

```bash
hermes kanban [--board <slug>] <command> [options]
```

| 参数 | 功能 |
| --- | --- |
| `--board <slug>` | 指定要操作的 board；默认使用当前 board，也可用 `HERMES_KANBAN_BOARD` 环境变量指定。 |
| `-h`, `--help` | 查看帮助。 |

## 常用流程

```bash
hermes kanban init
hermes kanban create "任务标题" --body "任务说明" --assignee default
hermes kanban dispatch
hermes kanban list
hermes kanban show <task_id>
hermes kanban log <task_id>
hermes kanban archive <task_id>
```

任务要被 worker 执行，通常需要：有 `assignee`、依赖已满足、进入 `ready` 状态，并且 gateway/dispatcher 正在运行。

## Board 管理

### `hermes kanban boards`

管理不同项目/工作流的独立看板。每个 board 有独立 DB、workspace 和 dispatcher 队列。

```bash
hermes kanban boards <subcommand> [options]
```

| 子命令 | 别名 | 功能 |
| --- | --- | --- |
| `list` | `ls` | 列出所有 board 及任务数量。 |
| `create` | `new` | 创建新 board。 |
| `rm` | `remove`, `delete` | 归档或硬删除 board。 |
| `switch` | `use` | 切换当前默认 board。 |
| `show` | `current` | 显示当前默认 board。 |
| `rename` | - | 修改 board 显示名，slug 不变。 |

#### `boards list`

```bash
hermes kanban boards list [--json] [--all]
```

| 参数 | 功能 |
| --- | --- |
| `--json` | JSON 输出。 |
| `--all` | 包含已归档 board。 |

#### `boards create`

```bash
hermes kanban boards create <slug> [--name <name>] [--description <text>] [--icon <icon>] [--color <hex>] [--switch]
```

| 参数 | 功能 |
| --- | --- |
| `<slug>` | board slug，例如 `atm10-server`。 |
| `--name <name>` | 显示名；默认由 slug 转标题格式。 |
| `--description <text>` | 描述。 |
| `--icon <icon>` | dashboard 图标，emoji 或单字符。 |
| `--color <hex>` | dashboard 颜色，例如 `#8b5cf6`。 |
| `--switch` | 创建后切换到该 board。 |

#### `boards rm`

```bash
hermes kanban boards rm <slug> [--delete]
```

| 参数 | 功能 |
| --- | --- |
| `<slug>` | 要移除的 board。 |
| `--delete` | 硬删除 board 目录；默认是移动到 `boards/_archived/`，可恢复。 |

#### `boards switch`

```bash
hermes kanban boards switch <slug>
```

| 参数 | 功能 |
| --- | --- |
| `<slug>` | 切换为当前默认 board。 |

#### `boards show`

```bash
hermes kanban boards show
```

显示当前默认 board slug。

#### `boards rename`

```bash
hermes kanban boards rename <slug> <name>
```

| 参数 | 功能 |
| --- | --- |
| `<slug>` | board slug。 |
| `<name>` | 新显示名。 |

## 任务创建与查看

### `init`

```bash
hermes kanban init
```

初始化 kanban 数据库；幂等执行，数据库存在时不会重复创建。

### `create`

```bash
hermes kanban create <title> [--body <body>] [--assignee <profile>] [--parent <task_id>] [--workspace <workspace>] [--tenant <tenant>] [--priority <n>] [--triage] [--idempotency-key <key>] [--max-runtime <duration>] [--created-by <name>] [--skill <skill>] [--json]
```

| 参数 | 功能 |
| --- | --- |
| `<title>` | 任务标题。 |
| `--body <body>` | 任务说明/首条正文。 |
| `--assignee <profile>` | 分配给指定 Hermes profile。 |
| `--parent <task_id>` | 添加父任务依赖；可重复。 |
| `--workspace <workspace>` | 工作区类型：`scratch`、`worktree`、`dir:<path>`；默认 `scratch`。 |
| `--tenant <tenant>` | 租户命名空间。 |
| `--priority <n>` | 优先级排序值。 |
| `--triage` | 放入 triage，由 specifier 细化后再推进；不会直接执行。 |
| `--idempotency-key <key>` | 去重 key；存在非归档同 key 任务时返回已有 ID。 |
| `--max-runtime <duration>` | 单任务运行上限，支持 `300`、`90s`、`30m`、`2h`、`1d`。超时后 dispatcher 终止 worker 并重新排队。 |
| `--created-by <name>` | 创建者；默认 `user`。 |
| `--skill <skill>` | 强制 worker 加载指定 skill；可重复。会追加到内置 `kanban-worker` skill 后。 |
| `--json` | JSON 输出。 |

### `list` / `ls`

```bash
hermes kanban list [--mine] [--assignee <profile>] [--status <status>] [--tenant <tenant>] [--archived] [--json]
```

| 参数 | 功能 |
| --- | --- |
| `--mine` | 只显示分配给 `$HERMES_PROFILE` 的任务。 |
| `--assignee <profile>` | 按 assignee 过滤。 |
| `--status <status>` | 按状态过滤：`archived`、`blocked`、`done`、`ready`、`running`、`todo`、`triage`。 |
| `--tenant <tenant>` | 按 tenant 过滤。 |
| `--archived` | 包含已归档任务。 |
| `--json` | JSON 输出。 |

### `show`

```bash
hermes kanban show <task_id> [--json]
```

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 任务 ID。 |
| `--json` | JSON 输出。 |

### `context`

```bash
hermes kanban context <task_id>
```

打印 worker 执行任务时看到的完整上下文：标题、正文、父任务结果、评论等。

## 分配、认领与调度

### `assign`

```bash
hermes kanban assign <task_id> <profile>
```

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 任务 ID。 |
| `<profile>` | Hermes profile 名；传 `none` 可取消分配。 |

### `reassign`

```bash
hermes kanban reassign <task_id> <profile> [--reclaim] [--reason <reason>]
```

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 任务 ID。 |
| `<profile>` | 新 profile 名；传 `none` 可取消分配。 |
| `--reclaim` | 释放当前 active claim 后再重分配；任务 running 时需要。 |
| `--reason <reason>` | 记录 reclaim 原因。 |

### `claim`

```bash
hermes kanban claim <task_id> [--ttl <seconds>]
```

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 要原子认领的 ready 任务。 |
| `--ttl <seconds>` | claim 有效期，默认 `900` 秒。 |

### `reclaim`

```bash
hermes kanban reclaim <task_id> [--reason <reason>]
```

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 任务 ID。 |
| `--reason <reason>` | 释放 claim 的原因，会写入事件。 |

### `dispatch`

```bash
hermes kanban dispatch [--dry-run] [--max <n>] [--failure-limit <n>] [--json]
```

执行一次 dispatcher tick：回收 stale claim、推进 ready、启动 worker。

| 参数 | 功能 |
| --- | --- |
| `--dry-run` | 只打印将要执行的操作，不实际启动 worker。 |
| `--max <n>` | 本次最多启动多少个 worker。 |
| `--failure-limit <n>` | 连续 spawn 失败达到次数后自动 block；默认 `5`。 |
| `--json` | JSON 输出。 |

### `daemon`

```bash
hermes kanban daemon [--interval <seconds>] [--max <n>] [--failure-limit <n>] [--pidfile <path>] [--verbose]
```

旧版 dispatcher daemon；已废弃，推荐使用 `hermes gateway start`。

| 参数 | 功能 |
| --- | --- |
| `--interval <seconds>` | dispatch tick 间隔，默认 `60` 秒。 |
| `--max <n>` | 每个 tick 最多启动多少个 worker。 |
| `--failure-limit <n>` | 连续 spawn 失败限制。 |
| `--pidfile <path>` | 启动后写入 PID 文件。 |
| `--verbose`, `-v` | 输出每次 tick 结果。 |

### `heartbeat`

```bash
hermes kanban heartbeat <task_id> [--note <note>]
```

为 running 任务写入 worker 心跳事件，用于 worker 存活检测。

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 任务 ID。 |
| `--note <note>` | 附加到 heartbeat 事件的简短备注。 |

## 状态流转

### `complete`

```bash
hermes kanban complete <task_id> [<task_id> ...] [--result <text>] [--summary <text>] [--metadata <json>]
```

| 参数 | 功能 |
| --- | --- |
| `<task_id> ...` | 一个或多个任务 ID。 |
| `--result <text>` | 完成结果摘要。 |
| `--summary <text>` | 给下游任务的结构化交接摘要；省略时使用 `--result`。 |
| `--metadata <json>` | 结构化事实 JSON，例如 `{"changed_files": [], "tests_run": 12}`。 |

### `edit`

```bash
hermes kanban edit <task_id> --result <text> [--summary <text>] [--metadata <json>]
```

修改已完成任务的恢复/交接字段。

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 已完成任务 ID。 |
| `--result <text>` | 回填任务结果文本；必填。 |
| `--summary <text>` | 结构化交接摘要；省略时使用 `--result`。 |
| `--metadata <json>` | 结构化事实 JSON。 |

### `block`

```bash
hermes kanban block <task_id> [reason ...] [--ids <task_id> ...]
```

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 要阻塞的任务 ID。 |
| `[reason ...]` | 阻塞原因，也会追加为 comment。 |
| `--ids <task_id> ...` | 批量阻塞其他任务，并使用相同原因。 |

### `unblock`

```bash
hermes kanban unblock <task_id> [<task_id> ...]
```

将 blocked 任务返回 ready。

### `archive`

```bash
hermes kanban archive <task_id> [<task_id> ...]
```

归档任务；dashboard 默认可隐藏归档任务。通常用于“删除/隐藏”已完成任务。

## 依赖关系

### `link`

```bash
hermes kanban link <parent_id> <child_id>
```

添加父任务到子任务的依赖关系。子任务会等待父任务完成。

### `unlink`

```bash
hermes kanban unlink <parent_id> <child_id>
```

移除父子依赖关系。

## 评论与事件观察

### `comment`

```bash
hermes kanban comment <task_id> <text...> [--author <author>]
```

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 任务 ID。 |
| `<text...>` | 评论内容。 |
| `--author <author>` | 评论作者；默认 `$HERMES_PROFILE` 或 `user`。 |

### `tail`

```bash
hermes kanban tail <task_id> [--interval <seconds>]
```

跟踪单个任务事件流。

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 任务 ID。 |
| `--interval <seconds>` | 轮询间隔。 |

### `watch`

```bash
hermes kanban watch [--assignee <profile>] [--tenant <tenant>] [--kinds <kinds>] [--interval <seconds>]
```

实时查看 task_events，按 `Ctrl+C` 退出。

| 参数 | 功能 |
| --- | --- |
| `--assignee <profile>` | 只显示分配给该 profile 的任务事件。 |
| `--tenant <tenant>` | 只显示该 tenant 的任务事件。 |
| `--kinds <kinds>` | 只显示指定事件类型，逗号分隔，例如 `completed,blocked,gave_up,crashed,timed_out`。 |
| `--interval <seconds>` | 轮询间隔，默认 `0.5` 秒。 |

## 日志、运行记录与统计

### `log`

```bash
hermes kanban log <task_id> [--tail <bytes>]
```

打印任务 worker 日志，日志来源于 `<kanban-root>/kanban/logs/`。

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 任务 ID。 |
| `--tail <bytes>` | 只打印最后 N 字节。 |

### `runs`

```bash
hermes kanban runs <task_id> [--json]
```

显示任务尝试历史，包括 profile、结果、耗时、summary。

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 任务 ID。 |
| `--json` | JSON 输出。 |

### `stats`

```bash
hermes kanban stats [--json]
```

显示各状态、各 assignee 的任务数量，以及最老 ready 任务年龄。

### `assignees`

```bash
hermes kanban assignees [--json]
```

列出已知 profile 及每个 profile 的任务数量。来源包括 `~/.hermes/profiles/` 和当前 board 中出现过的 assignee。

## 诊断

### `diagnostics` / `diag`

```bash
hermes kanban diagnostics [--severity <level>] [--task <task_id>] [--json]
```

| 参数 | 功能 |
| --- | --- |
| `--severity <level>` | 只显示指定及以上严重级别：`warning`、`error`、`critical`。 |
| `--task <task_id>` | 只显示指定任务的诊断。 |
| `--json` | JSON 输出。 |

## 通知订阅

### `notify-subscribe`

```bash
hermes kanban notify-subscribe <task_id> --platform <platform> --chat-id <chat_id> [--thread-id <thread_id>] [--user-id <user_id>]
```

订阅某任务的 gateway 终端事件，常用于 gateway adapter 的 `/kanban subscribe`。

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 任务 ID。 |
| `--platform <platform>` | 平台名。 |
| `--chat-id <chat_id>` | 聊天 ID。 |
| `--thread-id <thread_id>` | 线程 ID。 |
| `--user-id <user_id>` | 用户 ID。 |

### `notify-list`

```bash
hermes kanban notify-list [task_id] [--json]
```

| 参数 | 功能 |
| --- | --- |
| `[task_id]` | 可选；只列出单个任务的订阅。 |
| `--json` | JSON 输出。 |

### `notify-unsubscribe`

```bash
hermes kanban notify-unsubscribe <task_id> --platform <platform> --chat-id <chat_id> [--thread-id <thread_id>]
```

取消任务事件订阅。

| 参数 | 功能 |
| --- | --- |
| `<task_id>` | 任务 ID。 |
| `--platform <platform>` | 平台名。 |
| `--chat-id <chat_id>` | 聊天 ID。 |
| `--thread-id <thread_id>` | 线程 ID。 |

## 清理

### `gc`

```bash
hermes kanban gc [--event-retention-days <days>] [--log-retention-days <days>]
```

垃圾回收已归档任务 workspace、旧事件和旧日志。

| 参数 | 功能 |
| --- | --- |
| `--event-retention-days <days>` | 删除 terminal 任务中早于 N 天的 `task_events`；默认 `30`。 |
| `--log-retention-days <days>` | 删除早于 N 天的 worker 日志文件；默认 `30`。 |
