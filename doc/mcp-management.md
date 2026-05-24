# MCP 管理实现说明

本文档说明当前项目中 Agent MCP servers 的实际实现。MCP 配置按 agent 对应的 Hermes profile 隔离，最终写入该 profile 的 `config.yaml`。

## 1. 当前能力

- 管理每个 agent 的 MCP servers 列表。
- 支持 `http`、`streamable_http`、`stdio` 三种 transport。
- 新增、编辑、删除单个 MCP。
- 测试 MCP 连通性。
- 保护平台托管的 `agent_bus`，禁止编辑和删除。
- `list_workers()` 返回 worker 已安装的 MCP 摘要，供 Leader 做能力感知。

暂不支持：

- OAuth 流程。
- MCP marketplace。
- 内置模板库。
- 启用/禁用开关。
- MCP 调用指标统计。

## 2. 存储布局

真相源是 Hermes profile 的 `config.yaml`：

```yaml
mcp_servers:
  agent_bus:
    url: http://127.0.0.1:5050/mcp/
    enabled: true
  figma:
    url: https://mcp.figma.com/sse
    enabled: true
    headers:
      Authorization: "Bearer figd_xxx"
  remote_http:
    transport: streamable_http
    url: https://mcp.example.com/mcp
    enabled: true
  playwright:
    command: npx
    args: ["-y", "@playwright/mcp@latest"]
    env:
      PWDEBUG: "1"
    enabled: true
```

数据库表 `agent_mcp_servers` 记录 UI 元数据：

- `profile_name`
- `name`
- `transport`
- `source_type`
- `description`
- `managed`
- `last_test_status`
- `last_test_at`
- `last_error`

分工：

- `config.yaml` 决定 MCP 是否真正生效。
- DB 记录来源、描述和最近一次测试结果。
- 用户手动写入 `config.yaml` 的 MCP 会以 `source_type="external"` 展示；编辑保存时会补写 DB，转为平台可管理。

## 3. 关键文件

| 文件 | 作用 |
| --- | --- |
| `argos/controllers/agent_mcps.py` | MCP REST API |
| `argos/services/mcp_installer.py` | MCP 列表、CRUD、测试、摘要 |
| `argos/services/profiles.py` | profile config.yaml 原子读写 |
| `argos/services/agents.py` | leader 创建时写入 `agent_bus`，删除 agent 时清理 MCP 记录 |
| `argos/mcp_server.py` | `list_workers()` 返回 `mcps` 摘要 |
| `tests/test_mcp_installer.py` | MCP 管理测试 |

## 4. API

| 方法 | 路径 | Body / Query | 返回 |
| --- | --- | --- | --- |
| GET | `/api/agents/<agent_id>/mcps` | `?reveal=0/1` | `{ok, mcps, agent}` |
| GET | `/api/agents/<agent_id>/mcps/<name>` | `?reveal=0/1` | `{ok, mcp}` |
| POST | `/api/agents/<agent_id>/mcps` | `{name, transport, url?, headers?, command?, args?, env?, description?, takeover?}` | `{ok, mcp, requires_restart}`，状态码 `201` |
| PUT | `/api/agents/<agent_id>/mcps/<name>` | patch | `{ok, mcp, requires_restart}` |
| POST | `/api/agents/<agent_id>/mcps/<name>/test` | - | `{ok, status, detail}` |
| DELETE | `/api/agents/<agent_id>/mcps/<name>?confirm=1` | - | `{ok, requires_restart}` |
| POST | `/api/agents/<agent_id>/restart` | - | 重启 agent runtime |

删除接口当前要求 `confirm=1`。

常见错误：

| HTTP | 场景 |
| --- | --- |
| 400 | 名称非法、transport 缺失或修改 managed 条目 |
| 404 | agent / mcp 不存在 |
| 409 | 同名已存在，或检测到 external MCP 需要 takeover |
| 422 | url / headers / args / env 字段不合法 |
| 500 | config.yaml 写入或测试过程异常 |

## 5. Transport 规则

