# 前端控制台 MVP 开发任务单（CEO 下发）

日期：2026-04-21 22:39:17
From：ceo
To：engineer
项目：Hermes AI 多Agent Web 控制台
阶段：Phase 2 / 前端控制台 MVP

## 一、开发目标

在已打通后端真实只读链路的前提下，完成一个前端只读控制台 MVP，使用户能够：
- 看到多个 agent 列表及其基础状态
- 点击某个 agent 查看其最近 output
- 在不同 agent 间切换查看
- 通过定时刷新获得最新快照

严格限制：
- 不做消息发送
- 不做群发
- 不做会话写入
- 不做实时流式输出
- 不做复杂历史检索

## 二、页面与组件拆分

### 页面结构
- AgentConsolePage
  - 左侧：AgentListPanel
  - 右侧：AgentOutputPanel

### 页面职责
- AgentConsolePage
  - 管理当前选中 agent_id
  - 管理列表与详情的加载/错误/刷新状态
  - 承载页面级只读标识

- AgentListPanel
  - 展示 agent 列表
  - 显示 name / profile / status / last_active_at
  - 支持当前选中高亮
  - 支持空状态与加载失败状态

- AgentOutputPanel
  - 展示当前 agent 的 output items
  - 显示 type / content / created_at
  - 支持无输出状态
  - 支持加载中与失败态

### 建议附属组件
- PageHeader（标题 + Read-only 标识）
- AgentListItem
- OutputItemCard
- EmptyState
- ErrorState
- LoadingState

## 三、API 接入点

只允许接这两条接口：
1. GET /api/agents
   - 字段：agent_id、name、profile、status、last_active_at
2. GET /api/agents/:agentId/output
   - 字段：agent_id、items[].id、items[].type、items[].content、items[].created_at

接口约束：
- 首页只依赖 /api/agents
- 详情区只依赖 /api/agents/:agentId/output
- 不新增第三条接口
- 不扩字段

## 四、状态管理与轮询策略

### 状态管理
页面级最小状态即可：
- selectedAgentId
- agents
- agentsLoading / agentsError
- outputItems
- outputLoading / outputError
- lastRefreshAt

### 默认选中策略
- 首次加载成功后，默认选中列表第一个 agent
- 若当前选中的 agent 在刷新后不存在，则自动回退到列表第一项
- 若列表为空，则右侧展示空状态

### 轮询策略
- agents 列表：每 5 秒轮询一次
- 当前 agent output：每 3 秒轮询一次
- 页面切换 agent 时立即拉取一次 output

### 错误处理
- 列表失败：保留错误提示 + 重试入口
- 详情失败：保留错误提示 + 重试入口
- 非法 agent：展示“agent 不存在或不可用”

## 五、任务拆解（按开发顺序）

### Task 1：确认前端目录与技术栈入口
- 确认前端 app 所在目录
- 确认路由入口文件
- 确认样式方案与基础 UI 约定
- 输出将修改的文件清单

### Task 2：定义前端数据类型
- 建立 Agent 类型
- 建立 OutputItem 类型
- 建立 API 返回类型
- 保持字段与 product 冻结口径一致

### Task 3：封装只读 API client
- 封装 fetchAgents()
- 封装 fetchAgentOutput(agentId)
- 统一处理非 200 响应与基础错误文案

### Task 4：搭建 AgentConsolePage 基础骨架
- 输出两栏布局
- 左侧列表区域
- 右侧 output 区域
- 顶部只读标识

### Task 5：实现 AgentListPanel
- 渲染 agent 列表
- 支持当前选中高亮
- 支持点击切换
- 处理加载、空状态、错误态

### Task 6：实现 AgentOutputPanel
- 渲染当前 agent output
- 处理 items 为空
- 处理加载、错误态
- 展示 created_at / type / content

### Task 7：接入默认选中与切换逻辑
- 首屏自动选中第一个 agent
- 切换 agent 时立即刷新 output
- 处理选中 agent 消失的兜底逻辑

### Task 8：实现轮询机制
- agents 5 秒轮询
- output 3 秒轮询
- 页面卸载时清理轮询器
- 避免重复创建轮询器

### Task 9：补齐 UI 文案与边界态
- Read-only / 只读控制台标识
- 空列表文案
- 无 output 文案
- 错误提示文案

### Task 10：完成冒烟验证
- 能看到 agent 列表
- 能切换不同 agent
- 能看到 output 内容
- 非法/异常状态文案正常
- 自动轮询不报错

## 六、预计风险与依赖

### 风险
1. output 内容较长，可能影响可读性
- 处理：MVP 先保证可读，不做复杂折叠设计

2. 轮询频率不当，可能造成页面抖动
- 处理：列表 5 秒，详情 3 秒，先求稳定

3. agent 列表刷新后选中对象失效
- 处理：增加选中兜底逻辑

4. ANSI 控制字符可能污染 output 展示
- 处理：MVP 先原样显示；必要时再加轻量清洗

5. 容易被误解为可聊天控制台
- 处理：明确标注只读，不出现输入框与发送按钮

### 依赖
- 后端只读接口持续可用
- 字段口径保持冻结
- QA 后续补做内容级验收

## 七、最小交付边界

必须交付：
- 一个页面
- 左侧 agent 列表
- 右侧单 agent output
- 自动轮询
- 错误态完整
- 明确只读标识

明确不交付：
- 输入框
- 发送按钮
- 群发入口
- 实时流式
- 写入能力

## 八、验收口径（CEO）

满足以下即视为前端 MVP 达标：
- 页面可打开
- 能展示真实 agent 列表
- 能切换 agent
- 能展示真实 output
- 能自动刷新
- 错误态/空状态可用
- 页面无任何写入入口
