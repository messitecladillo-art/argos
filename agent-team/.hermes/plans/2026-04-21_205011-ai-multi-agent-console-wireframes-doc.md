# AI 多Agent Web 控制台页面线框说明稿

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 将已确认的 AI 多Agent Web 控制台 MVP 页面线框需求沉淀为设计/前端可直接引用的正式文档。

**Architecture:** 文档聚焦 4 个核心页面/状态模块：首页列表、agent 详情与时间线、群发入口、异常与空加载态，并补充信息层级规则，便于设计稿与前端布局实现保持一致。

**Tech Stack:** Markdown 文档

---

## Current context / assumptions
- 已确认 MVP 的核心范围是：看状态、查记录、发指令、可切换 agent、可处理异常。
- 页面至少覆盖：首页/agent 列表页、agent 详情+聊天时间线页、群发发送入口、异常/空态/加载态。
- 当前任务目标是文档落盘，不涉及代码实现。

## Proposed approach
1. 将已确认的页面说明整理为正式 markdown 文档。
2. 结构以设计/前端直接可引用为目标，保持短句、可读、可落图。
3. 同步保存一份 plan 文件，记录本次执行准备文档化内容。

## Step-by-step plan
1. 确认目标文件路径与文档标题。
2. 按要求整理 5 个章节内容。
3. 写入正式文档到 `product/docs/ai-multi-agent-console-wireframes-v1.md`。
4. 保存一份 plan 记录到 `.hermes/plans/2026-04-21_205011-ai-multi-agent-console-wireframes-doc.md`。
5. 回复已写入路径与一句说明。

## Files likely to change
- Create/Modify: `product/docs/ai-multi-agent-console-wireframes-v1.md`
- Create: `.hermes/plans/2026-04-21_205011-ai-multi-agent-console-wireframes-doc.md`

## Tests / validation
- 检查目标文件已生成。
- 检查文档包含以下章节：
  - 控制台首页/agent列表页线框说明
  - agent详情+聊天时间线页线框说明
  - 群发发送入口线框说明
  - 异常空态加载态说明
  - 区域优先级与信息层级
- 检查内容为结构化短版，可直接给设计/前端使用。

## Risks, tradeoffs, and open questions
- 风险：如果后续首页布局从列表改为看板，文档需增补布局变体。
- 取舍：当前只沉淀 MVP 级线框说明，不扩展到视觉规范和组件 token。
- 开放问题：群发入口最终采用独立页、抽屉还是弹层，需设计阶段最终定稿。
