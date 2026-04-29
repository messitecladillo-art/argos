# Agent 导入导出方案

将电脑 A 上配置好的 Leader / Worker agents 打包导出，在电脑 B 上导入后显示内容与功能与 A 保持一致。

---

## 1. 需求范围

- **导出**：选择一个或多个 agent（含 Leader），打包成单一可分发文件（`.hermes-team.zip`）。
- **导入**：在目标机上解包并还原，使该 agent 立即可用 —— UI 列表能看到、点进去 SOUL / 技能 / MCP 配置都在、可以启动对话。
- **目标一致性**：身份（name / role / description / is_leader）、SOUL.md、已装 Skills、已配 MCP Servers、人设 memories、基础 hermes profile 配置。
- **非目标（v1 不做）**：
  - 运行时状态、消息历史、任务/委派/事件记录（属于 A 机的运行痕迹，不跟随迁移）。
  - Hermes CLI 本身的安装与模型 API Key（依赖 B 机自己的 `HERMES_HOME` 环境）。
  - Workspace 工作目录内容（`~/agent_team/<name>/` 下的业务产物，体积大且机器相关）。

---

## 2. 一个 Agent 由什么组成

实际状态分散在三处：

| 位置 | 内容 | 是否导出 |
|---|---|---|
| SQLite `data/hermes_agent_team.db` | `agents` / `agent_skill_installs` / `agent_mcp_servers` 行 | ✅ 仅该 agent 相关行 |
| `~/.hermes/profiles/<profile_name>/` | `SOUL.md`、`team-meta.json`、`config.yaml`、`skills/`、`memories/` | ✅ 白名单子集 |
| `~/.hermes/profiles/<profile_name>/` | `state.db*`、`sessions/`、`logs/`、`sandboxes/`、`cron/`、`plans/`、`bin/`、`home/` | ❌ 运行时/机器相关 |
| `~/agent_team/<profile_name>/` | Workspace | ❌ 默认不导（可选开关） |

### 2.1 DB 字段筛选

`AgentRecord` 中需重置为初始态、不导出的字段：

```
status, runtime_status, interaction_state, orchestration_state,
queue_depth, pending_interaction_json, load,
last_input, last_output, last_output_at,
readiness_status, readiness_message, last_active_at,
created_at/updated_at/deleted_at/db_*  (DB 自动生成)
```

需要导出的字段：`agent_id`、`profile_name`、`name`、`role`、`description`、`is_leader`、`workspace_path`（可选，导入时按 B 机 `AGENT_TEAM_WORKSPACE_ROOT` 重建）、`current_task` 默认置 "空闲"。

`AgentSkillInstallRecord` 全字段保留；`installed_at` 在 B 机重写。

`AgentMcpServerRecord` 全字段保留；`last_test_status` / `last_test_at` / `last_error` 在 B 机重置。

### 2.2 敏感字段处理

- `config.yaml` 里 `api_key: ${OPENAI_API_KEY}` 是环境变量占位符，可直接带走。若检测到明文 key（如 `sk-...`）则在导出时替换为占位符并在 `SECRETS.md` 标红。
- `agent_mcp_servers` 表中的 headers/env 凭据当前已脱敏存储（参见 `mcp_installer._mask_secrets`），导出时原样带走；运行时密钥由 B 机自己补齐。
- 导出包内提供 `SECRETS.md` 提示用户哪些凭据需要在 B 机重新配置。

---

## 3. 打包格式

单一 `.zip`，结构：

```
team-export-<timestamp>.hermes-team.zip
├── manifest.json            # schema_version、导出时间、源主机信息、agent 清单、checksum
├── agents/
│   └── <profile_name>/
│       ├── meta.json        # AgentRecord 序列化（去掉运行时字段）
│       ├── db/
│       │   ├── skill_installs.json   # 该 profile 的 AgentSkillInstallRecord 列表
│       │   └── mcp_servers.json      # 该 profile 的 AgentMcpServerRecord 列表
│       └── profile/         # hermes profile 白名单文件
│           ├── SOUL.md
│           ├── team-meta.json
│           ├── config.yaml  # 敏感字段已占位化
│           ├── memories/
│           └── skills/      # 已安装的 skill 目录（可选，按勾选）
├── SECRETS.md               # 需要 B 机手动补齐的凭据清单
└── README.txt               # 简短导入说明
```

