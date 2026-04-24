#!/usr/bin/env bash
set -euo pipefail

SESSION="hermes-team"
LINES="60"
WAIT_SECONDS="0"
AGENTS=(ceo product engineer qa xiaohongshu wechat)

usage() {
  cat <<'EOF'
用法:
  collect-team-output.sh [--lines N] [--wait seconds]

说明:
  一次抓取整个团队所有 agent 的最近输出。
  默认顺序：ceo, product, engineer, qa, xiaohongshu, wechat

示例:
  collect-team-output.sh
  collect-team-output.sh --lines 100
  collect-team-output.sh --wait 8 --lines 80
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
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 1
      ;;
  esac
done

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session '$SESSION' 不存在。请先启动团队："
  echo "  bash /Users/liuwenbin/agent-team/scripts/start-team.sh"
  exit 1
fi

if [[ "$WAIT_SECONDS" != "0" ]]; then
  sleep "$WAIT_SECONDS"
fi

for agent in "${AGENTS[@]}"; do
  if tmux list-windows -t "$SESSION" -F '#W' | grep -Fxq "$agent"; then
    echo "===== $agent (last $LINES lines) ====="
    tmux capture-pane -p -t "$SESSION:$agent" | tail -n "$LINES"
    echo
  else
    echo "===== $agent ====="
    echo "窗口不存在"
    echo
  fi
done
