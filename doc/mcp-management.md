# MCP 管理功能设计方案

> 目标:为每个 agent 配置其专属的 MCP server(例如给"设计助手"装 Figma MCP,给"前端助手"装 Playwright MCP)。支持查看、新增、编辑、删除、连通性测试。Leader 通过 `list_workers()` 能看到每个 worker 已安装的 MCP 摘要,据此做能力感知派发。

与 [skills-management.md](skills-management.md) 类比:**skills 是 agent 学到的知识/流程**,**MCP 是 agent 获得的外部工具接入**。两者正交,机制相近。

## 0. 已确认决策

- `yaml 有但 DB 无` 的外部 MCP:列表展示为 `source_type="external"`,允许测试/删除;编辑保存时补写 DB,转为平台可管理。
- HTTP MCP URL:允许公网、私网、回环地址,不做默认拦截。
- stdio command:不做白名单限制,任意命令都允许保存;UI 仅做风险提示。
- Secret reveal:`?reveal=1` 在当前登录会话内直接返回明文。
- Secret 显示交互:前端点击“显示”时需要二次确认,确认后再请求 `?reveal=1`;后端仍按当前登录会话返回明文。
- 编辑 secret:未提交字段保留原值;提交空字符串表示清空。
- 生效时机:一期实现“重启 worker”按钮,接入现有 restart 能力;保存配置后提示用户重启 worker 后生效。
- `agent_bus`:在 UI 列表展示,标记 `builtin/平台托管`,禁止编辑和删除。
- HTTP 连通性测试:仅 `2xx/3xx` 算成功;`401/404` 算失败,但 detail 提示“网络可达”。
- HTTP 连通性测试请求策略:先 `HEAD`,遇到 `405/403` 或请求异常时再降级尝试 `GET`。
- stdio 连通性测试:真实启动本机命令并执行 MCP `initialize` 握手;前端调用测试前必须二次确认“将执行本机命令”。
- yaml 有但 DB 无的 external MCP 删除:只从 `config.yaml` 删除,不补写 DB 历史记录。
- 同名 MCP 新增:如果 `config.yaml` 已存在但 DB 无记录,前端提示“检测到外部 MCP”,由用户选择“接管编辑”或取消。
- stdio `args`:API 只接受字符串数组;前端使用“一行一个参数”的输入方式。
- `list_workers()` 的 `mcps`:只返回 `{name, transport, description, source_type}`,不暴露 url/header/env 或 secret 摘要。

---

## 1. 范围与边界

### 1.1 要做
- 管理每个 agent 的 MCP servers 列表(基于 Hermes profile `config.yaml` 的 `mcp_servers` 节)
- 支持两种传输类型:
  - **HTTP/SSE**:`url`(+ 可选 `headers`,含 token)
  - **stdio**:`command` + `args` + `env`
- 新增 / 编辑 / 删除单个 MCP
- 连通性测试(HTTP: HEAD/GET;stdio: 启动后 `initialize` 握手,超时杀掉)
- 保护平台自管的 `agent_bus` 条目,UI/API 禁止修改或删除
- Leader 端 `list_workers()` 返回每个 worker 已安装的 MCP 摘要

### 1.2 不做
- 不代理执行 MCP 调用(Hermes 自己接)
- 不做 OAuth 流程(token/secret 由用户粘贴)
- 不做 MCP marketplace 协议
- 不做内置模板库(一期全部手动填写;未来再加)
- 不做跨 agent 的策略继承(每个 agent 独立维护)
- 不做启用/禁用开关(不需要就直接删除,需要时再重新安装)
- 不做运行时指标(调用次数、延迟等)

---

## 2. 存储布局与数据模型

### 2.1 真相源:Hermes profile 的 config.yaml

```yaml
# ~/.hermes/profiles/<profile>/config.yaml 的 mcp_servers 节
# 平台写入的条目始终带 enabled: true(Hermes 配置模型的必填字段);
# 本平台不暴露启用/禁用开关,要取消使用就删除该条目。
mcp_servers:
  agent_bus:                                 # 平台内置,保护
    url: http://127.0.0.1:5050/mcp/
    enabled: true
  figma:                                     # 用户安装
    url: https://mcp.figma.com/sse
    enabled: true
    headers:
      Authorization: "Bearer figd_xxx"
  playwright:
    command: npx
    args: ["-y", "@playwright/mcp@latest"]
    env:
      PWDEBUG: "1"
    enabled: true
```

Hermes 本身已解析这个节点(见现有 `profiles.attach_mcp_server`)。平台做的只是**以结构化方式增删这个字典**,外加一层元数据记录。

### 2.2 命名规则

- `name` 作为字典 key,正则 `^[a-z0-9][a-z0-9_-]{0,40}$`
- 保留名(禁止用户占用): `agent_bus`

