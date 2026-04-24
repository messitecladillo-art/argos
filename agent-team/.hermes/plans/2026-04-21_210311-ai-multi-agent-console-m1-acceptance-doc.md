# AI 多Agent Web 控制台 M1 验收清单落盘计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 将 M1 验收映射整理为正式验收清单文档，供 engineer 与 qa 在项目启动阶段直接引用。

**Architecture:** 文档按验收目标、页面模块拆分、模块验收点、优先级标注和实现边界提醒五部分组织，保持短版和执行导向。

**Tech Stack:** Markdown 文档

---

## Current context / assumptions
- 已确认 M1 的范围围绕首页列表、详情时间线、发送区、群发入口和异常态。
- 当前任务是把已有内容整理并落盘，不涉及实现代码。
- 目标路径为 `product/docs/ai-multi-agent-console-m1-acceptance-checklist.md`。

## Proposed approach
1. 复用已确认的 M1 验收映射内容。
2. 按用户指定的五个标题整理成正式文档。
3. 同步保存一份本次落盘计划到 `.hermes/plans/`。

## Step-by-step plan
1. 获取当前时间戳用于 plan 文件命名。
2. 整理 M1 验收清单 markdown 内容。
3. 写入正式文档到 `product/docs/ai-multi-agent-console-m1-acceptance-checklist.md`。
4. 保存 plan 文件到 `.hermes/plans/2026-04-21_210311-ai-multi-agent-console-m1-acceptance-doc.md`。
5. 回复已写入文件路径与一句说明。

## Files likely to change
- Create/Modify: `product/docs/ai-multi-agent-console-m1-acceptance-checklist.md`
- Create: `.hermes/plans/2026-04-21_210311-ai-multi-agent-console-m1-acceptance-doc.md`

## Tests / validation
- 检查目标文档已生成。
- 检查文档包含以下章节：
  - M1验收目标
  - 页面与模块拆分
  - 每个模块验收点
  - P0/P1 标注
  - 给 engineer 的实现边界提醒
- 检查内容简洁、结构化、偏执行。

## Risks, tradeoffs, and open questions
- 风险：若后续将群发入口提升为 M1 必须项，则 P0/P1 标注需调整。
- 取舍：当前文档只保留执行所需清单，不展开到测试用例级别。
- 开放问题：后续是否需要同步输出 qa test case 版本，可在下一阶段补充。
