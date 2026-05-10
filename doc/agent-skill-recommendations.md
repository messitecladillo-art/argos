# Agent Skill 推荐清单

> 本文记录当前团队 agent 的推荐 skills。安装方式按项目现有 Skills 管理方案填写:使用 Git 仓库地址作为 `source_url`,使用 skill 目录作为 `subdir`。

| Agent | Skill 名称 | 安装地址 | Skill 介绍 | 注意事项 |
| --- | --- | --- | --- | --- |
| 领导 | `ai-team-orchestration` | 网页: https://github.com/github/awesome-copilot/tree/main/skills/ai-team-orchestration<br>`source_url`: `https://github.com/github/awesome-copilot`<br>`subdir`: `skills/ai-team-orchestration` | 强化多 agent 团队编排能力,用于理解目标、拆解任务、选择合适 worker、组织多轮协作并汇总结果。 | 适合 Leader profile。安装后仍要遵守项目里的 `mcp_agent_bus_list_workers` 和 `mcp_agent_bus_create_kanban_worker_tasks` 调度约束,不要让 skill 中的通用编排建议覆盖本项目团队总线规则。 |
| 领导 | `create-implementation-plan` | 网页: https://github.com/github/awesome-copilot/tree/main/skills/create-implementation-plan<br>`source_url`: `https://github.com/github/awesome-copilot`<br>`subdir`: `skills/create-implementation-plan` | 把需求整理成实施计划,包含目标、范围、任务拆解、执行顺序、风险和验收点。 | 适合在派发 worker 前使用。输出计划后应继续转成平台可追踪的 Kanban worker 子任务,避免只停留在自然语言计划。 |
| 领导 | `structured-autonomy-plan` | 网页: https://github.com/github/awesome-copilot/tree/main/skills/structured-autonomy-plan<br>`source_url`: `https://github.com/github/awesome-copilot`<br>`subdir`: `skills/structured-autonomy-plan` | 面向长任务的结构化自主执行计划,帮助明确目标、约束、检查点、继续条件和阻塞条件。 | 和长时任务/多轮 review 流程契合。使用时要结合系统 `max_rounds` 和 review checkpoint,避免无限继续派发。 |
| 开发者 | `acquire-codebase-knowledge` | 网页: https://github.com/github/awesome-copilot/tree/main/skills/acquire-codebase-knowledge<br>`source_url`: `https://github.com/github/awesome-copilot`<br>`subdir`: `skills/acquire-codebase-knowledge` | 帮助开发者快速理解代码库结构、关键模块、架构约定和已有实现模式。 | 适合开发任务开始阶段。应优先读取本仓库真实代码和文档,不要用泛化框架经验替代项目约定。 |
| 开发者 | `review-and-refactor` | 网页: https://github.com/github/awesome-copilot/tree/main/skills/review-and-refactor<br>`source_url`: `https://github.com/github/awesome-copilot`<br>`subdir`: `skills/review-and-refactor` | 支持代码审查、识别坏味道、提出局部重构方案并执行小范围质量改进。 | 适合已有代码质量改进。使用时应控制改动范围,避免把业务需求实现任务扩大成无关重构。 |
| 开发者 | `gh-fix-ci` | 网页: https://github.com/openai/skills/tree/main/skills/.curated/gh-fix-ci<br>`source_url`: `https://github.com/openai/skills`<br>`subdir`: `skills/.curated/gh-fix-ci` | 使用 GitHub CLI 检查 PR 的 GitHub Actions 失败日志,定位失败原因,形成修复计划并处理 CI 问题。 | 依赖本机安装并登录 `gh`,且需要仓库和 workflow 权限。只适用于 GitHub Actions;如果 CI 来自其他平台,只能作为故障分析参考。 |
| 测试 | `pytest-coverage` | 网页: https://github.com/github/awesome-copilot/tree/main/skills/pytest-coverage<br>`source_url`: `https://github.com/github/awesome-copilot`<br>`subdir`: `skills/pytest-coverage` | 面向 Python 项目的 pytest 覆盖率分析和补测,帮助发现未覆盖逻辑并添加针对性测试。 | 适合本项目 Flask/Python 后端。运行前确认测试依赖和数据库/临时目录配置,避免把环境问题误判为业务缺陷。 |
| 测试 | `playwright-generate-test` | 网页: https://github.com/github/awesome-copilot/tree/main/skills/playwright-generate-test<br>`source_url`: `https://github.com/github/awesome-copilot`<br>`subdir`: `skills/playwright-generate-test` | 根据 Web 页面和用户流程生成 Playwright E2E 测试,覆盖关键交互和回归路径。 | 需要可访问的本地或远程 Web 页面。生成测试前应先启动应用并确认测试账号、端口、数据状态。 |
| 测试 | `webapp-testing` | 网页: https://github.com/github/awesome-copilot/tree/main/skills/webapp-testing<br>`source_url`: `https://github.com/github/awesome-copilot`<br>`subdir`: `skills/webapp-testing` | 提供 Web 应用测试策略、测试用例设计、缺陷记录和回归检查框架。 | 更适合测试设计和测试报告,不一定自动生成可运行测试代码。可与 `playwright-generate-test` 搭配使用。 |
| 产品 | `deliver-prd` | 网页: https://github.com/product-on-purpose/pm-skills/tree/main/skills/deliver-prd<br>`source_url`: `https://github.com/product-on-purpose/pm-skills`<br>`subdir`: `skills/deliver-prd` | 输出产品需求文档,包括背景、目标、范围、用户故事、验收标准、风险和发布考虑。 | 适合产品 agent 在开发前沉淀需求。PRD 输出后建议交给 Leader 拆成实施计划和 worker 子任务。 |
| 产品 | `deliver-acceptance-criteria` | 网页: https://github.com/product-on-purpose/pm-skills/tree/main/skills/deliver-acceptance-criteria<br>`source_url`: `https://github.com/product-on-purpose/pm-skills`<br>`subdir`: `skills/deliver-acceptance-criteria` | 为功能需求生成清晰、可验证的验收标准,方便开发实现和测试验证。 | 验收标准应尽量可测试、可观察。对存在歧义的业务规则,应先要求补充输入,不要自行假设。 |
| 产品 | `deliver-edge-cases` | 网页: https://github.com/product-on-purpose/pm-skills/tree/main/skills/deliver-edge-cases<br>`source_url`: `https://github.com/product-on-purpose/pm-skills`<br>`subdir`: `skills/deliver-edge-cases` | 系统性梳理边界场景、异常流程、极端输入和潜在失败路径。 | 产品和测试 agent 都可使用。适合在需求评审或测试设计前运行,但输出需要结合当前版本范围做取舍。 |

## 安装示例

```bash
curl -X POST http://localhost:5000/api/agents/<agent_id>/skills/install \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "git",
    "source_url": "https://github.com/github/awesome-copilot",
    "ref": "main",
    "subdir": "skills/ai-team-orchestration"
  }'
```

安装后需要重启对应 agent 会话,让 Hermes 重新读取该 profile 下的 `skills/` 目录。
