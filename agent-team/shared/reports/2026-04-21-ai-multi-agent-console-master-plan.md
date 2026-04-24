# AI 多Agent Web 控制台项目总方案（CEO 汇总）

日期：2026-04-21 22:35:26
负责人：ceo
项目：Hermes AI 多Agent Web 控制台

> 说明：本方案基于 CEO 已真实调度 product、engineer、qa、wechat、xiaohongshu 后的汇总。文中明确区分：已真实收到的回复、仍在等待的回复、以及 CEO 判断。

## 1. 当前结论

项目已完成“真实 Hermes 只读链路”验证，可以进入“前端控制台 MVP 开发阶段”。

当前最稳妥的项目定义是：
- 已完成后端只读 MVP 的真实验证
- 未完成完整产品
- 可立即进入前端控制台接入与展示
- QA 纠偏终验新版仍待补齐归档

## 2. 实际调度情况

### 2.1 已真实派发的角色
- product
- engineer
- qa
- wechat
- xiaohongshu

### 2.2 已收到回复
- product：已回复
- engineer：已回复
- qa：已回复纠偏新版，最终结论为“有条件通过”
- wechat：已回复
- xiaohongshu：已回复

### 2.3 仍在等待
- 无

### 2.4 状态说明
此前曾出现一次终端审批拦截，导致 QA 纠偏请求未即时送达；后续已重新真实派发并成功收到 QA 纠偏新版结论，因此当前无待回复核心角色。

## 3. 已实证成立的事实（CEO 独立复验）

以下为已独立实测通过的事实，不是 engineer 自述：

1. 标准启动命令已成功启动，并出现日志：
   - API listening on http://127.0.0.1:3000
2. GET /api/agents 返回 200
3. GET /api/agents/agt_engineer/output 返回 200
4. GET /api/agents/agt_unknown/output 返回 404
5. 数据来源为真实 Hermes / tmux / read-agent-output.sh 链路，而非 mock

结论：后端只读链路已经成立。

## 4. 各角色结论摘要

### 4.1 product 结论摘要

#### MVP 定义
首期只做：
- agent 列表
- 单 agent output 查看
- 不同 agent 间切换
- 真实 Hermes 只读接入

#### 冻结口径
- agents 字段冻结：agent_id、name、profile、status、last_active_at
- output 字段冻结：agent_id、items[].id、items[].type、items[].content、items[].created_at
- 首页只依赖 GET /api/agents
- 详情页只依赖 GET /api/agents/:agentId/output

#### 非目标
- 不做群发
- 不做实时流式
- 不做分析面板
- 不扩页面、不扩字段、不新增第三条接口

#### CEO 判断
需求边界清晰，范围健康，适合快速落地第一版。

### 4.2 engineer 结论摘要

#### 技术架构
- 后端：Node API 层
- 数据源：真实 Hermes tmux + read-agent-output.sh
- 接口：
  - GET /api/agents
  - GET /api/agents/:agentId/output
- 首期前端建议采用轮询，不急于上流式架构

#### 阶段计划
- Phase 1：后端只读链路打通（已实证完成）
- Phase 2：前端控制台读取与切换
- Phase 3：单 agent 指令下发
- Phase 4：多 agent 分别下发 / 批量分发 / 审计控制

#### CEO 判断
技术路线正确，当前已具备从“方案阶段”进入“前端产品化阶段”的条件。

### 4.3 qa 结论摘要

#### 已收到的 QA 版本
- QA 已给出纠偏新版结论
- 通过项：标准命令可复现启动；`GET /api/agents` 返回 200；`GET /api/agents/agt_engineer/output` 返回 200；`GET /api/agents/agt_unknown/output` 返回 404；上述结果来自 CEO 独立实测
- 不通过项：字段口径完整性、真实数据一致性/无串线、字段稳定性与异常语义仍需补做内容级验收
- 最终结论：有条件通过

#### CEO 判断
当前项目状态应表述为：
- 技术上，后端只读链路已被独立实证通过
- 验收上，基础可用性通过，内容级验收仍需补齐
- 项目可进入前端控制台 MVP 开发阶段
### 4.4 wechat 内容方案摘要

内容主线：
- 多 Agent 控制台第一步不是先做调度，而是先做真实只读能力
- 先把“状态可见、输出可见、切换可见”做成可信事实
- 面向产品经理、AI 工具从业者、技术负责人，强调克制、可信、工程化落地

推荐主稿方向：
- 为什么 AI 多Agent 控制台，第一步必须先做只读能力

### 4.5 xiaohongshu 内容方案摘要

