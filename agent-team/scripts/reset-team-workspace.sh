#!/usr/bin/env bash
set -euo pipefail

SESSION="hermes-team"
TEAM_ROOT="/Users/liuwenbin/agent-team"
SHARED_DIR="$TEAM_ROOT/shared"

keep_file() {
  local path="$1"
  case "$path" in
    "$SHARED_DIR/context/operating-rules.md") return 0 ;;
    "$SHARED_DIR/context/current-priorities.md") return 0 ;;
    "$SHARED_DIR/reports/daily-template.md") return 0 ;;
    "$SHARED_DIR/decisions/decision-log.md") return 0 ;;
    *) return 1 ;;
  esac
}

echo "[1/3] Stopping tmux session if it exists..."
if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux kill-session -t "$SESSION"
  echo "Stopped tmux session: $SESSION"
else
  echo "tmux session '$SESSION' not running, skipped."
fi

echo
echo "[2/3] Cleaning shared workspace..."
removed_count=0

while IFS= read -r path; do
  [[ -z "$path" ]] && continue

  if keep_file "$path"; then
    echo "KEEP  $path"
    continue
  fi

  rm -f "$path"
  echo "REMOVE $path"
  removed_count=$((removed_count + 1))
done < <(find "$SHARED_DIR" -type f | sort)

echo
echo "[3/3] Ensuring core directories exist..."
mkdir -p \
  "$SHARED_DIR/context" \
  "$SHARED_DIR/decisions" \
  "$SHARED_DIR/inbox" \
  "$SHARED_DIR/outbox" \
  "$SHARED_DIR/reports"

echo ""
echo "Cleanup complete."
echo "Removed files: $removed_count"
echo "Preserved core files:"
echo "- $SHARED_DIR/context/operating-rules.md"
echo "- $SHARED_DIR/context/current-priorities.md"
echo "- $SHARED_DIR/reports/daily-template.md"
echo "- $SHARED_DIR/decisions/decision-log.md"
echo ""
echo "You can restart the team with:"
echo "bash /Users/liuwenbin/agent-team/scripts/start-team.sh"
