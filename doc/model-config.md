# 大模型配置功能设计方案

> 目标：在本地 Web 系统中维护可复用的大模型配置，并允许每个 Agent 选择其中一条配置。保存后写入对应 Hermes profile 的 `config.yaml`，Agent 重启后使用新模型。

---

## 1. 已确认决策

- 一期只做必要字段：`name`、`model`、`base_url`、`api_key`。
- `provider` 不暴露给用户，统一写入 `custom`。
- `reasoning_effort` 暂不做，沿用 Hermes profile 原配置。
- `api_key` 允许明文保存在本地数据库中。
- 模型配置作为全局资源维护，Agent 通过选择配置来应用。
- 运行中的 Agent 修改模型后需要重启生效；保存后提示重启。

---

## 2. 范围与边界

### 2.1 要做

- 新增全局“大模型配置”管理能力。
- 支持新增、编辑、删除、查看模型配置。
- 新建 Agent 时可选择模型配置。
- 已有 Agent 可在配置菜单中切换模型配置。
- 应用模型配置时，写入对应 Hermes profile 的 `model` 节点。
- Agent 列表展示当前使用的模型名。
- 做模型连通性测试。

### 2.2 暂不做

- 不做多 provider 复杂抽象。
- 不做 OpenRouter / Bedrock / Anthropic 等专用字段。
- 不做 API key 加密存储。
- 不做模型费用、上下文长度、能力标签管理。
- 不做按 Leader / Worker 角色自动推荐模型。

---

## 3. 数据模型

### 3.1 DB 表：模型配置

新增表 `model_configs`：

```python
class ModelConfigRecord(TimestampMixin, Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    model: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[str] = mapped_column(String(500))
    api_key: Mapped[str] = mapped_column(Text, default="")
```

字段说明：

| 字段 | 说明 | 示例 |
|---|---|---|
| `name` | 用户可读配置名 | `公司网关` |
| `model` | 实际模型名 | `gpt-5.4` |
| `base_url` | OpenAI 兼容接口地址 | `https://example.com/v1` |
| `api_key` | 明文 API Key 或环境变量占位符 | `sk-xxx` / `${OPENAI_API_KEY}` |

### 3.2 Agent 当前模型来源

Agent 当前模型以 Hermes profile 的 `config.yaml` 为准：

```yaml
model:
  default: gpt-5.4
  provider: custom
  base_url: https://example.com/v1
  api_key: sk-xxx
```

DB 中的 `model_configs` 是可复用模板，不作为运行时真相源。

---

## 4. 写入 Hermes profile

应用模型配置时读取：

`~/.hermes/profiles/<profile_name>/config.yaml`

只更新 `model` 节点：

```yaml
model:
  default: <model_config.model>
  provider: custom
  base_url: <model_config.base_url>
  api_key: <model_config.api_key>
```

其他配置保持不变，例如 `agent`、`terminal`、`mcp_servers`、`toolsets`。

---

## 5. API 设计

### 5.1 模型配置 CRUD

#### `GET /api/model-configs`

返回全部模型配置。

```json
{
  "items": [
    {
      "id": 1,
      "name": "公司网关",
      "model": "gpt-5.4",
      "base_url": "https://example.com/v1",
      "api_key": "sk-xxx"
    }
  ]
}
```

#### `POST /api/model-configs`

新增模型配置。

```json
{
  "name": "公司网关",
  "model": "gpt-5.4",
  "base_url": "https://example.com/v1",
  "api_key": "sk-xxx"
}
```

#### `PUT /api/model-configs/<id>`

更新模型配置。

#### `DELETE /api/model-configs/<id>`

删除模型配置。

如果已有 Agent 的当前 profile 与该配置内容一致，删除不影响 Agent，因为 Agent 已经写入了自己的 `config.yaml`。

### 5.2 Agent 应用模型配置

#### `PUT /api/agents/<agent_id>/model`

```json
{
  "model_config_id": 1
}
```

处理逻辑：

1. 查找 Agent。
2. 查找模型配置。
3. 校验 Agent 是否可修改模型。
4. 写入 Hermes profile `config.yaml`。
5. 推送 Agent 变更事件。
6. 返回当前模型摘要。

---

## 6. 前端设计

### 6.1 模型配置入口

在页面增加“模型配置”入口，打开抽屉或弹窗。

列表字段：

- 配置名
- 模型名
- Base URL
- API Key
- 操作：编辑 / 删除

### 6.2 新建 Agent

新建 Agent 表单增加“模型配置”下拉框：

- 默认选项：继承当前 Hermes active profile 配置
- 其他选项：来自 `GET /api/model-configs`

提交时如果选择了模型配置：

1. 先创建 Agent。
2. 再调用 `PUT /api/agents/<agent_id>/model` 应用模型配置。

### 6.3 已有 Agent 切换模型

Agent 配置菜单增加“模型配置”。

交互：

- 展示当前 profile 中读取到的 `model.default` 和 `base_url`。
- 下拉选择一条模型配置。
- 保存后提示：`模型配置已保存，重启 Agent 后生效。`

### 6.4 Agent 列表展示

Agent 行增加模型摘要：

```text
worker · frontend · gpt-5.4
```

---

## 7. 校验规则

- `name` 必填，去除首尾空格，不允许重复。
- `model` 必填。
- `base_url` 必填，必须以 `http://` 或 `https://` 开头。
- `api_key` 必填，一期允许任意非空字符串。
- `api_key` 可以是明文，也可以是 `${ENV_NAME}`。

---

## 8. 生效时机

HermesSession 当前启动方式是：

```text
hermes -p <profile_name>
```

模型配置由 Hermes 启动时读取 profile `config.yaml`，所以修改后需要重启 Agent 才能稳定生效。

一期策略：

- Agent 未运行：允许直接保存。
- Agent 正在运行：允许保存，但 UI 明确提示“需重启生效”。
- 后续可增强为保存后提供“一键重启 Agent”。

---

## 9. 与导入导出的关系

一期建议：

- Agent 导入导出不默认携带全局 `model_configs`。
- Agent profile 的 `config.yaml` 会按现有导入导出策略处理。
- 如果 `config.yaml` 中是明文 API Key，导出时应继续按导入导出文档的敏感字段策略处理。

---

## 10. 实施步骤建议

1. 新增 DB 表与 repository 方法。
2. 新增 `services/model_configs.py`。
3. 新增 `profiles.update_model_config()` 与 `profiles.read_model_summary()`。
4. 新增 `controllers/model_configs.py`。
5. 在 Agent 创建与详情返回中带上模型摘要。
6. 前端增加模型配置管理 UI。
7. 前端增加 Agent 选择/切换模型 UI。
8. 补充基础测试。

