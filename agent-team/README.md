# agent-team

这是为你当前 Hermes 多代理团队生成的共享工作区。

## Agents
- ceo
- product
- engineer
- qa
- xiaohongshu
- wechat

## Core Files
- `~/.hermes/AGENTS.md`：共享规则与上下文
- `~/.hermes/team-agents.md`：团队架构说明
- `~/.hermes/profiles/<name>/SOUL.md`：各 agent 灵魂文件
- `/Users/liuwenbin/agent-team/tmux-usage.md`：tmux 使用文档（完整说明）
- `/Users/liuwenbin/agent-team/scripts/send-to-agent.sh`：从 shell 直接给某个 agent 发消息
- `/Users/liuwenbin/agent-team/scripts/read-agent-output.sh`：读取某个 agent 最近输出
- `/Users/liuwenbin/agent-team/scripts/ask-agent.sh`：发消息后自动抓回复
- `/Users/liuwenbin/agent-team/scripts/collect-team-output.sh`：一次抓取全部 agent 最近输出
- `/Users/liuwenbin/agent-team/scripts/wait-all-agents.sh`：等待多个 agent 全部完成后再返回
- `/Users/liuwenbin/agent-team/scripts/dispatch-and-wait.sh`：并行派发给多个 agent，等待完成后再收集输出

## Start
```bash
bash /Users/liuwenbin/agent-team/scripts/start-team.sh
```

## Attach Existing Session
```bash
tmux attach -t hermes-team
```

## Quick Reference
```bash
# 启动团队
bash /Users/liuwenbin/agent-team/scripts/start-team.sh

# 进入现有 session
tmux attach -t hermes-team

# 查看 session
tmux ls

# 查看窗口
tmux list-windows -t hermes-team

# 给 engineer 发消息
/Users/liuwenbin/agent-team/scripts/send-to-agent.sh engineer "请检查当前项目的启动脚本"

# 发消息后直接看回复
/Users/liuwenbin/agent-team/scripts/ask-agent.sh product "请输出当前功能的 MVP 定义"

# 单独查看某个 agent 最近输出
/Users/liuwenbin/agent-team/scripts/read-agent-output.sh engineer

# 一次查看整个团队最近输出
/Users/liuwenbin/agent-team/scripts/collect-team-output.sh --lines 80

# 等 product / engineer / qa 全部完成
/Users/liuwenbin/agent-team/scripts/wait-all-agents.sh product engineer qa

# 并行派发并等待完成
/Users/liuwenbin/agent-team/scripts/dispatch-and-wait.sh \
  product="请输出 MVP 定义，并在完成时明确写已完成" \
  engineer="请输出最小技术方案，并在完成时明确写已完成" \
  qa="请输出最小验收清单，并在完成时明确写已完成"

# 关闭整个团队
tmux kill-session -t hermes-team
```

## 常用快捷键
- `Ctrl-b d`：detach，离开 tmux 但不停止 agents
- `Ctrl-b 0~5`：切换到 ceo / product / engineer / qa / xiaohongshu / wechat
- `Ctrl-b n`：下一个窗口
- `Ctrl-b p`：上一个窗口
- `Ctrl-b w`：打开窗口列表
- `Ctrl-b [`：进入滚动/复制模式

## 给每个窗口发送指令
方式一：进入 tmux 后手动发送

先进入：
```bash
tmux attach -t hermes-team
```

然后切到目标窗口：
- `Ctrl-b 0` → ceo
- `Ctrl-b 1` → product
- `Ctrl-b 2` → engineer
- `Ctrl-b 3` → qa
- `Ctrl-b 4` → xiaohongshu
- `Ctrl-b 5` → wechat

切过去后，像普通终端一样直接输入内容并回车即可。

方式二：从 shell 直接发送

```bash
/Users/liuwenbin/agent-team/scripts/send-to-agent.sh engineer "请检查当前项目的启动脚本，并告诉我有哪些风险。"
```

方式三：发完直接抓回复

```bash
/Users/liuwenbin/agent-team/scripts/ask-agent.sh qa "请输出最小验收清单。"
```

方式四：单独查看某个 agent 的最近输出

```bash
/Users/liuwenbin/agent-team/scripts/read-agent-output.sh --lines 80 wechat
```

方式五：一次查看整个团队最近输出

```bash
/Users/liuwenbin/agent-team/scripts/collect-team-output.sh --lines 80
```

方式六：等待多个 agent 都完成

```bash
/Users/liuwenbin/agent-team/scripts/wait-all-agents.sh product engineer qa
```

方式七：并行派发并等待完成

```bash
/Users/liuwenbin/agent-team/scripts/dispatch-and-wait.sh \
  product="请输出 MVP 定义，并在完成时明确写已完成" \
  engineer="请输出最小技术方案，并在完成时明确写已完成" \
  qa="请输出最小验收清单，并在完成时明确写已完成"
```

可用 agent：
- ceo
- product
- engineer
- qa
- xiaohongshu
- wechat

## 现在的协作模式
- 现在 ceo 不只是“口头调度”，而是应该通过脚本真实给其他 agent 发消息
- `send-to-agent.sh`：负责派单
- `read-agent-output.sh`：负责回收单个 agent 输出
- `ask-agent.sh`：适合快速测试单个 agent 的响应
- `collect-team-output.sh`：适合一次查看整队最近状态
- `wait-all-agents.sh`：适合在 ceo 派给多个 agent 后，等待全部完成再收口
- `dispatch-and-wait.sh`：适合一条命令完成“派发 → 等待 → 收集”

## wait-all-agents 的约定
- 默认会轮询指定 agent 的窗口输出
- 如果检测到这些完成信号之一，就视为完成：
  - `DONE`
  - `已完成`
  - `完成了`
  - `处理完成`
  - `任务完成`
  - `已回复`
  - `输出如下`
  - `结论如下`
- 如果检测到这些阻塞信号之一，会标记为 blocked：
  - `阻塞`
  - `卡住`
  - `无法继续`
  - `需要补充`
  - `缺少信息`
  - `等待中`
  - `blocked`

## dispatch-and-wait 的格式
- 参数必须写成：`agent="message"`
- 支持一次发给多个 agent
- 默认发送后等待所有目标 agent 完成，再自动收集团队输出

如果你只是暂时离开，不想停止团队：
- 按 `Ctrl-b d`

## 文档
- 完整 tmux 文档：`/Users/liuwenbin/agent-team/tmux-usage.md`