### 3.1 manifest.json 结构

```json
{
  "schema_version": 1,
  "exported_at": "2026-04-29T10:00:00Z",
  "source_host": {"hostname": "Liu-MBP", "platform": "darwin"},
  "options": {"inline_skill_files": true, "include_workspace": false},
  "agents": [
    {
      "profile_name": "leader",
      "agent_id": "agent-leader-xxx",
      "role": "leader",
      "is_leader": true,
      "files": {
        "agents/leader/meta.json": "sha256:...",
        "agents/leader/profile/SOUL.md": "sha256:...",
        "...": "..."
      },
      "skills": [{"slug": "code-review", "source_type": "git", "inline": true}],
      "mcp_servers": [{"name": "agent_bus", "transport": "http"}]
    }
  ]
}
```

导入前校验每文件 sha256 与 schema_version。

### 3.2 Skills 的两种打包策略

| 模式 | 体积 | B 机要求 | 适用 |
|---|---|---|---|
| **按源拉取（默认）** | 小 | 网络 + 源仓库可达 | 常规迁移 |
| **内联文件** | 大 | 离线即可 | 离线分发、源仓库可能失效 |

导出时给用户勾选；推荐**默认"按源拉取 + 同时内联文件作为 fallback"**：先尝试 git 拉，失败回落到包内文件。

---

## 4. 冲突策略（导入时）

`profile_name` / `agent_id` 在 B 机已存在时：

1. **rename**（默认）：自动追加后缀 `-imported-<n>`，生成新的 `agent_id` 与 `profile_name`，DB 与 hermes profile 同步改名。
2. **skip**：跳过该 agent。
3. **overwrite**：删除 B 机现有 profile 与 DB 行后覆盖（高危，前端二次确认）。

MCP Server 名与 Skill slug 在同一 profile 下如有冲突走相同的三选一（profile 级覆盖时其下资源整体替换；rename 时仅冲突项追加后缀）。

校验规则：`profile_name` 必须满足 `PROFILE_NAME_RE`，rename 后仍需通过校验。

---

## 5. 后端实施

### 5.1 模块划分

新增 `app/services/transfer.py`，对外暴露：

```python
def export_agents(profile_names: list[str], *, inline_skill_files: bool, include_workspace: bool) -> Path
def inspect_archive(zip_path: Path) -> dict   # 返回 manifest + 冲突预检
def import_archive(zip_path: Path, *, strategy: str, rename_map: dict[str, str]) -> dict
```

复用现有服务：
- `profiles.create_hermes_profile` —— 创建 hermes profile
- `profiles.check_hermes_ready` —— 前置检查
- `skill_installer.install_from_git` / 内部辅助 —— 恢复 skills
- `mcp_installer.add_mcp` —— 恢复 MCP servers
- `app.db.repositories` —— DB 读写

### 5.2 Export 流程

1. 入参：`profile_names`、`inline_skill_files`、`include_workspace`。
2. 校验每个 `profile_name` 在 DB 中存在。
3. 创建临时目录 `tmp/export-<uuid>/`。
4. 对每个 agent：
   - 从 DB 拉 `AgentRecord` / `AgentSkillInstallRecord` / `AgentMcpServerRecord`，序列化为 JSON（剔除运行时字段）。
   - 从 `HERMES_HOME/profiles/<name>/` 按白名单（`SOUL.md` / `team-meta.json` / `config.yaml` / `memories/` / 可选 `skills/`）拷入临时目录。
   - 对 `config.yaml` 做 secret 扫描：形如 `api_key: <非占位符>` 的明文替换为 `${OPENAI_API_KEY}` 并记入 `SECRETS.md`。
