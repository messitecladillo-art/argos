#!/usr/bin/env bash
set -euo pipefail

SESSION="hermes-team"
TEAM_ROOT="/Users/liuwenbin/agent-team"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HELPER="$SCRIPT_DIR/send-to-agent.sh"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session '$SESSION' already exists. Attach with: tmux attach -t $SESSION"
  exit 0
fi

tmux new-session -d -s "$SESSION" -n ceo "cd '$TEAM_ROOT' && hermes -p ceo"
tmux new-window -t "$SESSION" -n product "cd '$TEAM_ROOT' && hermes -p product"
tmux new-window -t "$SESSION" -n engineer "cd '$TEAM_ROOT' && hermes -p engineer"
tmux new-window -t "$SESSION" -n qa "cd '$TEAM_ROOT' && hermes -p qa"
tmux new-window -t "$SESSION" -n xiaohongshu "cd '$TEAM_ROOT' && hermes -p xiaohongshu"
tmux new-window -t "$SESSION" -n wechat "cd '$TEAM_ROOT' && hermes -p wechat"

echo "Started tmux session: $SESSION"
echo "Windows: ceo, product, engineer, qa, xiaohongshu, wechat"
echo "Attach with: tmux attach -t $SESSION"
echo
echo "Quick tips:"
echo "- Detach without stopping agents: Ctrl-b d"
echo "- Switch windows: Ctrl-b 0~5"
echo "- List windows: tmux list-windows -t $SESSION"
echo "- Send a task from shell: $HELPER engineer '请检查当前项目的风险'"
echo "- Full tmux doc: $TEAM_ROOT/tmux-usage.md"