### 2.3 DB 表:元数据(用于 UI 展示)

新增到 [app/db/models.py](../app/db/models.py):

```python
class AgentMcpServerRecord(TimestampMixin, Base):
    __tablename__ = "agent_mcp_servers"
    __table_args__ = (UniqueConstraint("profile_name", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_name: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(80))
    transport: Mapped[str] = mapped_column(String(16))   # "http" | "stdio"
    source_type: Mapped[str] = mapped_column(String(20), default="manual")  # manual | builtin
    description: Mapped[str] = mapped_column(Text, default="")
    managed: Mapped[bool] = mapped_column(Boolean, default=False)  # 平台托管,禁止 UI 改(agent_bus)
    last_test_status: Mapped[str] = mapped_column(String(16), default="")   # ok | fail | ""
    last_test_at: Mapped[str] = mapped_column(String(40), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
```

**文件 + DB 分工** (和 skills 一致):
- config.yaml 决定"是否生效"(Hermes 真正读它)
- DB 决定"从哪来、最近一次测试结果、描述"(UI 呈现用)
- 用户手改 config.yaml 加的 MCP → yaml 有但 DB 无 → 列表上报 `source_type="external"`,允许测试/删除;编辑保存时补写 DB,转为平台可管理

### 2.4 敏感字段处理

- `headers.Authorization` / `env.*_TOKEN` / `env.*_KEY` 等识别为 secret
- GET 返回时默认 mask 为 `****`(保留长度提示);UI 有"显示"按钮走 `?reveal=1`(同一会话权限内)
- 编辑时未提交的 secret 字段保留原值;提交空字符串表示清空
- 不把 secret 写入 DB,只写在 config.yaml(与现有 `attach_mcp_server` 行为一致)

---

## 3. 服务层模块

### 3.1 新增文件:`app/services/mcp_installer.py`

```python
def list_installed(profile_name: str) -> list[dict]
def get_mcp(profile_name: str, name: str, *, reveal_secrets: bool=False) -> dict | None

def add_mcp(agent_id, *, name, transport, url=None, headers=None,
            command=None, args=None, env=None,
            description="") -> dict
def update_mcp(agent_id, name, *, patch: dict) -> dict
def remove_mcp(agent_id, name) -> None

def test_mcp(agent_id, name, *, timeout=15) -> dict
```

### 3.2 config.yaml 读写

复用现有 [profiles.py](../app/services/profiles.py) 的 yaml 读写 pattern,抽两个辅助:

```python
# app/services/profiles.py 追加
def read_profile_config(profile_name: str) -> dict
def write_profile_config(profile_name: str, data: dict) -> None
def upsert_mcp_server(profile_name: str, name: str, spec: dict) -> None
def remove_mcp_server(profile_name: str, name: str) -> None
```

所有写入采用"读→改→原子落盘"(写临时文件 + `os.replace`)避免 config.yaml 损坏。

### 3.3 受保护条目

`agent_bus` 条目:
- 建表时由创建 agent 流程写入(现已是),同时在 DB 插入 `managed=True`
- `update/remove` 遇到 `managed=True` → 返回 400 "agent_bus is platform-managed"

### 3.4 连通性测试

| 传输 | 做法 |
|---|---|
| http | `httpx.head(url, timeout=10)` + 把自定义 headers 带上;仅 2xx/3xx 视为成功;401/404 视为失败,但 detail 提示"网络可达" |
| stdio | `subprocess.Popen(command, args, env)`,stdin 写 `initialize` JSON-RPC,stdout 读响应;超时 15s,结束后 kill |

HTTP 测试优先使用 `HEAD`;如果遇到 `405/403` 或请求异常,自动降级尝试 `GET`。stdio 测试会真实执行本机命令,前端在调用测试接口前必须二次确认风险。

测试结果写回 DB 的 `last_test_status / last_test_at / last_error`。

---

## 4. 安全护栏

### 4.1 URL 校验(复用 skill_installer)
HTTP MCP 允许公网、私网、回环地址,不做默认拦截;仅校验 URL 格式和 scheme。

### 4.2 stdio 命令风险提示

- 不做 command 白名单限制,任意命令都允许保存
- UI 对 stdio MCP 展示风险提示:"stdio MCP 会在本机执行命令,请确认来源可信"
- 这类 MCP 完全在用户本机跑,本质等同 shell,由用户自担

### 4.3 Secret 处理
- 不进日志、不进 SSE 事件体、不进 DB
- UI 编辑页的 headers/env 字段:类型标注为 `secret` 的走掩码输入
- UI 点击“显示”secret 时先二次确认,确认后调用 `?reveal=1` 获取明文
- 导出 agent 配置(未来功能)默认脱敏

