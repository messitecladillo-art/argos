#!/usr/bin/env bash
set -euo pipefail

SESSION="hermes-team"
LINES="50"
POLL_INTERVAL="3"
TIMEOUT_SECONDS="120"
DONE_PATTERN='(^|[^A-Z])(DONE|已完成|完成了|处理完成|任务完成|已回复|输出如下|结论如下)'
BLOCK_PATTERN='(阻塞|卡住|无法继续|需要补充|缺少信息|等待中|blocked|BLOCKED)'
RUNNING_PATTERN='(Initializing agent|processing|brainstorming|type a message \+ Enter to interrupt|⚕ ❯)'

usage() {
  cat <<'EOF'
用法:
  wait-all-agents.sh [--lines N] [--interval seconds] [--timeout seconds] <agent1> [agent2 ...]

说明:
  轮询多个 agent 窗口，直到它们都出现“完成信号”或超时。
  完成信号默认匹配：DONE / 已完成 / 处理完成 / 任务完成 / 已回复 / 输出如下 / 结论如下
  阻塞信号默认匹配：阻塞 / 卡住 / 无法继续 / 需要补充 / 缺少信息 / 等待中 / blocked

示例:
  wait-all-agents.sh product engineer qa
  wait-all-agents.sh --timeout 300 --lines 80 product engineer qa
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lines)
      LINES="${2:-}"
      [[ -n "$LINES" ]] || { echo "--lines 需要数字参数"; exit 1; }
      shift 2
      ;;
    --interval)
      POLL_INTERVAL="${2:-}"
      [[ -n "$POLL_INTERVAL" ]] || { echo "--interval 需要秒数参数"; exit 1; }
      shift 2
      ;;
    --timeout)
      TIMEOUT_SECONDS="${2:-}"
      [[ -n "$TIMEOUT_SECONDS" ]] || { echo "--timeout 需要秒数参数"; exit 1; }
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

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

AGENTS=("$@")

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session '$SESSION' 不存在。请先启动团队："
  echo "  bash /Users/liuwenbin/agent-team/scripts/start-team.sh"
  exit 1
fi

for agent in "${AGENTS[@]}"; do
  if ! tmux list-windows -t "$SESSION" -F '#W' | grep -Fxq "$agent"; then
    echo "未找到 agent 窗口: $agent"
    exit 1
  fi
done

START_TS=$(date +%s)
ALL_DONE=0

status_file() {
  local agent="$1"
  echo "/tmp/hermes-wait-status-${agent}.txt"
}

set_status() {
  local agent="$1"
  local status="$2"
  printf '%s' "$status" > "$(status_file "$agent")"
}

get_status() {
  local agent="$1"
  local file
  file="$(status_file "$agent")"
  if [[ -f "$file" ]]; then
    cat "$file"
  else
    printf 'unknown'
  fi
}

check_agent() {
  local agent="$1"
  local text
  text=$(tmux capture-pane -p -t "$SESSION:$agent" | tail -n "$LINES")

  if printf '%s
' "$text" | grep -Eiq "$DONE_PATTERN"; then
    set_status "$agent" "done"
    return
  fi

  if printf '%s
' "$text" | grep -Eiq "$RUNNING_PATTERN"; then
    set_status "$agent" "running"
    return
  fi

  if printf '%s
' "$text" | grep -Eiq "$BLOCK_PATTERN"; then
    set_status "$agent" "blocked"
    return
  fi

  set_status "$agent" "waiting"
}

render_status() {
  local now elapsed all_done_local=1 agent current_status
  now=$(date +%s)
  elapsed=$((now - START_TS))
  echo "=== wait-all-agents status (${elapsed}s / timeout ${TIMEOUT_SECONDS}s) ==="
  for agent in "${AGENTS[@]}"; do
    check_agent "$agent"
    current_status="$(get_status "$agent")"
    printf '%-14s %s
' "$agent" "$current_status"
    if [[ "$current_status" != "done" ]]; then
      all_done_local=0
    fi
  done
  if [[ "$all_done_local" == "1" ]]; then
    ALL_DONE=1
  else
    ALL_DONE=0
  fi
}

while true; do
  render_status

  if [[ "$ALL_DONE" == "1" ]]; then
    echo
    echo "All target agents completed."
    echo
    for agent in "${AGENTS[@]}"; do
      echo "===== $agent (last $LINES lines) ====="
      tmux capture-pane -p -t "$SESSION:$agent" | tail -n "$LINES"
      echo
    done
    exit 0
  fi

  NOW_TS=$(date +%s)
  if (( NOW_TS - START_TS >= TIMEOUT_SECONDS )); then
    echo
    echo "Timeout reached before all agents completed."
    echo
    for agent in "${AGENTS[@]}"; do
      echo "===== $agent (last $LINES lines) ====="
      tmux capture-pane -p -t "$SESSION:$agent" | tail -n "$LINES"
      echo
    done
    exit 2
  fi

  sleep "$POLL_INTERVAL"
  echo
done
