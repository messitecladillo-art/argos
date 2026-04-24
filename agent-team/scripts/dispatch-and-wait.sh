#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SEND_SCRIPT="$SCRIPT_DIR/send-to-agent.sh"
WAIT_SCRIPT="$SCRIPT_DIR/wait-all-agents.sh"
COLLECT_SCRIPT="$SCRIPT_DIR/collect-team-output.sh"

MODE="message"
CLEAR_FIRST=0
SEND_WAIT="0"
WAIT_TIMEOUT="120"
WAIT_INTERVAL="3"
LINES="60"

usage() {
  cat <<'EOF'
用法:
  dispatch-and-wait.sh [options] agent1="message1" [agent2="message2" ...]

说明:
  并行向多个 agent 派发消息，然后等待这些 agent 全部完成，最后收集整队输出。

选项:
  --raw               原样发送，不加团队前缀
  --clear             发送前对每个目标窗口执行 /clear
  --send-wait N       每次发送后等待 N 秒
  --timeout N         等待全部完成的超时时间，默认 120 秒
  --interval N        轮询间隔，默认 3 秒
  --lines N           最后收集输出时每个窗口显示 N 行，默认 60

示例:
  dispatch-and-wait.sh \
    product="请输出 MVP 定义，并在完成时明确写已完成" \
    engineer="请输出最小技术方案，并在完成时明确写已完成" \
    qa="请输出最小验收清单，并在完成时明确写已完成"
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
    --send-wait)
      SEND_WAIT="${2:-}"
      [[ -n "$SEND_WAIT" ]] || { echo "--send-wait 需要秒数参数"; exit 1; }
      shift 2
      ;;
    --timeout)
      WAIT_TIMEOUT="${2:-}"
      [[ -n "$WAIT_TIMEOUT" ]] || { echo "--timeout 需要秒数参数"; exit 1; }
      shift 2
      ;;
    --interval)
      WAIT_INTERVAL="${2:-}"
      [[ -n "$WAIT_INTERVAL" ]] || { echo "--interval 需要秒数参数"; exit 1; }
      shift 2
      ;;
    --lines)
      LINES="${2:-}"
      [[ -n "$LINES" ]] || { echo "--lines 需要数字参数"; exit 1; }
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

AGENTS=()
for pair in "$@"; do
  if [[ "$pair" != *=* ]]; then
    echo "参数格式错误：$pair"
    echo "正确格式：agent=\"message\""
    exit 1
  fi

  agent="${pair%%=*}"
  message="${pair#*=}"
  AGENTS+=("$agent")

  send_args=()
  if [[ "$MODE" == "raw" ]]; then
    send_args+=(--raw)
  fi
  if [[ "$CLEAR_FIRST" == "1" ]]; then
    send_args+=(--clear)
  fi
  if [[ "$SEND_WAIT" != "0" ]]; then
    send_args+=(--wait "$SEND_WAIT")
  fi

  echo "=== dispatch -> $agent ==="
  if [[ ${#send_args[@]} -gt 0 ]]; then
    "$SEND_SCRIPT" "${send_args[@]}" "$agent" "$message"
  else
    "$SEND_SCRIPT" "$agent" "$message"
  fi
  echo
done

echo "=== waiting for all target agents ==="
"$WAIT_SCRIPT" --timeout "$WAIT_TIMEOUT" --interval "$WAIT_INTERVAL" --lines "$LINES" "${AGENTS[@]}"
echo

echo "=== collect team output ==="
"$COLLECT_SCRIPT" --lines "$LINES"
