# tmux 使用说明（Hermes 多代理团队）

本文档记录你当前 Hermes 多代理团队使用 tmux 的常用方法与命令。

适用场景：
- 管理 `hermes-team` 这个 6-agent 团队 session
- 在 ceo / product / engineer / qa / xiaohongshu / wechat 之间切换
- 日常启动、恢复、退出、关闭 tmux

---

## 1. 当前团队 session 信息

当前 tmux session 名称：
- `hermes-team`

当前窗口：
- `0: ceo`
- `1: product`
- `2: engineer`
- `3: qa`
- `4: xiaohongshu`
- `5: wechat`

---

## 2. 最常用命令

### 进入团队
```bash
tmux attach -t hermes-team
```

### 启动团队（如果 session 还没启动）
```bash
bash /Users/liuwenbin/agent-team/scripts/start-team.sh
```

### 查看当前有哪些 tmux session
```bash
tmux ls
```

### 查看 hermes-team 里有哪些窗口
```bash
tmux list-windows -t hermes-team
```

### 离开 tmux，但不关闭里面运行的 agents
快捷键：
- `Ctrl-b d`

说明：
- 这只是 detach
- tmux 和里面的 Hermes agents 会继续运行

### 重新进入 tmux
```bash
tmux attach -t hermes-team
```

### 关闭整个团队 session
```bash
tmux kill-session -t hermes-team
```

说明：
- 会把 6 个窗口里的 Hermes 一起关闭
- 这是“整队下线”命令

---

## 3. 窗口切换

tmux 默认前缀键：
- `Ctrl-b`

意思是：
- 先按住 `Ctrl`
- 再按 `b`
- 松开后再按后续功能键

### 直接切到某个 agent 窗口
- `Ctrl-b 0` → ceo
- `Ctrl-b 1` → product
- `Ctrl-b 2` → engineer
- `Ctrl-b 3` → qa
- `Ctrl-b 4` → xiaohongshu
- `Ctrl-b 5` → wechat

### 切到下一个窗口
- `Ctrl-b n`

### 切到上一个窗口
- `Ctrl-b p`

### 打开窗口列表并选择
- `Ctrl-b w`

这个命令很适合窗口多的时候使用。

---

## 4. 会话管理

### 查看所有 session
```bash
tmux ls
```

### 新建一个 session（通用写法）
```bash
tmux new -s session_name
```

例如：
```bash
tmux new -s test
```

### 连接到指定 session
```bash
tmux attach -t session_name
```

例如：
```bash
tmux attach -t hermes-team
```

### 删除指定 session
```bash
tmux kill-session -t session_name
```

例如：
```bash
tmux kill-session -t hermes-team
```

---

## 5. 窗口管理

### 新建窗口
快捷键：
- `Ctrl-b c`

### 关闭当前窗口
快捷键：
- `Ctrl-b &`

tmux 会要求确认。

### 重命名当前窗口
快捷键：
- `Ctrl-b ,`

### 在窗口之间编号切换
快捷键：
- `Ctrl-b 0~9`

---

## 6. 面板（pane）管理

你当前团队脚本默认是“每个窗口一个 pane”。
但如果以后你想在一个窗口内分屏，可以用这些命令。

### 左右分屏
- `Ctrl-b %`

### 上下分屏
- `Ctrl-b "`

### 在 pane 间切换
- `Ctrl-b o`

### 关闭当前 pane
- `Ctrl-b x`

### 显示 pane 编号
- `Ctrl-b q`

---

## 7. 复制 / 滚动查看历史输出

### 进入复制模式
- `Ctrl-b [`

进入后可用：
- 方向键上下移动
- `PageUp` / `PageDown` 翻页
- `q` 退出复制模式

这个很适合看 Hermes 之前输出过什么。

---

## 8. 针对你这个多代理团队的推荐工作流

### 启动团队
```bash
bash /Users/liuwenbin/agent-team/scripts/start-team.sh
```

### 进入团队
```bash
tmux attach -t hermes-team
```

### 常用切换方式
- `Ctrl-b 0` 看 ceo
- `Ctrl-b 1` 看 product
- `Ctrl-b 2` 看 engineer
- `Ctrl-b 3` 看 qa
- `Ctrl-b 4` 看 xiaohongshu
- `Ctrl-b 5` 看 wechat

### 暂时离开，但保持团队运行
- `Ctrl-b d`

### 结束全部 agent
```bash
tmux kill-session -t hermes-team
```

---

## 9. 推荐的最小记忆清单

你只要先记住这 6 个就够用：

```bash
# 启动团队
bash /Users/liuwenbin/agent-team/scripts/start-team.sh

# 进入团队
tmux attach -t hermes-team

# 看有哪些 session
tmux ls

# 暂时离开 tmux
# Ctrl-b d

# 切换窗口
# Ctrl-b 0~5

# 关闭整个团队
tmux kill-session -t hermes-team
```

---

## 10. 常见问题

### Q1：我退出终端了，team 还在吗？
一般还在。
只要没有执行：
```bash
tmux kill-session -t hermes-team
```
那么 tmux session 通常还会保留。

重新进入：
```bash
tmux attach -t hermes-team
```

### Q2：执行 start-team.sh 说 session 已存在？
说明之前已经启动过。
直接进入即可：
```bash
tmux attach -t hermes-team
```

### Q3：我只想关闭一个 agent 窗口？
先切到那个窗口，再：
- `Ctrl-b &`

但对你现在的团队来说，不建议随便关单个窗口。
更稳的是保留整套结构。

### Q4：怎么确认 team 真的在运行？
```bash
tmux ls
tmux list-windows -t hermes-team
```

---

## 11. 相关文件

- 团队启动脚本：
  - `/Users/liuwenbin/agent-team/scripts/start-team.sh`

- 团队根目录：
  - `/Users/liuwenbin/agent-team`

- 团队共享规则：
  - `/Users/liuwenbin/.hermes/AGENTS.md`

- 团队架构说明：
  - `/Users/liuwenbin/.hermes/team-agents.md`

---

## 12. 一句话总结

你的日常只要记住：
- 启动：`bash /Users/liuwenbin/agent-team/scripts/start-team.sh`
- 进入：`tmux attach -t hermes-team`
- 切换：`Ctrl-b` 后按 `0~5`
- 离开：`Ctrl-b d`
- 关闭：`tmux kill-session -t hermes-team`