名称规则：

```text
^[a-z0-9][a-z0-9_-]{0,40}$
```

保留名：

```text
agent_bus
```

transport：

| transport | 配置字段 | 说明 |
| --- | --- | --- |
| `http` | `url`、`headers?` | 写入 config.yaml 时不额外保存 `transport` 字段 |
| `streamable_http` | `url`、`headers?`、`transport` | 用于区分 Streamable HTTP MCP |
| `stdio` | `command`、`args?`、`env?` | 会在测试时真实启动本机命令 |

`args` 必须是字符串数组，`headers` 和 `env` 必须是对象，值会转成字符串。

## 6. Secret 处理

识别为 secret 的 key：

```text
authorization / token / secret / key / password
```

默认 GET 会脱敏：

```text
abcdef123456 -> ab****56
```

传 `?reveal=1` 会返回明文。secret 不写入 DB，只保存在 `config.yaml`。编辑时：

- 未提交字段保留原值。
- 提交空字符串表示删除该 key。
- 提交原掩码值会保留原 secret。

## 7. 连通性测试

HTTP / Streamable HTTP：

1. 先发 `HEAD`，带上 headers。
2. 如果遇到 `403`、`405` 或请求异常，再尝试 `GET` stream。
3. `2xx/3xx` 视为成功。
4. `401/404/406` 视为失败，但 detail 会提示“网络可达但协议/权限未通过”。

stdio：

1. 启动 `command + args`。
2. 通过 stdin 发送 MCP `initialize` JSON-RPC。
3. 读取 stdout 第一行响应。
4. 超时或进程异常会返回失败。
5. 测试结束后 kill 进程。

测试结果会写回 DB 的 `last_test_status`、`last_test_at`、`last_error`。

## 8. agent_bus

创建 leader agent 时，`argos/services/agents.py` 会：

1. 调用 `profiles.attach_mcp_server(...)` 写入 `agent_bus`。
2. 调用 `mcp_installer.upsert_builtin_agent_bus(...)` 写入 DB 记录。
3. 将其标记为 `source_type="builtin"`、`managed=True`。

`agent_bus` 在 API 和 UI 中展示，但不能编辑、测试配置变更或删除。

## 9. Leader 能力感知

`list_workers()` 会为 worker 返回 MCP 摘要：

```json
{
  "mcps": [
    {
      "name": "figma",
      "transport": "http",
      "description": "Figma 设计文件访问",
      "source_type": "manual"
    }
  ]
}
```

摘要不包含 `url`、`headers`、`env` 或 secret。`agent_bus` 不会出现在摘要中。

## 10. 生效时机

新增、编辑、删除 MCP 都会修改 profile 的 `config.yaml`，返回 `requires_restart: true`。

正在运行的 agent 进程不会自动热重载 MCP 列表，需要调用：

```text
POST /api/agents/<agent_id>/restart
```

或等下次启动时生效。

## 11. 示例

新增 HTTP MCP：

```bash
curl -X POST http://127.0.0.1:5050/api/agents/agent_designer/mcps \
  -H 'Content-Type: application/json' \
  -d '{"name":"figma","transport":"http","url":"https://mcp.figma.com/sse","headers":{"Authorization":"Bearer figd_xxx"},"description":"Figma 设计文件访问"}'
```

新增 Streamable HTTP MCP：

```bash
curl -X POST http://127.0.0.1:5050/api/agents/agent_designer/mcps \
  -H 'Content-Type: application/json' \
  -d '{"name":"remote","transport":"streamable_http","url":"https://mcp.example.com/mcp","description":"远程 Streamable HTTP MCP"}'
```

列出：

```bash
curl http://127.0.0.1:5050/api/agents/agent_designer/mcps
```

测试：

```bash
curl -X POST http://127.0.0.1:5050/api/agents/agent_designer/mcps/figma/test
```

删除：

```bash
curl -X DELETE 'http://127.0.0.1:5050/api/agents/agent_designer/mcps/figma?confirm=1'
```
