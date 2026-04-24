# Hermes 多 Agent 协作系统 — 架构设计

## 目标

基于 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的 profile 机制,构建一个多 agent 相互协作的 Web 系统:

- **后端**:Flask,作为 agent 之间的通信枢纽
- **前端**:实时展示多 agent 对话过程
- **agent**:每个 agent 是一个独立的 Hermes profile,拥有独立记忆、技能、人设
- **领导者 agent**:负责拆解任务、选择合适的执行 agent、汇总结果
- **通信**:agent 之间**不直接对话**,通过 Flask 中转

---

## 核心概念

### 1. Hermes Profile = 一个独立 Agent

Hermes 的 `profile` 机制允许在同一台机器运行多个独立的 agent 实例:

```bash
hermes profile create analyst     # 数据分析 agent
hermes profile create writer      # 报告撰写 agent
hermes profile create reviewer    # 审核 agent
```

每个 profile 拥有独立的:
- `config.yaml` — 模型、工具集配置
- `.env` — API keys
- `SOUL.md` — 人设与行为指令
- 记忆、会话历史、技能、cron 任务

详见 [Profiles: Running Multiple Agents](https://hermes-agent.nousresearch.com/docs/user-guide/profiles)。

### 2. 两个协议的分工

| 协议 | 方向 | 用途 |
|------|------|------|
| **MCP** (Model Context Protocol) | agent → Flask | LLM 调用"发消息"工具 |
| **ACP** (Agent Communication Protocol) | Flask → agent | 程序驱动 agent 工作 |

**关键理解**:
- **MCP** 是给 LLM 用的 — agent 的 LLM 原生理解 `tool_use`,Flask 把"给其他 agent 发消息"暴露为一个 MCP tool,LLM 自然会调
- **ACP** 是给程序用的 — Flask 不是 LLM,需要确定性的 RPC 接口来驱动 agent,ACP 正好解决这个问题(JSON-RPC over stdio,支持流式、多轮会话、工具调用可见、反向权限请求)

### 3. 为什么 agent 不直接互相通信

- 每个 profile 是**独立进程**,不共享内存
- 直接 HTTP 互调会导致死锁、难追踪、前端无法观察
- Flask 中转的好处:集中路由、统一日志、前端可实时监听

### 4. Leader Agent + Specialist Agent

在更接近真实协作的场景里,推荐把 agent 分成两类:

- **leader agent**:面向用户,负责理解总任务、拆分子任务、选择执行者、汇总最终结果
- **specialist agent**:面向具体能力,例如 analyst / writer / reviewer / researcher

leader **不自己执行所有细节工作**,而是像项目经理一样调度其他 agent。

### 5. Agent Registry:让 leader 知道"有哪些 agent 可以用"

leader 不应该只靠 prompt 记忆有哪些 agent,也不应该逐个去问"你能做什么"。

更稳的做法是:由 Flask 维护一份**Agent Registry**,作为系统唯一可信的数据源。

每个 agent 在注册表里至少包含:

- `agent_id` — 唯一标识
- `name` — 展示名
- `role` — 角色,如 leader / analyst / writer / reviewer
- `description` — 一句话职责说明
- `skills` — 能力标签,如 `analysis`, `writing`, `review`
- `input_types` — 能接受的任务类型
- `output_types` — 能产出的结果类型
- `constraints` — 限制条件,如"不能联网"、"只做总结"
- `status` — online / busy / offline
- `current_load` — 当前负载
- `priority` — 默认优先级

**关键点**:

- leader 通过 **MCP tool 读取 Flask 的注册表**
- 真实数据源是 Flask 的 registry,不是 leader 自己猜,也不是其他 agent 临时自报
- 这样 agent 动态上下线、扩缩容时,leader 的决策仍然稳定

---

## 数据流

### 用户发起对话

```
[前端]                [Flask]               [agent_a 的 ACP server]
   │                    │                         │
   │ POST /api/send ──> │                         │
   │                    │ ─ ACP prompt ────────> │
   │                    │                         │ (agent_a 开始工作)
   │                    │ <─ session/update ───  │ 流式 chunk
   │ <─ SSE ──────────  │ <─ session/update ───  │ tool_use 事件
   │                    │ <─ result ───────────  │ 完成
```

### Agent A 调用工具给 Agent B 发消息

```
[agent_a]            [Flask]             [agent_b]
   │                    │                    │
   │ ① LLM 决定调用     │                    │
   │    tool_use:       │                    │
   │    send_to(b, "…") │                    │
   │                    │                    │
   │ ② MCP call ──────> │                    │
   │                    │ ③ ACP prompt ────> │
   │                    │                    │ ④ b 开始工作
   │ <─ MCP result ──── │                    │   流式返回
   │   ("已发送")       │                    │
   │                    │ <─ ACP events ──── │
   │                    │ (推送到前端)       │
```

### Leader 分配任务给 Specialist

```
[用户]               [leader]            [Flask]            [specialist]
   │                    │                    │                    │
   │ ① 提出总任务       │                    │                    │
   │ ─────────────────> │                    │                    │
   │                    │ ② MCP:list_agents  │                    │
   │                    │ ─────────────────> │                    │
   │                    │ <───────────────── │  返回可用 agent    │
   │                    │                    │                    │
   │                    │ ③ 拆分子任务       │                    │
   │                    │ ④ MCP:delegate_task│                    │
   │                    │ ─────────────────> │                    │
   │                    │                    │ ⑤ ACP prompt ────> │
   │                    │ <───────────────── │  已投递            │
   │                    │                    │                    │
   │                    │                    │ <─ ACP events ──── │
   │                    │ ⑥ 收到结果/进度     │                    │
   │                    │ ⑦ 汇总并回复用户     │                    │
```

### 如何让 A 收到 B 的回复

B 处理完后,Flask **主动** 对 A 发一条 ACP prompt:

```python
acp_clients["agent_a"].prompt(f"[来自 agent_b]: {reply}")
```

这样 A 的下一轮对话自然看到 B 的回复,继续推进协作。

---

## 系统架构图

```
┌─────────────────────────────────────────────────────────┐
│                        前端 (Web)                        │
│  - 对话展示 / 用户输入                                   │
│  - EventSource 订阅 SSE                                  │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP / SSE
                        ▼
┌─────────────────────────────────────────────────────────┐
│                   Flask 后端 (核心枢纽)                  │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │  HTTP API    │  │  MCP Server  │  │  SSE 广播     │ │
│  │ /api/send    │  │ list_agents  │  │ /api/stream   │ │
│  │ /api/agents  │  │ delegate_task│  │               │ │
│  └──────┬───────┘  │ send_to_agent│  └───────┬───────┘ │
│         │          └──────┬───────┘          │         │
│         └─────────┬───────┴──────────────────┘         │
│                   │                                     │
│      ┌────────────▼────────────┐                        │
│      │  Agent Registry         │                        │
│      │  + 消息路由器            │                        │
│      │  + ACP 客户端池          │                        │
│      └────────────┬────────────┘                        │
└───────────────────┼─────────────────────────────────────┘
                    │ JSON-RPC (ACP over stdio)
         ┌──────────┼──────────┬──────────┬──────────┐
         ▼          ▼          ▼          ▼          ▼
   ┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐
   │ hermes  ││ hermes  ││ hermes  ││ hermes  ││ hermes  │
   │ -p      ││ -p      ││ -p      ││ -p      ││ -p …    │
   │ leader  ││ analyst ││ writer  ││reviewer ││         │
   │ acp     ││ acp     ││ acp     ││ acp     ││         │
   └─────────┘└─────────┘└─────────┘└─────────┘└─────────┘
     各自独立的记忆、技能、人设、配置
```

---

## 实施步骤

### Step 1:创建多个 Profile

```bash
hermes profile create leader
hermes profile create analyst
hermes profile create writer
hermes profile create reviewer

# 为每个 profile 配置人设
cat > ~/.hermes/profiles/leader/SOUL.md <<EOF
你是领导者 agent。
你的职责是理解用户目标,拆分子任务,调用 MCP 工具查询当前可用 agent,
然后把子任务分配给最合适的 specialist agent,最后汇总结果回复用户。
不要假设系统里有哪些 agent,先调用 list_agents 再决策。
EOF

cat > ~/.hermes/profiles/analyst/SOUL.md <<EOF
你是数据分析 agent。
你只负责分析类子任务,不负责总调度。
EOF
```

### Step 2:配置每个 Profile 的 MCP Server

让每个 profile 连接到 Flask 暴露的 MCP 端点:

```yaml
# ~/.hermes/profiles/analyst/config.yaml
mcp:
  servers:
    agent_bus:
      url: http://localhost:5000/mcp
```

### Step 3:Flask 后端实现

Flask 需要同时承担四个角色:

**3.1 Agent Registry** — 维护所有 agent 的身份、能力、状态、负载

可以理解为一个内存版的"调度目录":

```python
agent_registry = {
    "leader": {
        "role": "leader",
        "skills": ["planning", "delegation", "summary"],
        "status": "online",
    },
    "analyst": {
        "role": "analyst",
        "skills": ["analysis", "reasoning"],
        "status": "online",
    },
}
```

leader 的 agent 信息来源应该是这里,而不是写死在 prompt 里。

**3.2 MCP Server** — 暴露查询和委派工具给各 agent,尤其是 leader

```python
@mcp_server.tool("list_agents")
def list_agents(role: str | None = None, only_available: bool = True):
    ...

@mcp_server.tool("delegate_task")
def delegate_task(
    to: str,
    task_type: str,
    content: str,
    expected_output: str,
    _from: str,
) -> str:
    acp_clients[to].prompt(
        f"[委派任务][来自 {_from}][类型 {task_type}]: {content}",
        on_event=lambda ev: broadcast_to_frontend(ev)
    )
    return f"已发送给 {to}"   # 立即返回,不等 B 回复完
```

`send_to_agent` 仍然可以保留,用于普通 agent 间简单传话;
但对 leader 来说,更推荐使用语义更明确的 `list_agents` + `delegate_task`。

**3.3 ACP 客户端池** — 为每个 profile 维护一个常驻连接

```python
class ACPClient:
    def __init__(self, profile):
        self.proc = subprocess.Popen(
            ["hermes", "-p", profile, "acp"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1
        )
        # 启动读取线程,解析 JSON-RPC 事件
        threading.Thread(target=self._reader, daemon=True).start()
        self._send("initialize", {})

    def prompt(self, text, on_event):
        self.event_handler = on_event
        self._send("session/prompt", {"text": text})

acp_clients = {p: ACPClient(p) for p in ["leader", "analyst", "writer", "reviewer"]}
```

**3.4 HTTP API + SSE** — 前端交互

```python
@app.route("/api/send", methods=["POST"])
def api_send():
    d = request.json
    acp_clients[d["to"]].prompt(d["content"], on_event=broadcast_to_frontend)
    return {"ok": True}

@app.route("/api/stream")
def stream():
    q = queue.Queue()
    subscribers.append(q)
    def gen():
        try:
            while True:
                yield f"data: {json.dumps(q.get())}\n\n"
        finally:
            subscribers.remove(q)
    return Response(gen(), mimetype="text/event-stream")
```

### Step 4:前端订阅实时事件

```javascript
const es = new EventSource("/api/stream");
es.onmessage = (e) => {
    const event = JSON.parse(e.data);
    // 渲染到对话 UI:显示哪个 agent 说了什么、调了什么工具
};
```

### Step 5:leader 的任务分配策略

推荐 leader 按下面的顺序做决策:

1. **先查 registry** — 调 `list_agents`,拿到当前在线且可用的 agent
2. **拆分任务** — 把用户任务拆成 `analysis` / `writing` / `review` 等子任务
3. **打任务标签** — 每个子任务标注 `task_type`
4. **能力匹配** — 用 agent 的 `role`、`skills`、`input_types`、`output_types` 做匹配
5. **状态筛选** — 排除 `offline`、`busy`、不满足约束的 agent
6. **发送委派** — 用 `delegate_task` 把结构化任务发给目标 agent
7. **汇总结果** — specialist 返回后,leader 统一整合并面向用户输出

leader 的选择逻辑不应该是"自由猜测",而应该是:

- **谁能做** — 由 Flask 里的 Agent Registry 决定
- **这次派给谁** — 由 leader 在候选集合里做判断

### Step 6:建议的任务消息结构

为了让委派、回复、汇总都能被正确追踪,消息不要只传纯文本,建议至少包含:

- `task_id` — 当前任务 ID
- `message_id` — 当前消息 ID
- `from` — 发送方 agent
- `to` — 接收方 agent
- `task_type` — 子任务类型
- `content` — 任务正文
- `expected_output` — 期望产物
- `reply_to` — 回复哪条消息

这样 leader 在收到多个 specialist 的结果时,能明确知道:

- 这是哪个总任务下的子任务
- 这条回复对应哪次委派
- 哪些结果已经齐了,哪些还在等待

---

## 关键设计决策

### 为什么 MCP tool 立即返回,不等回复完?

如果 `send_to_agent` 同步等 B 完成才返回:
- A 会被阻塞,失去并发能力
- 如果 B 在处理中又想回复 A → **死锁**
- A 长时间看不到响应,LLM 可能超时或放弃

所以:**MCP tool 只确认"已投递"**,Flask 异步等待 B 的回复,然后**主动 prompt** 回 A。

### 为什么 leader 通过 MCP 读 registry,而不是直接问其他 agent?

如果让 leader 自己逐个问其他 agent:

- agent 数量一多,开销会明显上升
- 能力描述容易不一致,今天这样说,明天那样说
- agent 上下线后,leader 看到的信息可能过期

让 Flask 维护 registry,再通过 MCP 暴露给 leader,好处是:

- 数据源唯一,更稳定
- 支持动态上下线
- 更容易做权限、限流、负载均衡
- leader 的 prompt 可以更简单,只负责拆任务和选择

### 为什么用 ACP 而不是 subprocess `hermes chat -q`?

| 问题 | subprocess | ACP 常驻进程 |
|------|-----------|-------------|
| 启动开销 | 每次数秒 | 一次启动持续复用 |
| 上下文 | 每次丢失 | session 持久 |
| 流式输出 | 无法获取 | 实时 chunk |
| 工具调用可见 | 不可见 | 每次 tool_use 有事件 |
| 中断 | 只能 kill | 标准 cancel 消息 |

### 为什么 Flask 线程模型够用?

- 每个 ACPClient 占用一个读取线程(I/O 阻塞,不占 CPU)
- MCP 调用和 ACP prompt 都是快速 I/O
- Flask 用 `threaded=True` 启动即可,无需额外进程管理
- 瓶颈在 LLM 响应,不在 Flask 本身

---

## 局限与后续升级路径

### 当前方案的局限

1. **单机部署** — 所有 agent 进程在同一台机器
2. **Flask 进程重启丢失消息** — 内存里的路由状态会丢
3. **没有持久化对话流** — 前端刷新看不到历史
4. **registry 先是内存态** — 重启后 agent 状态需要重新注册
5. **leader 的路由策略先是规则驱动** — 复杂场景下可能需要更精细的调度器

### 升级路径

| 需求 | 升级方案 |
|------|---------|
| 持久化对话 | 所有消息写 SQLite,前端加载时从 DB 读 |
| 多机部署 | Flask 之间用 Redis pub-sub 同步,ACP 进程分布在不同机器 |
| 进程重启不丢 | ACP session 的 checkpoint,Flask 侧持久化路由状态 |
| 权限/安全 | 利用 ACP 的反向权限请求 + Flask 审批层 |
| 动态 agent 注册 | agent 启动时自动报到,更新 registry |
| 更智能的分配 | 在 registry 之上增加任务路由器 / 评分器 |

---

## 参考资料

- [Hermes Agent GitHub](https://github.com/NousResearch/hermes-agent)
- [Hermes Profile 文档](https://hermes-agent.nousresearch.com/docs/user-guide/profiles)
- [ACP 实现](https://github.com/NousResearch/hermes-agent/tree/main/acp_adapter)
- [Agent Client Protocol 标准](https://agentclientprotocol.com)
- [MCP 协议](https://modelcontextprotocol.io)

---

## 一句话总结

> **MCP 是 agent 用嘴说话,ACP 是 Flask 用手戳 agent,Flask 是中间的传话人,leader 是团队里的项目经理。**
>
> leader 先通过 MCP 查看 Flask 维护的 Agent Registry,再把子任务委派给 specialist agent;Flask 负责中转、记录、广播,最后 leader 汇总结果回复用户。
