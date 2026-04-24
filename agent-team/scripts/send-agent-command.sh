#!/usr/bin/env bash
set -euo pipefail

SESSION="hermes-team"

usage() {
  cat <<'EOF'
用法:
  send-agent-command.sh <agent> <content>

说明:
  向指定 agent 的 tmux 窗口发送一条命令并回车。
EOF
}

if [[ $# -ne 2 ]]; then
  usage
  exit 1
fi

AGENT="$1"
CONTENT="$2"
TARGET="$SESSION:$AGENT"

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  echo '{"error":"SESSION_NOT_FOUND","session_name":"'"$SESSION"'"}'
  exit 2
fi

if ! tmux list-windows -t "$SESSION" -F '#W' | grep -Fxq "$AGENT"; then
  echo '{"error":"AGENT_NOT_FOUND","agent_name":"'"$AGENT"'"}'
  exit 3
fi

if [[ -z "$CONTENT" ]]; then
  echo '{"error":"EMPTY_CONTENT","agent_name":"'"$AGENT"'"}'
  exit 4
fi

tmux send-keys -t "$TARGET" -- "$CONTENT" Enter

echo '{"status":"sent","agent_name":"'"$AGENT"'"}'
