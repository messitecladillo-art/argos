#!/usr/bin/env bash
set -euo pipefail

SESSION="hermes-team"
MODE="message"
CLEAR_FIRST=0
WAIT_SECONDS=0

usage() {
  cat <<'EOF'
用法:
  send-to-agent.sh [--clear] [--wait seconds] <agent> <message>
  send-to-agent.sh --raw [--clear] [--wait seconds] <agent> <message>

说明:
  默认会在消息前加一段系统前缀，提醒目标 agent 这是团队内派发任务。
  --raw   不加前缀，原样发送。
  --clear 发送前先执行 /clear。
  --wait  发送后等待 N 秒，方便对方进入稳定状态。

示例:
  send-to-agent.sh engineer "请检查当前项目的启动脚本"
  send-to-agent.sh --clear qa "请输出最小验收清单"
  send-to-agent.sh --raw ceo "请只回复：PING-ceo"
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --raw)
      MODE="raw"
      shift
      ;;
    --clear)
      CLEAR_FIRST=1
      shift
      ;;
    --wait)
      WAIT_SECONDS="${2:-}"
      if [[ -z "$WAIT_SECONDS" ]]; then
        echo "--wait 需要一个秒数参数"
        exit 1
      fi
      shift 2
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

if [[ $# -lt 2 ]]; then
  usage
  exit 1
fi

AGENT="$1"
shift
MESSAGE="$*"
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

if [[ "$CLEAR_FIRST" == "1" ]]; then
  tmux send-keys -t "$TARGET" "/clear" C-m
  sleep 1
fi

if [[ "$MODE" == "raw" ]]; then
  FINAL_MESSAGE="$MESSAGE"
else
  FINAL_MESSAGE=$(cat <<EOF
[TEAM_MESSAGE]
From shell dispatcher
To $AGENT
请把以下内容视为团队内部任务或协作请求，并直接执行：
$MESSAGE
EOF
)
fi

tmux send-keys -t "$TARGET" "$FINAL_MESSAGE" C-m

if [[ "$WAIT_SECONDS" != "0" ]]; then
  sleep "$WAIT_SECONDS"
fi

echo "已发送到 $AGENT"
echo "模式: $MODE"
echo "消息: $MESSAGE"
