#!/bin/bash
# SessionEnd hook → record the just-ended session (Phase 1 spine).
# Reentrancy guard: the engine's own `claude -p` calls set WIKI_ENGINE, so skip those.
[ -n "$WIKI_ENGINE" ] && exit 0

payload="$(cat)"
[ -z "$payload" ] && exit 0

ENGINE_DIR="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/wiki}"   # code (plugin); falls back to the data repo for dev
export WIKI_HOME="${WIKI_HOME:-$HOME/.claude/wiki}"      # data
mkdir -p "$WIKI_HOME/logs"

# Launch fully detached so session exit is never blocked (spike-verified to survive teardown).
nohup python3 "$ENGINE_DIR/bin/wiki" record --from-hook-json "$payload" \
  >>"$WIKI_HOME/logs/record.log" 2>&1 &
disown 2>/dev/null

exit 0
