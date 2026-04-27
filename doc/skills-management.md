# Skills 管理功能设计方案

> 目标:为每个 agent 支持从 Git 仓库安装第三方 skill 包,管理已安装列表,支持查看、卸载、更新。Leader 通过 `list_workers()` 能看到每个 worker 已安装的 skills 摘要,据此做能力感知派发。

---

## 1. 范围与边界

### 1.1 要做
- 从 git 公开 https 仓库安装 skill
- 列出已安装 skill(含 DB 登记的 + 手动放入目录的本地 skill)
- 查看 skill 正文(`SKILL.md` 只读预览)
- 卸载 skill(允许删除本地 skill,语义为删除当前 agent profile 下的真实目录)
- 重新安装/升级(仅对平台记录过来源的 skill)
- Leader 端 `list_workers()` 返回每个 worker 的已安装 skills 摘要

### 1.2 不做
- 不支持 git 私有仓(遇到认证失败即返回错误)
- 不做 archive URL / zip 上传安装
- 不做启用/禁用
- 不做 skill 市场/注册表协议
- 不做 skill 运行时沙箱/权限隔离(agent 自行决定是否读取)
- 不做 UI 内编辑 skill 内容(用户改就直接编辑 SKILL.md 文件)
- 不做来源 URL 白名单

---

## 2. 存储布局与数据模型

### 2.1 文件系统(真相源)

```
~/.hermes/profiles/<profile_name>/
├── config.yaml
├── SOUL.md
├── team-meta.json
└── skills/                             ← 从源 profile 克隆继承(可能非空),平台只兜底建目录
    ├── code-review/
    │   └── SKILL.md
    ├── data-analysis/
    │   ├── SKILL.md
    │   ├── scripts/
    │   └── templates/
    └── ...
```

### 2.2 SKILL.md 约定

每个 skill 包**必须**在根目录有 `SKILL.md`,frontmatter 字段:

```markdown
---
name: code-review              # 必需,必须与目录名一致
description: Review PRs ...    # 必需,一句话,进 list_workers 返回给 leader
---

# Code Review

<正文 markdown ...>
```

**校验规则**:
- `name` 缺失 → 拒绝安装
- `name` 与目录名不一致 → 以目录名为准(重写 frontmatter 的 name 字段)
- `description` 缺失 → 用 `name` 兜底

**slug 规则**:`^[a-z0-9][a-z0-9_-]{0,60}$`

### 2.3 DB 表(来源元数据,用于 reinstall)

新增到 `app/db/models.py`:

```python
class AgentSkillInstallRecord(TimestampMixin, Base):
    __tablename__ = "agent_skill_installs"
    __table_args__ = (UniqueConstraint("profile_name", "slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_name: Mapped[str] = mapped_column(String(120), index=True)
    slug: Mapped[str] = mapped_column(String(80))
    source_type: Mapped[str] = mapped_column(String(20))   # "git"
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_ref: Mapped[str] = mapped_column(String(120), default="")  # 用户输入的 ref
    resolved_commit_sha: Mapped[str] = mapped_column(String(120), default="")
    subdir: Mapped[str] = mapped_column(Text, default="")
    installed_at: Mapped[str] = mapped_column(String(40), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
```

**文件 + DB 分工**:
- 文件系统决定"是否装了"(agent 用的就是文件)
- DB 决定"从哪装来的"(reinstall/update 依赖)
- 手动复制进 `skills/` 的 skill → 文件存在但 DB 无记录 → `source_type` 上报 `"local"`,仍可查看/删除

### 2.4 生效机制

- Hermes 在运行 `hermes -p <profile>` 时,会原生读取该 profile 目录下的 `skills/`
- 平台不改写 `SOUL.md`,也不额外注入 runtime prompt
- skill 是否生效,完全依赖 Hermes 对当前 profile `skills/` 目录的原生自动加载机制

---

## 3. 安装流程

### 3.1 一期统一管线

```
[请求] → [规范化 source + slug] → [tmp clone] → [校验] → [原子替换目标目录] → [写 DB]
```

每一步失败都要清理 tmp,不得污染目标目录。

### 3.2 Git 安装(`install_from_git`)

输入:`repo_url`, `ref`(默认 `main`), `subdir`(可选), `slug`(可选)

