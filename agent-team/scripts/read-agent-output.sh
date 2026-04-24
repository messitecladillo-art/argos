#!/usr/bin/env bash
set -euo pipefail

SESSION="hermes-team"
LINES="50"
WAIT_SECONDS="0"
FOLLOW=0

usage() {
  cat <<'EOF'
用法:
  read-agent-output.sh [--lines N] [--wait seconds] <agent>
  read-agent-output.sh --follow <agent>

说明:
  读取指定 agent 窗口最近输出。
  --lines N   显示最后 N 行，默认 50
  --wait N    先等待 N 秒再读取
  --follow    持续每 2 秒刷新一次

示例:
  read-agent-output.sh product
  read-agent-output.sh --lines 120 engineer
  read-agent-output.sh --wait 5 qa
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lines)
      LINES="${2:-}"
      if [[ -z "$LINES" ]]; then
        echo "--lines 需要数字参数"
        exit 1
      fi
      shift 2
      ;;
    --wait)
      WAIT_SECONDS="${2:-}"
      if [[ -z "$WAIT_SECONDS" ]]; then
        echo "--wait 需要秒数参数"
        exit 1
      fi
      shift 2
      ;;
    --follow)
      FOLLOW=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

AGENT="$1"
TARGET="$SESSION:$AGENT"

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session '$SESSION' 不存在。请先启动团队："
  echo "  bash /Users/liuwenbin/agent-team/scripts/start-team.sh"
  exit 1
fi

if ! tmux list-windows -t "$SESSION" -F '#W' | grep -Fxq "$AGENT"; then
  echo "未找到 agent 窗口: $AGENT"
  echo "可用窗口："
  tmux list-windows -t "$SESSION" -F '  - #W'
  exit 1
fi

render_once() {
  clear 2>/dev/null || true
  echo "=== $AGENT (last $LINES lines) ==="
  tmux capture-pane -p -t "$TARGET" | tail -n "$LINES"
}

if [[ "$WAIT_SECONDS" != "0" ]]; then
  sleep "$WAIT_SECONDS"
fi

if [[ "$FOLLOW" == "1" ]]; then
  while true; do
    render_once
    sleep 2
  done
else
  render_once
fi
