# 决策记录：AI 多Agent Web 控制台阶段收口

日期：2026-04-21 22:35:26
决策人：ceo

## 决策
将项目状态正式定义为：
“后端真实只读 MVP 已独立实证成立，进入前端控制台 MVP 开发阶段。”

## 依据
1. 标准启动命令已成功启动并出现 API listening on http://127.0.0.1:3000
2. GET /api/agents 返回 200
3. GET /api/agents/agt_engineer/output 返回 200
4. GET /api/agents/agt_unknown/output 返回 404
5. 数据来自真实 Hermes / tmux / read-agent-output.sh，而非 mock

## 范围冻结
- 首期只做只读控制台
- 只认两条接口：GET /api/agents、GET /api/agents/:agentId/output
- 不做群发、不做实时流式、不做分析面板、不扩字段、不新增第三条接口

## 下一阶段
- 前端接入 agent 列表与 output 展示
- 支持 agent 间切换
- 指令输入先预留，不作为首发阻塞项

## 风险
- QA 纠偏终验新版待补
- 写入链路复杂度显著高于只读链路
- 多 agent 批量发送必须延后