内容主线：
- 先证明“看得见”，再做“发得出、控得住、跑得稳”
- 用开发日志 / MVP 复盘方式讲清楚路线选择
- 面向独立开发者 / AI 工具爱好者，真实、克制、不浮夸

推荐首发方向：
- 我为什么没有先做多 agent 群发，而是先把只读控制台跑通

## 5. 最终统一方案

### 5.1 项目目标
构建一个面向 Hermes 多个 agent/profile 的 Web 控制台，让用户能够：
- 查看多个 agent 的工作状态
- 查看每个 agent 的输入输出 / 聊天记录
- 在不同 agents 之间切换
- 后续逐步支持单 agent 发指令，再扩展为多个 agents 分别发指令

### 5.2 MVP 范围
MVP 只做“真实只读控制台 + 指令入口预留”：
- Agent 列表
- Agent 状态展示
- Agent output / 聊天记录查看
- Agent 间切换
- 基础刷新/轮询
- 指令输入区可先占位，不作为首发阻塞项

### 5.3 核心功能优先级

#### P0
- agents 列表读取
- 单 agent output 读取
- 非法 agent 错误处理
- agent 切换查看
- 刷新 / 轮询

#### P1
- 单 agent 指令下发
- 指令发送反馈
- output 增量展示
- 最近活跃排序

#### P2
- 多 agent 分别发指令
- 批量发送
- 审计记录
- 权限控制
- 更完整的实时机制

### 5.4 非目标
首期不做：
- 编排器
- 群发能力
- 复杂权限体系
- 分析后台
- 跨组织协作
- 一次性全功能 IM 化

### 5.5 信息架构
- 左侧：Agent 列表 / 状态 / 最近活跃
- 中间：当前 Agent 聊天记录 / output 流
- 顶部：当前 Agent 身份 / profile / 状态 / 切换入口
- 右侧或底部：详情面板 / 指令输入区（后续接写入）
- 全局：错误提示 / 刷新状态 / 接口健康状态

### 5.6 技术架构

#### 后端
- Node API 层
- 对接真实 Hermes tmux / read-agent-output.sh
- REST 先行
- 后续按需要补 WebSocket/SSE

#### 前端
- Web 控制台
- 首页 agent 列表
- 详情页 / 主工作区 output 展示
- 先采用轮询

#### 核心数据模型
- Agent：agent_id / name / profile / status / last_active_at
- OutputItem：id / type / content / created_at

## 6. 阶段计划

### 阶段 1：后端只读 MVP
状态：已实证完成
交付：
- 启动命令可用
- /api/agents
- /api/agents/:agentId/output
- 非法 agentId 返回 404

### 阶段 2：前端控制台 MVP
目标：
- 展示 agent 列表
- 展示单 agent output
- 支持切换 agent
- 提供基础刷新机制

建议：优先做成一个可用页面，不追求复杂组件化。

### 阶段 3：单 agent 指令下发
目标：
- 接入聊天输入框
- 后端写入到指定 agent
- 展示发送状态与新增输出

### 阶段 4：多 agent 指令分发
目标：
- 不同 agents 分别下发
- 批量操作
- 审计与异常隔离

## 7. 关键风险

1. QA 文档口径滞后
- 当前旧结论已失效
- 新版未补到位
- 属于验收文档待修正，不是当前只读链路的技术阻塞

2. 写入链路复杂度显著更高
- 涉及幂等、串线、失败回执、权限、误发
- 不应与只读 MVP 绑死

3. 多 agent 批量发送风险更高
- 容易出现状态不同步、错发、审计不清
- 必须晚于单 agent 写入闭环

4. 实时方案过早复杂化
- 首期轮询即可
- 不建议在 MVP 期引入复杂流式系统

## 8. 下一步建议

### 最高优先级
立即进入前端控制台 MVP 开发：
- 接入 GET /api/agents
- 接入 GET /api/agents/:agentId/output
- 完成列表、切换、输出展示

### 第二优先级
补齐 QA 纠偏终验归档：
- 待系统允许后，重新获取新版 QA 结论
- 作为正式验收归档材料

### 第三优先级
准备外部内容发布：
- wechat：发布“为什么多 Agent 控制台要先做只读能力”
- xiaohongshu：发布“为什么我先把多 Agent 控制台的只读链路跑通”

## 9. CEO 最终判断

当前项目不应再被定义为“只有方案，没有实物”；
也不应被定义为“完整产品已完成”。

正确表述应为：
- 后端真实只读 MVP 已被独立实证成立
- 项目已具备进入前端控制台 MVP 开发的条件
- QA 纠偏终验新版仍待补充归档

即：
项目已从方案阶段进入可产品化阶段。