5. 写入 `manifest.json`（含 schema_version、源主机、每文件 sha256）。
6. zip 成 `.hermes-team.zip`，返回给前端流式下载。
7. 清理临时目录。

### 5.3 Import 流程

两阶段，前端先 inspect 再 apply。

**阶段 A：inspect**
1. 解压到临时目录。
2. 校验 `manifest.json` schema_version。
3. 校验每文件 sha256。
4. 对每个 agent 计算冲突状态（profile_name 是否已存在、agent_id 是否已存在、MCP / Skill 名冲突）。
5. 返回结构化报告给前端。

**阶段 B：apply**
1. 检查 `hermes` CLI 可用（复用 `profiles.check_hermes_ready()`）。
2. 对每个 agent（独立事务，单个失败不影响其他）：
   1. 应用 rename：根据 `rename_map` 或自动生成新 `profile_name` / `agent_id`。
   2. `hermes profile create <name> --clone --no-alias`（幂等）。
   3. 覆盖写入 `SOUL.md` / `team-meta.json` / `memories/`。
   4. `config.yaml` 合并：保留 B 机已有 `model` / `provider` / `api_key`，只写入 agent 专属节（如 `agent.personalities` 自定义部分）。
   5. 写入 DB：`AgentRecord`（运行时字段重置为初始态：`status=idle`、`runtime_status=stopped`、`current_task="空闲"`、`load=0` 等）。
   6. 恢复 Skills：
      - 若 inline 且包内有目录：直接拷贝到 `profile/skills/<slug>/`，并插 `AgentSkillInstallRecord` 行。
      - 否则按 `source_url` + `source_ref` 调 `skill_installer.install_from_git` 装回。
      - git 拉失败且有 inline 备份 → fallback 到 inline。
   7. 恢复 MCP Servers：构造 `_RecordPayload`，调 `mcp_installer.add_mcp`（或内部 `_upsert_record`）写入 profile YAML + `AgentMcpServerRecord`。敏感凭据留空并记入返回结果的 "需补齐" 列表。
   8. 注册到运行时 `RuntimeStore`，触发 SSE 通知前端刷新列表。
3. 返回每个 agent 的 `success / skipped / failed` 状态、rename 结果、缺失凭据清单。

### 5.4 错误与回滚

- inspect 阶段失败 → 整包拒绝，无副作用。
- apply 阶段单 agent 失败 → 该 agent 已创建的 hermes profile 与 DB 行回滚（删除）；其他 agent 继续。
- 全部失败时清理临时目录与残留 profile。

---

## 6. HTTP 接口