流程:
1. 校验 URL:必须 `https://` 开头;解析 host,拒绝私网/回环(见 §4 安全护栏)
2. 创建 tmp 目录 `~/.hermes/tmp/skill_install_<uuid>/`
3. `git clone --depth=1 --branch <ref> <url> <tmp>/repo` —— 超时 120s
4. 若提供 `subdir`,源路径 = `<tmp>/repo/<subdir>`;否则 = `<tmp>/repo`
5. 移除 `.git` 目录
6. 校验:
   - 源路径下有 `SKILL.md`
   - 解析 frontmatter,拿到 `name`
   - 推断 slug:优先参数 `slug`,否则用 frontmatter 的 `name`,否则用 repo 名(末段)
   - slug 合法性(正则)
7. 大小/文件数/路径逃逸检查(见 §4)
8. 记录 commit sha:`git -C <tmp>/repo rev-parse HEAD`
9. 冲突处理:
   - 若目标 slug 不存在 → 继续安装
   - 若目标 slug 已存在且 DB 中来源相同(`source_type/source_url/subdir`) → 允许覆盖安装
   - 若目标 slug 已存在但来源不同 → 返回 `409`,并附带现有来源摘要,提示用户先卸载再安装
10. 原子替换:
   - 目标 = `<profile>/skills/<slug>/`
   - 若已存在 → 先 `mv` 到 `<profile>/skills/.trash/<slug>.<timestamp>/`
   - `mv <tmp>/skill_content → 目标`
   - 成功后 `rm -rf .trash`;失败则 `mv` 回来
11. upsert DB 记录,`source_type="git"`, `source_url=repo_url`, `source_ref=<ref>`, `resolved_commit_sha=<sha>`, `subdir=<subdir>`
12. `rm -rf <tmp>`

### 3.3 卸载(`uninstall`)

- 校验 slug
- `rm -rf skills/<slug>/`
- 删 DB 记录(若有)
- 若是 local skill,语义同样是删除当前 agent profile 下的真实目录
- 幂等:目录不存在也视为成功

### 3.4 重新安装/升级(`reinstall`)

- 查 DB 记录,没有 → 返回 400 "手动安装的 skill 无法自动升级"
- 按 `source_type` 分派回 `install_from_*`,复用所有参数
- 等价于先装一遍,会走完整的原子替换

### 3.5 查看(`get_skill`)

- 读 `<profile>/skills/<slug>/SKILL.md`
- 返回 frontmatter + body + 绝对路径

---

## 4. 安全护栏

### 4.1 URL 校验(git 通用)

```python
def validate_source_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("only https:// is supported")
    host = parsed.hostname or ""
    # 拒绝明确的内网/回环
    import ipaddress, socket
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError(f"host resolves to private/reserved address: {ip}")
    except socket.gaierror:
        raise ValueError(f"cannot resolve host: {host}")
```

### 4.2 路径逃逸

- git clone 后扫描目录
- 拒绝任何绝对 symlink
- 拒绝任何指向仓库外的 symlink

### 4.3 资源限制

| 项 | 上限 |
|---|---|
| 单个 skill 总大小 | 10 MB |
| 文件总数 | 500 |
| 单文件大小 | 5 MB |
| git clone 超时 | 120 s |

超限直接 abort,清理 tmp。

### 4.4 原子性

- 所有落盘操作在 `<profile>/skills/.tmp_<uuid>/` 完成
- 最终一步 `os.rename` 到 `skills/<slug>/`
- 若目标已存在,先 rename 到 `skills/.trash/<slug>.<ts>/`,成功后删除,失败还原

---

## 5. 服务层模块

### 5.1 新增文件:`app/services/skill_installer.py`

```python
def list_installed(profile_name: str) -> list[dict]:
    """扫文件 merge DB,每项:
       {slug, name, description, source_type, source_url,
        source_ref, resolved_commit_sha, subdir, installed_at, has_db_record, error?}"""

def get_skill(profile_name: str, slug: str) -> dict | None:
    """含 body 全文,用于 UI 详情展示。"""

def install_from_git(agent_id, *, repo_url, ref="main", subdir="",
                     slug=None) -> dict

def uninstall(agent_id, slug) -> None

def reinstall(agent_id, slug) -> dict
```

### 5.2 `app/services/registry.py` 新增

