# Skills 管理实现说明

本文档说明当前项目中 Agent Skills 的实际实现。Skills 按 agent 对应的 Hermes profile 隔离，最终通过 profile 目录下的 `skills/` 被 Hermes 原生加载。

## 1. 当前能力

- 从公开 `https://` Git 仓库安装 skill。
- 支持指定 `ref`、`subdir`、`slug`。
- 列出已安装 skill，包括平台安装记录和手动放入目录的本地 skill。
- 查看 `SKILL.md` frontmatter、正文和绝对路径。
- 卸载 skill，语义是删除当前 agent profile 下的真实目录。
- 重新安装/升级平台记录过来源的 Git skill。
- `list_workers()` 不返回 skills 字段，避免 Leader 工具输出过大。

暂不支持：

- Git 私有仓认证。
- archive URL / zip 上传安装。
- skill 市场或 registry 协议。
- UI 内编辑 skill 内容。
- skill 启用/禁用。

## 2. 存储布局

Skills 存放在 Hermes profile 目录：

```text
~/.hermes/profiles/<profile_name>/
├── config.yaml
├── SOUL.md
├── team-meta.json
└── skills/
    └── <slug>/
        └── SKILL.md
```

文件系统是真相源：目录存在且包含 `SKILL.md`，就视为已安装。

数据库表 `agent_skill_installs` 只记录平台安装来源，用于 reinstall/update：

- `profile_name`
- `slug`
- `source_type`
- `source_url`
- `source_ref`
- `resolved_commit_sha`
- `subdir`
- `installed_at`
- `last_error`

手动复制进 `skills/` 的 skill 没有 DB 记录，接口返回 `source_type="local"`，仍可查看和删除，但不能自动重新安装。

## 3. 关键文件

| 文件 | 作用 |
| --- | --- |
| `app/controllers/agents.py` | Skills REST API，和 agent API 在同一个 blueprint 中 |
| `app/services/skill_installer.py` | 安装、列表、查看、卸载、重新安装逻辑 |
| `app/services/skill_frontmatter.py` | `SKILL.md` frontmatter 解析和序列化 |
| `app/services/registry.py` | profile / skills 路径计算 |
| `app/db/models.py` | `AgentSkillInstallRecord` |
| `tests/test_skill_api.py` | Skills API 测试 |

## 4. API

当前 Skills API 是同步执行，不返回 `job_id`，也不通过 SSE 推安装进度。

| 方法 | 路径 | Body / Query | 返回 |
| --- | --- | --- | --- |
| GET | `/api/agents/<agent_id>/skills` | - | `{ok, skills, agent}` |
| GET | `/api/agents/<agent_id>/skills/<slug>` | - | `{ok, skill}` |
| POST | `/api/agents/<agent_id>/skills/install` | `{source_url 或 repo_url, ref?, subdir?, slug?}` | `{ok, skill}`，状态码 `201` |
| POST | `/api/agents/<agent_id>/skills/<slug>/reinstall` | - | `{ok, skill}` |
| DELETE | `/api/agents/<agent_id>/skills/<slug>` | - | `{ok}` |

错误码由 `SkillError.status_code` 决定，常见情况：

| HTTP | 场景 |
| --- | --- |
| 400 | 参数缺失、URL 非法、slug 非法、clone 失败、clone 超时 |
| 404 | agent 不存在、skill 不存在 |
| 409 | 目标 slug 已存在但来源不同，需要先卸载 |

## 5. Git 安装流程

`install_from_git(...)` 的当前流程：

1. 校验仓库 URL：只允许 `https://`，并拒绝解析到私网、回环、链路本地或保留地址的 host。
2. 在 `~/.hermes/tmp/skill_install_<uuid>/` 下执行浅克隆。
3. 如果传入 `ref`，执行 `git clone --depth=1 --branch <ref>`；否则使用仓库默认分支。
4. 解析 `subdir`；未传 `subdir` 且仓库中只有一个 `SKILL.md` 时，会自动发现该目录。
5. 推断 slug：优先使用请求参数，其次使用 `SKILL.md` 的 `name`，再退回仓库名。
6. 将 `SKILL.md` frontmatter 的 `name` 重写为最终 slug，`description` 缺失时用原 name 或 slug 兜底。
7. 校验 symlink、文件数量和大小。
8. 如果目标目录已存在：
   - 有同来源 DB 记录时允许覆盖；
   - 本地 skill 或不同来源记录会返回 `409`。
9. 通过 `.tmp_<uuid>` 和 `.trash/<slug>.<timestamp>` 做原子替换。
10. 写入或更新 `agent_skill_installs` 记录。

资源限制：

| 项 | 上限 |
| --- | --- |
| 单个 skill 总大小 | 10 MB |
| 文件总数 | 500 |
| 单文件大小 | 5 MB |
| git clone 超时 | 120 秒 |

## 6. 查看、卸载和重装

`list_installed(profile_name)` 会递归扫描 `skills/` 下所有 `SKILL.md`，并合并 DB 记录。返回项包含：

- `slug`
- `name`
- `description`
- `path`
- `source_type`
- `source_url`
- `source_ref`
- `resolved_commit_sha`
- `subdir`
- `installed_at`
- `has_db_record`
- `error`

`get_skill(profile_name, slug)` 返回 `frontmatter`、`body`、原始 `content`、路径和来源信息。

`uninstall(agent_id, slug)` 删除 `skills/<slug>/` 并清理 DB 记录。目录不存在时也返回成功。

`reinstall(agent_id, slug)` 只支持有 DB 记录且 `source_type="git"` 的 skill；本地手动安装的 skill 会返回错误。

## 7. Agent 生命周期

创建 agent 时，`app/services/agents.py` 会兜底创建：

```text
~/.hermes/profiles/<profile_name>/skills/
```

如果新 profile 是从源 profile 克隆来的，已有 skills 会被保留，并在列表中显示为 `source_type="local"`。

删除 agent 时，Hermes profile 目录会随之删除；同时会清理该 profile 对应的 skill 安装记录。

## 8. 示例

安装：

```bash
curl -X POST http://127.0.0.1:5050/api/agents/agent_alice/skills/install \
  -H 'Content-Type: application/json' \
  -d '{
    "source_url": "https://github.com/github/awesome-copilot",
    "ref": "main",
    "subdir": "skills/ai-team-orchestration"
  }'
```

返回：

```json
{"ok": true, "skill": {"slug": "ai-team-orchestration"}}
```

列出：

```bash
curl http://127.0.0.1:5050/api/agents/agent_alice/skills
```

重新安装：

```bash
curl -X POST http://127.0.0.1:5050/api/agents/agent_alice/skills/ai-team-orchestration/reinstall
```

卸载：

```bash
curl -X DELETE http://127.0.0.1:5050/api/agents/agent_alice/skills/ai-team-orchestration
```
