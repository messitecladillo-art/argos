#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SEND_SCRIPT="$SCRIPT_DIR/send-to-agent.sh"
READ_SCRIPT="$SCRIPT_DIR/read-agent-output.sh"

usage() {
  cat <<'EOF'
用法:
  ask-agent.sh <agent> <message>

说明:
  向指定 agent 发消息，等待几秒后自动抓取最近输出。

示例:
  ask-agent.sh product "请输出当前功能的 MVP 定义"
  ask-agent.sh engineer "请给出最小技术实现方案"
EOF
}

if [[ $# -lt 2 ]]; then
  usage
  exit 1
fi

AGENT="$1"
shift
MESSAGE="$*"

"$SEND_SCRIPT" "$AGENT" "$MESSAGE"
sleep 6
"$READ_SCRIPT" --lines 80 "$AGENT"