```python
def skills_dir_for(profile_name: str) -> Path:
    return HERMES_HOME / "profiles" / profile_name / "skills"

def skill_dir(profile_name: str, slug: str) -> Path:
    return skills_dir_for(profile_name) / slug

def skill_md_path(profile_name: str, slug: str) -> Path:
    return skill_dir(profile_name, slug) / "SKILL.md"
```

### 5.3 `app/services/agents.py` 的 `create_agent` 末尾增加

```python
registry.skills_dir_for(profile_name).mkdir(parents=True, exist_ok=True)
```

### 5.4 Frontmatter 工具(`app/services/skill_frontmatter.py`)

```python
def parse(content: str) -> tuple[dict, str]:
    """返回 (frontmatter_dict, body_markdown)。
       无 frontmatter 时 frontmatter_dict = {}。"""

def dump(frontmatter: dict, body: str) -> str:
    """序列化回 markdown 字符串,frontmatter 用 yaml.safe_dump。"""
```

不引入 `python-frontmatter` 第三方库,自己写 30 行基于 `---` 分隔的简单解析即可。

---

## 6. API 层

### 6.1 新增蓝图:`app/controllers/agent_skills.py`

注册到 `app/__init__.py`。所有端点先 `store.find_agent(agent_id)` → 拿 `profile_name` → 调 service。

### 6.2 端点清单

| 方法 | 路径 | Body / Query | 返回 |
|---|---|---|---|
| GET | `/api/agents/<agent_id>/skills` | - | `{ok, skills: [...]}` |
| GET | `/api/agents/<agent_id>/skills/<slug>` | - | `{ok, skill: {..., body}}` |
| POST | `/api/agents/<agent_id>/skills/install` | `{source_type:"git", source_url, ref?, subdir?, slug?}` | `{ok, job_id}` (异步) |
| POST | `/api/agents/<agent_id>/skills/<slug>/reinstall` | - | `{ok, job_id}` (异步) |
| DELETE | `/api/agents/<agent_id>/skills/<slug>?confirm=1` | - | `{ok}` |

### 6.3 异步执行模型

安装可能 30s~2min,不能阻塞 HTTP。复用项目已有的模式:

- 接口立即返回 `{ok: true, job_id: "<uuid>"}`
- 用线程池 `concurrent.futures.ThreadPoolExecutor`(新增)跑安装任务
- 任务通过 `store.push_event()` 推 SSE:
  - `skill.install.started` `{job_id, agent_id, slug?, source}`
  - `skill.install.done` `{job_id, agent_id, skill: {...}}`
  - `skill.install.failed` `{job_id, agent_id, error}`
- 前端订阅同一个 SSE 通道,按 `job_id` 匹配进度

一期不做细粒度 phase 进度,只做最小 job 状态:安装中 / 成功 / 失败。

### 6.4 错误码

| HTTP | 场景 |
|---|---|
| 400 | 参数缺失、URL 非法、slug 非法 |
| 404 | agent 不存在、skill 不存在 |
| 409 | 同 slug 已安装且来源不同(返回现有来源摘要),或并发安装冲突 |
| 422 | SKILL.md 缺失或 frontmatter 非法 |
| 504 | clone 超时 |
| 500 | 未分类错误,详情写 `last_error` |

---

## 7. Leader 能力感知(`list_workers()` 增强)

`app/mcp_server.py` 的 `list_workers()` 返回体中每个 worker 增加:

```python
from .services import skill_installer

"skills": [
    {"slug": s["slug"], "name": s["name"], "description": s["description"]}
    for s in skill_installer.list_installed(a["profile_name"])
],
```

**性能**:list_installed 扫文件 + 一次 DB 查询,worker 数 * skill 数通常 < 100,单次调用可接受。若后续发现瓶颈,再加 60s 内存缓存(按 profile_name,mtime 校验失效)。

不需要改 `SOUL.md`。skill 生效由 Hermes 原生 profile skills 机制负责。

---

## 8. 前端设计(`app/templates/index.html`)

### 8.1 入口

Agent 详情抽屉现有 tabs(基本信息 / SOUL.md / 历史 / ...)中新增一个 **Skills** tab,位置紧跟 SOUL.md。

### 8.2 Skills tab 布局

