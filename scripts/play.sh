#!/usr/bin/env bash
# Start the localhost Claude playground in one command.
#
#   scripts/play.sh                 database up, build if needed, serve on :8080 (foreground)
#   scripts/play.sh --background    the same, detached; prints the URL and returns
#   scripts/play.sh --stop          stop a background server started by this script
#   scripts/play.sh --port 8090     another port
#
# Works on Linux, macOS, WSL and in a Claude Code cloud session. On native
# Windows use:  powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 play
#
# Steps, each skipped when already done:
#   1. PostgreSQL up            (scripts/db_up.sh: docker compose or a native cluster)
#   2. pipeline built           (`make build` the first time: a few minutes)
#   3. serve the walkthrough with the playground on http://localhost:<port>/play
#      bound to 127.0.0.1 -- the playground refuses any other address.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-python3}"
PORT="${WEB_PORT:-8080}"
BACKGROUND=0
STATE_DIR="${PLAY_STATE_DIR:-.play}"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

while [ $# -gt 0 ]; do
  case "$1" in
    --background|-b) BACKGROUND=1 ;;
    --port) PORT="$2"; shift ;;
    --stop)
      if [ -f "$STATE_DIR/server.pid" ] && kill "$(cat "$STATE_DIR/server.pid")" 2>/dev/null; then
        echo "play | stopped"; else echo "play | nothing to stop"; fi
      rm -f "$STATE_DIR/server.pid"; exit 0 ;;
    -h|--help) sed -n 2,17p "$0"; exit 0 ;;
    *) echo "play | unknown option $1"; exit 2 ;;
  esac
  shift
done

log() { echo "play | $*"; }

# 1. database
if ! "$PY" -c "from src import config, db; db.connect().close()" >/dev/null 2>&1; then
  log "starting PostgreSQL"
  scripts/db_up.sh
fi

# 2. pipeline (the playground reads core, ai, sec and the semantic pack)
built() {
  "$PY" - <<'PYEOF' >/dev/null 2>&1
from src import config, db
with db.connect() as conn:
    assert db.fetch_value(conn, "SELECT count(*) FROM core.dim_client") > 0
    assert db.fetch_value(conn, "SELECT count(*) FROM pg_policies") > 0
assert (config.PROJECT_ROOT / "semantic" / "context_pack.md").exists()
assert config.REFERENCE_RESULTS_JSON.exists()
PYEOF
}
if ! built; then
  log "the pipeline is not built in this database yet -> make build (a few minutes, once)"
  make build
fi

# 3. the model: the playground works without one (guard lab, personas), but say so
if command -v claude >/dev/null 2>&1; then
  log "model -> $(claude --version 2>/dev/null | head -1) (the Claude Code CLI on this machine)"
else
  log "WARNING: no 'claude' CLI on PATH -> Ask and Test cannot reach a model."
  log "         Install Claude Code and log in once, or set LLM_PROVIDER=anthropic_api with LLM_API_KEY."
fi

URL="http://localhost:${PORT}/play"
if [ "$BACKGROUND" = 1 ]; then
  mkdir -p "$STATE_DIR"
  if [ -f "$STATE_DIR/server.pid" ] && kill -0 "$(cat "$STATE_DIR/server.pid")" 2>/dev/null; then
    log "already running -> $URL"; exit 0
  fi
  nohup "$PY" -m src.webapp --playground --host 127.0.0.1 --port "$PORT" > "$STATE_DIR/server.log" 2>&1 &
  echo $! > "$STATE_DIR/server.pid"
  for _ in $(seq 1 40); do
    if "$PY" -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:${PORT}/api/play/health', timeout=2)" 2>/dev/null; then
      log "running in the background -> $URL"
      log "log: $STATE_DIR/server.log · stop: scripts/play.sh --stop"
      exit 0
    fi
    sleep 0.5
  done
  log "ERROR: the server did not answer; see $STATE_DIR/server.log"; tail -20 "$STATE_DIR/server.log"; exit 1
fi

log "serving -> $URL  (Ctrl+C to stop)"
exec "$PY" -m src.webapp --playground --host 127.0.0.1 --port "$PORT"