挂载到 `app/controllers/transfer.py`：

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/transfer/export` | body `{profile_names: [...], options: {...}}`；返回 `application/zip` 流 |
| `POST` | `/api/transfer/inspect` | multipart 上传 zip；返回 manifest + 冲突预检 JSON |
| `POST` | `/api/transfer/import` | multipart 上传 zip + `{strategy, rename_map}`；返回执行结果 JSON |

错误码：
- `400` 参数非法（profile_name 不存在 / 非法 schema_version / zip 损坏）
- `409` 冲突（仅在 strategy 不允许的前提下）
- `412` Hermes CLI 未就绪
- `500` 未预期错误

---

## 7. 前端改动

`app/static/` 与 `app/templates/` 中：

- Agents 列表页顶部加 **导出 / 导入** 按钮。
- **导出弹窗**：
  - 多选 agent（默认勾选 Leader 时联动勾选其常用 Worker）。
  - 选项：`内联 skills 文件`、`包含 workspace`（高级折叠）。
  - 点击后下载 zip，文件名 `team-export-<yyyymmdd-HHMM>.hermes-team.zip`。
- **导入弹窗**（两步）：
  - 步骤 1：上传 zip → 调 `/inspect` → 渲染预览表（每行：profile_name / role / 冲突状态 / 缺失凭据）。
  - 步骤 2：用户为每个冲突 agent 选择 rename / skip / overwrite，确认后调 `/import` → 显示进度与结果表。
- 完成后自动刷新 agents 列表（依赖现有 SSE 事件）。

---

## 8. 测试计划

`tests/test_transfer.py`：

1. **export_minimal** — 导出一个最小 Leader → 解压 → 校验 manifest、SOUL、DB json 字段齐全；运行时字段未泄露。
2. **export_with_resources** — 导出含 skills + mcp_servers 的 agent → 校验 zip 结构与 sha256。
3. **import_into_empty** — 在空 HERMES_HOME 上导入上一个包 → 断言：
   - `~/.hermes/profiles/<name>/` 存在并含 SOUL.md / config.yaml / skills/
   - DB 中 AgentRecord / SkillInstall / McpServer 行齐全且运行时字段为初始值
   - 通过 `profiles.list_hermes_profiles()` 可见
4. **conflict_rename** — 同名 profile 已存在，strategy=rename → 新 profile 名带 `-imported-1` 后缀，DB agent_id 同步更新。
5. **conflict_skip** — strategy=skip → 不写入任何东西，返回 skipped。
6. **conflict_overwrite** — strategy=overwrite → 旧 profile 与 DB 行被替换。
7. **secret_redaction** — config.yaml 含明文 `api_key: sk-xxxx` → 导出包内为 `${OPENAI_API_KEY}`，`SECRETS.md` 列出该项。
8. **broken_zip** — 篡改 sha256 / schema_version 不匹配 → import 阶段拒绝，无副作用。
9. **partial_failure** — 三个 agent 导入，第二个的 skill git 源失效（无 inline）→ 第二个失败，其他两个成功。
10. **end_to_end** — 模拟 A→B 双 HERMES_HOME 全流程。

---

## 9. 与现有架构对接点

- `app/services/registry.py` —— 导入完成后需要触发 RuntimeStore 重新加载该 agent。
- `app/controllers/events.py` —— 通过 SSE 推送 `agent.imported` 事件让前端刷新列表。
- `app/services/profiles.py:_profile_config_path` —— 复用以定位 `config.yaml`。
- `app/db/repositories.py` —— 新增 `bulk_upsert_agent` / `bulk_upsert_skills` / `bulk_upsert_mcps` 辅助方法。

---

## 10. 分期落地

- **M1（MVP，1 周）**
  - 单 agent 导出/导入
  - 按源拉取 skills（不内联）
  - 仅 rename 冲突策略
  - 后端单测覆盖核心路径
  - 命令行可用（`python -m app.cli transfer export/import`），UI 后置
- **M2（完整版，1 周）**
  - 多 agent 批量
  - 内联 skills + git fallback
  - skip / overwrite 策略
  - 前端导入导出弹窗
  - SECRETS.md 与缺失凭据提示
- **M3（可选增强）**
  - workspace 导出（带过滤规则，跳过 `node_modules` / `.venv` 等）
  - 导入 dry-run 差异预览（哪些文件会变更）
  - 跨 schema_version 迁移（v1 → v2 升级器）
  - 增量导出（只导出某次时间戳后修改过的 agent）

---

## 11. 风险与注意事项

| 风险 | 缓解 |
|---|---|
| 明文 API key 误入导出包 | 导出前 secret 扫描 + `SECRETS.md` 提醒；扫描规则可配置 |
| B 机 hermes CLI 版本不同导致 config.yaml schema 不兼容 | 导入时合并而非覆盖；记录源 hermes 版本到 manifest |
| Skill 源仓库私有/失效 | 默认同时内联文件作为 fallback |
| profile_name 含非法字符 | 走 `PROFILE_NAME_RE` 校验，rename 时也需通过 |
| 大体积 zip 占内存 | 流式读写，导出/导入均不一次性加载到内存 |
| 导入中断导致脏状态 | 单 agent 事务化；中断后 cleanup 临时目录 + 残留 profile |
| Workspace 含敏感数据 | 默认不导；显式开关时弹二次确认 |
