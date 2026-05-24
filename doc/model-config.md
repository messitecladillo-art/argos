# 大模型配置实现说明

本文档说明当前项目中的大模型配置管理实现。系统维护可复用的模型配置，并允许每个 Agent 将其中一条配置写入自己的 Hermes profile `config.yaml`。

## 1. 当前能力

- 维护全局模型配置列表。
- 支持新增、编辑、删除、查看模型配置。
- 支持测试模型配置连通性。
- 新建 Agent 后可应用模型配置。
- 已有 Agent 可切换模型配置。
- Agent 当前模型以其 profile `config.yaml` 为准。

当前只支持必要字段：

- `name`
- `model`
- `base_url`
- `api_key`

`provider` 固定写入 `custom`。`reasoning_effort` 不由本功能管理，沿用 Hermes profile 原有配置。

## 2. 数据模型

数据库表：`model_configs`

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
| --- | --- | --- |
| `name` | 用户可读配置名 | `公司网关` |
| `model` | 实际模型名 | `gpt-5.4` |
| `base_url` | OpenAI 兼容接口地址 | `https://example.com/v1` |
| `api_key` | 明文 API Key 或环境变量占位符 | `sk-xxx` / `${OPENAI_API_KEY}` |

模型配置是可复用模板，不是 Agent 运行时真相源。Agent 当前模型从 profile `config.yaml` 读取。

## 3. 写入 profile

应用模型配置时，`argos/services/profiles.py::apply_model_config(...)` 只更新 profile `config.yaml` 的 `model` 节点：

```yaml
model:
  default: <model_config.model>
  provider: custom
  base_url: <model_config.base_url>
  api_key: <model_config.api_key>
```

其他配置保持不变，例如 `mcp_servers`、`toolsets` 等。

## 4. 关键文件

| 文件 | 作用 |
| --- | --- |
| `argos/controllers/model_configs.py` | 模型配置 REST API |
| `argos/services/model_configs.py` | CRUD、应用到 Agent、读取当前模型、连通性测试 |
| `argos/services/profiles.py` | 读写 profile `config.yaml` 和模型摘要 |
| `tests/test_model_config_api.py` | 模型配置 API 测试 |

## 5. API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/model-configs` | 返回全部模型配置 |
| POST | `/api/model-configs` | 新增模型配置，返回 `{ok, item}`，状态码 `201` |
| PUT | `/api/model-configs/<id>` | 更新模型配置 |
| DELETE | `/api/model-configs/<id>` | 删除模型配置 |
| POST | `/api/model-configs/<id>/test` | 测试模型配置 |
| GET | `/api/agents/<agent_id>/model` | 读取 Agent 当前模型摘要 |
| PUT | `/api/agents/<agent_id>/model` | 应用模型配置到 Agent |

应用模型配置请求：

```json
{
  "model_config_id": 1
}
```

成功返回包含：

- `agent`
- `model`
- `restart_required`

## 6. 校验规则

- `name` 必填，去除首尾空格，不允许重复。
- `model` 必填。
- `base_url` 必填，必须以 `http://` 或 `https://` 开头。
- `api_key` 必填。
- `api_key` 可以是明文，也可以是 `${ENV_NAME}`。

常见错误：

| HTTP | 场景 |
| --- | --- |
| 400 | 字段缺失、URL 非法、名称重复 |
| 404 | 模型配置或 Agent 不存在 |
| 500 | profile 配置读写失败 |

## 7. 连通性测试

`POST /api/model-configs/<id>/test` 当前请求：

```text
GET <base_url>/models
Authorization: Bearer <api_key>
Accept: application/json
```

`2xx` 视为成功，其余 HTTP 状态或请求异常视为失败。

## 8. 生效时机

Hermes 启动时读取 profile `config.yaml`：

```text
hermes -p <profile_name>
```

因此修改模型配置后，正在运行的 Agent 需要重启才会稳定生效。接口会在 Agent 正在运行时返回 `restart_required: true`。

新建 Agent 表单如果选择了模型配置，前端当前流程是：

1. 先调用 `POST /api/agents` 创建 Agent。
2. 再调用 `PUT /api/agents/<agent_id>/model` 应用模型配置。

## 9. 与导入导出的关系

导入导出以 Agent profile 为主。模型配置模板本身不是 Agent 运行时真相源；profile `config.yaml` 中的模型配置会随 profile 配置按导入导出策略处理。

如果 `config.yaml` 中包含明文 API Key，导出时按导入导出文档中的敏感字段策略处理。
