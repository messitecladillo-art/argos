# Hermes 多 Agent 协作系统 — 架构设计

## 目标

基于 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的 profile 机制,构建一个多 agent 相互协作的 Web 系统:

- **后端**:Flask,作为 agent 之间的通信枢纽
- **前端**:实时展示多 agent 对话过程
- **agent**:每个 agent 是一个独立的 Hermes profile,拥有独立记忆、技能、人设
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
│  │ /api/send    │  │ send_to_agent│  │ /api/stream   │ │
│  │ /api/agents  │  │              │  │               │ │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘ │
│         │                 │                  │         │
│         └─────────┬───────┴──────────────────┘         │
│                   │                                     │
│          ┌────────▼────────┐                            │
│          │  消息路由器      │                            │
│          │  + ACP 客户端池  │                            │
│          └────────┬────────┘                            │
└───────────────────┼─────────────────────────────────────┘
                    │ JSON-RPC (ACP over stdio)
         ┌──────────┼──────────┬──────────┐
         ▼          ▼          ▼          ▼
   ┌─────────┐┌─────────┐┌─────────┐┌─────────┐
   │ hermes  ││ hermes  ││ hermes  ││ hermes  │
   │ -p      ││ -p      ││ -p      ││ -p …    │
   │ analyst ││ writer  ││reviewer ││         │
   │ acp     ││ acp     ││ acp     ││         │
   └─────────┘└─────────┘└─────────┘└─────────┘
     各自独立的记忆、技能、人设、配置
```

---

## 实施步骤

### Step 1:创建多个 Profile

```bash
hermes profile create analyst
hermes profile create writer
hermes profile create reviewer

# 为每个 profile 配置人设
cat > ~/.hermes/profiles/analyst/SOUL.md <<EOF
你是数据分析 agent。
你可以通过 send_to_agent 工具与 writer、reviewer 协作。
当需要让其他 agent 做事时,调用该工具并指定 to 和 content。
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

Flask 需要同时承担三个角色:

**3.1 MCP Server** — 暴露 `send_to_agent` 工具给各 agent

```python
@mcp_server.tool("send_to_agent")
def send_to_agent(to: str, content: str, _from: str) -> str:
    acp_clients[to].prompt(
        f"[来自 {_from}]: {content}",
        on_event=lambda ev: broadcast_to_frontend(ev)
    )
    return f"已发送给 {to}"   # 立即返回,不等 B 回复完
```

**3.2 ACP 客户端池** — 为每个 profile 维护一个常驻连接

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

acp_clients = {p: ACPClient(p) for p in ["analyst", "writer", "reviewer"]}
```

**3.3 HTTP API + SSE** — 前端交互

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

---

## 关键设计决策

### 为什么 MCP tool 立即返回,不等回复完?

如果 `send_to_agent` 同步等 B 完成才返回:
- A 会被阻塞,失去并发能力
- 如果 B 在处理中又想回复 A → **死锁**
- A 长时间看不到响应,LLM 可能超时或放弃

所以:**MCP tool 只确认"已投递"**,Flask 异步等待 B 的回复,然后**主动 prompt** 回 A。

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

### 升级路径

| 需求 | 升级方案 |
|------|---------|
| 持久化对话 | 所有消息写 SQLite,前端加载时从 DB 读 |
| 多机部署 | Flask 之间用 Redis pub-sub 同步,ACP 进程分布在不同机器 |
| 进程重启不丢 | ACP session 的 checkpoint,Flask 侧持久化路由状态 |
| 权限/安全 | 利用 ACP 的反向权限请求 + Flask 审批层 |

---

## 参考资料

- [Hermes Agent GitHub](https://github.com/NousResearch/hermes-agent)
- [Hermes Profile 文档](https://hermes-agent.nousresearch.com/docs/user-guide/profiles)
- [ACP 实现](https://github.com/NousResearch/hermes-agent/tree/main/acp_adapter)
- [Agent Client Protocol 标准](https://agentclientprotocol.com)
- [MCP 协议](https://modelcontextprotocol.io)

---

## 一句话总结

> **MCP 是 agent 用嘴说话,ACP 是 Flask 用手戳 agent,Flask 是中间的传话人。**
>
> 每个 agent 以为自己只是在调一个 "send_to_agent" 工具,实际上 Flask 把这个工具翻译成"给另一个 agent 发 prompt",并把整个交互流实时推给前端。