### 4.4 config.yaml 原子写
- 写 `config.yaml.tmp` → `fsync` → `os.replace`
- 任一步失败 → 原文件保留

---

## 5. API 层

### 5.1 新增蓝图 `app/controllers/agent_mcps.py`,注册到 `app/__init__.py`

### 5.2 端点

| 方法 | 路径 | Body / Query | 返回 |
|---|---|---|---|
| GET | `/api/agents/<agent_id>/mcps` | `?reveal=0` | `{ok, mcps:[...]}` |
| GET | `/api/agents/<agent_id>/mcps/<name>` | `?reveal=1` | `{ok, mcp:{...}}` |
| POST | `/api/agents/<agent_id>/mcps` | `{name, transport, url?, headers?, command?, args?, env?, description?}` | `{ok, mcp}` |
| PUT | `/api/agents/<agent_id>/mcps/<name>` | 同上的 patch | `{ok, mcp}` |
| POST | `/api/agents/<agent_id>/mcps/<name>/test` | - | `{ok, status:"ok"\|"fail", detail}` |
| DELETE | `/api/agents/<agent_id>/mcps/<name>?confirm=1` | - | `{ok}` |

### 5.3 异步?

与 skills 安装不同,MCP 增删只是 config.yaml 修改,是**同步**的,< 100ms 完成。仅 `test` 端点可能耗时到 15s,仍用同步 HTTP(前端 loading) 即可,不引入 job 模型。

### 5.4 错误码

| HTTP | 场景 |
|---|---|
| 400 | 名称非法 / transport 字段缺失 / 改动 managed 条目 |
| 404 | agent / mcp 不存在 |
| 409 | 同名已存在(新增时) |
| 422 | url/headers/args/env 字段不合法 |
| 500 | yaml 写入失败 |

### 5.5 Hermes 生效时机

修改 `config.yaml` 后,**正在运行的 agent 进程不会自动重载** MCP 列表。两种处理:
1. **轻量**:在返回体附 `"requires_restart": true`,UI 显示 "修改将在下次对话生效"
2. **重启**:增加按钮 "重启 worker" → 调现有 `acp.pool.restart(agent_id)`

一期选方案 2:实现"重启 worker"按钮,保存 MCP 配置后提示用户重启 worker 后生效。

---

## 6. Leader 能力感知

`list_workers()`([app/mcp_server.py](../app/mcp_server.py)) 已附 `skills`,平行追加 `mcps`:

```python
from .services import mcp_installer
item["mcps"] = mcp_installer.mcp_summary(agent["profile_name"])
# 每项: {name, transport, description, source_type}
```

只排除 `agent_bus`(leader 不关心团队总线本身),其余条目全部返回,描述用于派发决策。这里不返回 `url` / `headers` / `env`,也不返回 secret 摘要。

---

## 7. 前端设计([app/templates/index.html](../app/templates/index.html))

### 7.1 入口
Agent 详情抽屉新增 **MCP** tab,位置放在 Skills 之后。

### 7.2 列表布局

```
┌────────────────────────────────────────────────────────────────┐
│  MCP Servers (3 已安装)                       [+ 新增 MCP ]     │
├────────────────────────────────────────────────────────────────┤
│ ● figma               [http]                     [测试:✓]      │
│   Figma 设计文件访问                                            │
│   https://mcp.figma.com/sse · Auth: ****                       │
│   [编辑] [测试] [删除]                                          │
│ ─────────────────────────────────────────────────────────────── │
│ ● playwright          [stdio]                    [未测试]      │
│   浏览器自动化                                                  │
│   npx -y @playwright/mcp@latest                                │
│   [编辑] [测试] [删除]                                          │
│ ─────────────────────────────────────────────────────────────── │
│ 🔒 agent_bus          [http] [builtin]                         │
│   平台团队总线(不可修改)                                       │
└────────────────────────────────────────────────────────────────┘
```

### 7.3 新增弹窗

顶部 Tab 切换 `http` / `stdio`:

- http:name / url / headers(key-value 列表) / description
- stdio:name / command / args(字符串数组输入) / env(kv) / description

底部按钮 `[测试后保存]` 与 `[直接保存]`。

### 7.4 删除 确认

- `agent_bus` 按钮置灰,hover 提示 "平台托管"
- 其他删除走二次确认,文案 "将从 `<profile>/config.yaml` 移除此 MCP 条目,下次对话生效"

---

## 8. agent 生命周期联动

