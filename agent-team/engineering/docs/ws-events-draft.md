# WebSocket Events Draft

## 统一事件信封
- 所有事件统一字段：`type`、`version`、`eventId`、`occurredAt`、`agentId?`、`conversationId?`、`payload`。
- `version`：M1 固定为 `1`。
- `eventId`：全局唯一事件 id。
- `occurredAt`：事件发生时间，ISO 8601。
- `agentId`：与 agent 相关时提供。
- `conversationId`：与会话相关时提供。
- `payload`：事件主体，按事件类型决定字段。

示例：
```json
{
  "type": "message.created",
  "version": 1,
  "eventId": "evt_001",
  "occurredAt": "2026-04-21T20:35:00Z",
  "agentId": "agt_engineer",
  "conversationId": "conv_001",
  "payload": {}
}
```

## 事件列表

### 1. agent.status.updated
- 用途：agent 在线状态或会话状态变化。
- payload 字段：`status`、`previousStatus`、`currentSessionId`、`lastSeenAt`。

示例：
```json
{
  "status": "busy",
  "previousStatus": "idle",
  "currentSessionId": "sess_engineer_001",
  "lastSeenAt": "2026-04-21T20:45:00Z"
}
```

### 2. conversation.updated
- 用途：会话元信息更新。
- payload 字段：`id`、`scope`、`title`、`participantAgentIds`、`lastMessageAt`、`unreadCount`。

示例：
```json
{
  "id": "conv_001",
  "scope": "direct",
  "title": "engineer 最近任务",
  "participantAgentIds": ["agt_engineer"],
  "lastMessageAt": "2026-04-21T20:45:02Z",
  "unreadCount": 3
}
```

### 3. message.created
- 用途：新消息写入会话。
- payload 字段：`messageId`、`senderType`、`senderId`、`content`、`contentFormat`、`seq`、`deliveryStatus`。

示例：
```json
{
  "messageId": "msg_001",
  "senderType": "agent",
  "senderId": "agt_engineer",
  "content": "已完成第一版方案整理",
  "contentFormat": "text",
  "seq": 18,
  "deliveryStatus": "delivered"
}
```

### 4. dispatch.updated
- 用途：消息发送任务状态更新。
- payload 字段：`dispatchTaskId`、`targetScope`、`status`、`targets[]`。
- `targets[]` 子字段：`agentId`、`status`、`errorMessage?`。

示例：
```json
{
  "dispatchTaskId": "dpt_001",
  "targetScope": "broadcast",
  "status": "partial_failed",
  "targets": [
    {
      "agentId": "agt_engineer",
      "status": "succeeded"
    },
    {
      "agentId": "agt_qa",
      "status": "failed",
      "errorMessage": "script timeout"
    }
  ]
}
```

### 5. agent.log.appended
- 用途：活动侧栏日志增量。
- payload 字段：`level`、`stream`、`chunk`、`sourceId`。
- 默认不直接写入聊天消息流。

示例：
```json
{
  "level": "info",
  "stream": "stdout",
  "chunk": "正在生成结构化方案",
  "sourceId": "engineer:stdout:offset:19"
}
```

### 6. sync.snapshot
- 用途：首次连接或断线重连后的全量快照。
- payload 字段：`agents[]`、`conversations[]`、`serverTime`。

示例：
```json
{
  "agents": [
    {
      "id": "agt_engineer",
      "status": "online",
      "unreadCount": 3
    }
  ],
  "conversations": [
    {
      "id": "conv_001",
      "title": "engineer 最近任务",
      "lastMessageAt": "2026-04-21T20:45:02Z"
    }
  ],
  "serverTime": "2026-04-21T20:45:05Z"
}
```

### 7. ingest.error
- 用途：adapter 采集、解析、上报失败时提示控制台。
- payload 字段：`source`、`stage`、`message`、`retryable`。

示例：
```json
{
  "source": "console-adapter",
  "stage": "output-parse",
  "message": "unexpected output format",
  "retryable": true
}
```

## 枚举建议
- agent 状态：`online | offline | busy | idle | degraded`
- dispatch 状态：`pending | running | succeeded | partial_failed | failed`
- senderType：`user | agent | system`
- log level：`info | warn | error`
- contentFormat：`text`

## 客户端处理约定
- 前端按 `eventId` 去重。
- 消息流按 `messageId` 去重。
- 消息排序优先 `seq`，其次 `occurredAt`。
- `sync.snapshot` 不替代增量事件，仅用于补状态。
- 所有事件建议落库，支持审计、回放、排障。