```
┌─────────────────────────────────────────────────────────────────┐
│  Skills (3 已安装)                       [+ 安装 skill ▾]        │
├─────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ ● code-review                                     [git]  │  │
│  │ Review PRs for correctness, style, and security issues.   │  │
│  │ ↳ github.com/foo/code-review @ main · a3f2c1 · 2026-04-15  │  │
│  │ [查看] [⟳ 更新] [🗑 卸载]                                  │  │
│  ├───────────────────────────────────────────────────────────┤  │
│  │ ● custom-local                                  [local]  │  │
│  │ (无来源记录,手动放入)                                      │  │
│  │ [查看] [🗑 卸载]                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**列表项字段**:
- 一行标题 + 一行 description + 一行来源/安装时间
- 右上角 badge:来源类型(git / local)
- 操作按钮:`查看`(抽屉展开 SKILL.md 只读预览) / `⟳ 更新`(仅有 DB 记录时显示) / `🗑 卸载`

### 8.3 "安装 skill" 下拉菜单

点击后一个选项:
- **从 Git 仓库安装...**

### 8.4 安装弹窗

#### Git 安装弹窗
```
┌─ 从 Git 仓库安装 skill ─────────────────────┐
│ 仓库 URL:     [https://github.com/...]      │
│ 分支/Tag:     [main]                        │
│ 子目录(可选): [skills/foo]                  │
│ Slug(可选):   [留空自动推断]                 │
│                                             │
│ ⓘ 仅支持公开的 https 仓库                   │
│                                             │
│              [取消]  [开始安装]             │
└─────────────────────────────────────────────┘
```

### 8.5 安装进度区

提交后,弹窗变为进度面板,订阅 SSE 按 `job_id` 过滤事件:

```
┌─ 正在安装 skill ──────────────────────────┐
│ 正在从 Git 安装…                           │
│ 仓库: github.com/foo/bar                   │
│ ref: main                                  │
│ 状态: cloning / success / failed           │
│                                           │
│                                  [关闭]   │
└───────────────────────────────────────────┘
```

成功 → 关闭弹窗,Skills 列表刷新,顶部 toast "已安装:code-review"。
失败 → 弹窗保留,显示红色错误信息 + 重试按钮。

### 8.6 卸载确认

点击 `🗑 卸载` 弹二次确认:

```
确定卸载 "code-review" 吗?
此操作将删除 ~/.hermes/profiles/<profile>/skills/code-review/ 整个目录。
[取消]  [确认卸载]
```

对 `source_type === "local"` 的条目,加一句提示:"此 skill 未由平台安装,仍要删除吗?"

### 8.7 "查看" 抽屉

从右侧滑出一个只读面板,显示:
- Frontmatter 表格
- SKILL.md 正文(markdown 渲染,不可编辑)
- 底部提示:"如需修改,请直接编辑 `<绝对路径>`"

---

## 9. 创建/删除 agent 的联动

### 9.1 创建 agent

`hermes profile create --clone` 会把源 profile 整个目录(含 `skills/`)克隆到新 profile,因此**新 agent 的 skills 目录可能已非空**——这些是从源 profile 继承来的 skill。

**设计决策:保留继承**

- 不在创建时清空 `skills/`,尊重源 profile 作为"模板"的设计意图
- 继承来的 skill 在 DB 中无 install 记录,列表里显示为 `source_type="local"`
- 用户可以随时通过 UI 卸载不需要的条目

**平台代码唯一要做的**:兜底建目录(防止源 profile 本身没有 `skills/`)。在 `app/services/agents.py` `create_agent()` 末尾增加:

```python
registry.skills_dir_for(profile_name).mkdir(parents=True, exist_ok=True)
```

### 9.2 删除 agent
现有 `delete_hermes_profile()` 会删整个 profile 目录,skills 自动消失。
**唯一需要新增**:删 agent 时一并清理 DB 中的 `agent_skill_installs` 记录:
```python
# app/services/agents.py delete_agent() 里新增
from ..db.session import SessionLocal
from ..db.models import AgentSkillInstallRecord
with SessionLocal() as db:
    db.query(AgentSkillInstallRecord).filter_by(profile_name=profile_name).delete()
    db.commit()
```

### 9.3 建表方式

本期沿用现有 SQLAlchemy `Base.metadata.create_all()` 自动建新表机制,不单独引入 migration。

- 适用范围:新增 `agent_skill_installs` 表
- 不适用范围:后续如果修改已有表结构,再单独引入迁移方案

---

## 10. 测试点清单

### 10.1 单元/集成测试(`tests/`)

- `test_skill_installer_git`: mock `subprocess.run` 模拟 clone,验证成功/失败/超时分支
- `test_path_traversal`: git clone 后若发现越界 symlink → 安装失败,目标目录无污染
- `test_atomic_replace`: 安装过程中途抛异常 → 原目录完整保留
- `test_ssrf_guard`: URL 指向 `127.0.0.1` / `10.x` → 拒绝
- `test_uninstall_local`: 手动放入目录的 skill 可卸载
- `test_reinstall`: 修改上游 commit 后重装,文件被替换
- `test_install_same_source_replaces`: 同 slug 同来源允许覆盖
- `test_install_different_source_conflict`: 同 slug 不同来源返回 409 和来源摘要

### 10.2 手工验收

- 安装 `https://github.com/anthropics/claude-cookbooks`(subdir=某个 skill 目录)成功
- 前端 Git 安装入口可用,异步状态正确显示
- leader 的 `list_workers()` 返回包含 skills 字段
- 卸载后目录消失,DB 记录消失,UI 列表刷新

---

## 11. 实施计划

| PR | 范围 | 估时 |
|---|---|---|
| **PR1** | DB model + `skill_installer` 骨架 + git 安装 + uninstall + list + get + 安全护栏 + 单测 | 1.5 天 |
| **PR2** | `reinstall` + API 蓝图 + 最小异步 job + `list_workers()` 增强 | 0.75 天 |
| **PR3** | 前端 Skills tab + Git 安装弹窗 + 安装状态 UI + 卸载确认 + 只读预览抽屉 | 1 天 |

合计:约 3.25 天。

---

## 12. 未决/未来扩展(本期不做,留接口)

- **skill 市场协议**:`source_type` 预留 `"registry"`,后续加
- **Git 私有仓**:`source_type="git"` 下增加 `auth_token` 字段(加密存),后续加
- **skill 依赖声明**:SKILL.md frontmatter 加 `requires: [other-skill]`,安装时校验
- **版本锁定**:目前 git 装完记录 commit sha,但 UI 不展示"有新版本可用"。后续可加定时检查
- **archive URL / zip 上传**:本期不做,后续可作为新增安装来源补入
- **启用/禁用**:若后续要做,优先接 Hermes 原生 `config.yaml -> skills.disabled`
- **跨 agent 复制**:"把 agent A 的 skill X 复制到 agent B",纯前端操作即可,service 层已够用

---

## 附录 A:关键文件清单(实现时对照)

| 文件 | 动作 |
|---|---|
| `app/db/models.py` | 新增 `AgentSkillInstallRecord` |
| `app/services/registry.py` | 新增 `skills_dir_for` / `skill_dir` / `skill_md_path` |
| `app/services/skill_frontmatter.py` | **新文件**:parse / dump |
| `app/services/skill_installer.py` | **新文件**:全部安装/卸载/列表逻辑 |
| `app/services/agents.py` | `create_agent` 末尾建 skills 目录;`delete_agent` 清 DB |
| `app/controllers/agent_skills.py` | **新文件**:REST 蓝图 |
| `app/__init__.py` | 注册新蓝图 |
| `app/mcp_server.py` | `list_workers()` 增加 `skills` 字段 |
| `app/templates/index.html` | 新增 Skills tab + 相关 JS/CSS |
| `tests/test_skill_installer.py` | **新文件** |

---

## 附录 B:示例 API 调用序列

```bash
# 1. 从 git 安装
curl -X POST http://localhost:5000/api/agents/agent_alice/skills/install \
  -H 'Content-Type: application/json' \
  -d '{"source_type":"git","source_url":"https://github.com/foo/bar","ref":"main","subdir":"skills/code-review"}'
# → {"ok":true,"job_id":"j_abc123"}

# 2. 订阅 SSE 查看进度(前端已做)

# 3. 列出已安装
curl http://localhost:5000/api/agents/agent_alice/skills
# → {"ok":true,"skills":[{"slug":"code-review","name":"code-review",...}]}

# 4. 升级(重新 clone)
curl -X POST http://localhost:5000/api/agents/agent_alice/skills/code-review/reinstall

# 5. 卸载
curl -X DELETE 'http://localhost:5000/api/agents/agent_alice/skills/code-review?confirm=1'
```