### 8.1 创建 agent
现有 [agents.py:63](../app/services/agents.py#L63) 已调 `attach_mcp_server(..., "agent_bus", ...)`,补一步:在 DB 里写一条 `managed=True, source_type="builtin"` 的 `agent_bus` 记录,便于 UI 区分。

### 8.2 删除 agent
现有流程删 profile 目录。追加清理 DB:

```python
with SessionLocal() as db:
    db.query(AgentMcpServerRecord).filter_by(profile_name=profile_name).delete()
    db.commit()
```

### 8.3 建表
沿用 `Base.metadata.create_all()` 自动建新表,不引入 migration。

---

## 9. 测试点

### 9.1 单元 / 集成(`tests/`)
- `test_mcp_add_http`:http MCP 写入 config.yaml,DB 有记录,`list` 能读到
- `test_mcp_add_stdio_any_command`:任意 stdio command 都可保存,无需 `allow_unsafe`
- `test_mcp_protect_builtin`:尝试修改 `agent_bus` → 400
- `test_mcp_remove`:删除后 yaml 里无该 key,DB 记录清除
- `test_mcp_test_http_reachable`:mock httpx 验证 2xx / 超时 / 连错
- `test_mcp_test_stdio_handshake`:mock Popen,验证 initialize 握手
- `test_secret_mask`:GET 默认掩码,`?reveal=1` 原值
- `test_atomic_write`:写入中途失败 → config.yaml 原文保留

### 9.2 手工验收
- 给一个 worker 装上 Figma MCP(http + PAT),`hermes -p <worker>` 启动后 `/tools` 能看到 figma 工具
- `list_workers()` 返回 `mcps:[{name:"figma",...}]`
- Leader 可以在 SOUL/上下文里感知到"这个 worker 有 figma 工具",派单更合理
- 删除后重启 worker,Figma 工具消失

---

## 10. 实施计划

| PR | 范围 | 估时 |
|---|---|---|
| **PR1** | DB model + `mcp_installer` CRUD + config.yaml 读写 + 保护条目 + 单测 | 1 天 |
| **PR2** | 测试端点 + API 蓝图 + `list_workers()` 增强 | 0.5 天 |
| **PR3** | 前端 MCP tab + 手动新增/编辑弹窗 + 测试/删除 | 1 天 |

合计:约 2.5 天。

---

## 11. 未决 / 未来扩展

- **OAuth 流程**:一期让用户粘贴 token;后续对 Figma/GitHub/Slack 等接标准 OAuth device flow
- **批量操作**:"把此 MCP 复制到其他 agent"(纯前端批量调 add)
- **运行时指标**:每个 MCP 的调用次数、错误率(需 Hermes 侧上报 hook,暂缓)
- **热重载**:Hermes 侧若支持 config.yaml 热重载 MCP 列表,则去掉"下次对话生效"提示
- **内置模板库**:预置 Figma / GitHub / Playwright / Filesystem / Slack 等常用 MCP,一键填 token 即装(backend 出 `/api/mcp-templates`,前端加"从模板新增"入口)
- **策略模板**:团队级"默认 MCP 组合",新建 agent 时勾选即装

---

## 附录 A:关键文件清单

| 文件 | 动作 |
|---|---|
| `app/db/models.py` | 新增 `AgentMcpServerRecord` |
| `app/services/profiles.py` | 追加 `read/write_profile_config` / `upsert_mcp_server` / `remove_mcp_server` |
| `app/services/mcp_installer.py` | **新文件**:全部 CRUD / test 逻辑 |
| `app/services/agents.py` | `create_agent` 末尾写入 `agent_bus` 的 DB 记录;`delete_agent` 清 DB |
| `app/controllers/agent_mcps.py` | **新文件**:REST 蓝图 |
| `app/__init__.py` | 注册新蓝图 |
| `app/mcp_server.py` | `list_workers()` 增加 `mcps` 字段 |
| `app/templates/index.html` | 新增 MCP tab + 弹窗 + JS/CSS |
| `tests/test_mcp_installer.py` | **新文件** |

---

## 附录 B:示例 API 调用序列

```bash
# 1. 新增 Figma MCP
curl -X POST http://localhost:5000/api/agents/agent_designer/mcps \
  -H 'Content-Type: application/json' \
  -d '{"name":"figma","transport":"http","url":"https://mcp.figma.com/sse","headers":{"Authorization":"Bearer figd_xxx"},"description":"Figma 设计文件访问"}'
# → {"ok":true,"mcp":{"name":"figma","transport":"http",...}}

# 2. 列出
curl http://localhost:5000/api/agents/agent_designer/mcps
# → {"ok":true,"mcps":[{"name":"agent_bus","managed":true,...},{"name":"figma",...}]}

# 3. 连通性测试
curl -X POST http://localhost:5000/api/agents/agent_designer/mcps/figma/test
# → {"ok":true,"status":"ok","detail":"2xx from https://mcp.figma.com/sse"}

# 4. 删除
curl -X DELETE 'http://localhost:5000/api/agents/agent_designer/mcps/figma?confirm=1'
```
