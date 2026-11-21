#!/usr/bin/env bash
# Stop the local V6 service started by tools/serve_detached.sh.
set -euo pipefail

PORT="${PORT:-8766}"
LOG_DIR="${LOG_DIR:-/tmp/opencode}"
PIDFILE="$LOG_DIR/german-v6-server.pid"
HEALTH="http://127.0.0.1:${PORT}/api/health"

if [[ ! -f "$PIDFILE" ]]; then
  if curl -fsS --max-time 2 "$HEALTH" >/dev/null 2>&1; then
    echo "no PID file, but something answers on ${PORT}; refusing to kill an unknown process" >&2
    echo "find it with: ss -ltnp 'sport = :${PORT}'" >&2
    exit 1
  fi
  echo "not running"
  exit 0
fi

PID="$(cat "$PIDFILE")"
if ! kill -0 "$PID" 2>/dev/null; then
  echo "pid ${PID} is gone; removing stale PID file"
  rm -f "$PIDFILE"
  exit 0
fi

kill "$PID"
for _ in $(seq 1 40); do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PIDFILE"
    echo "stopped pid ${PID}"
    exit 0
  fi
  sleep 0.25
done

echo "pid ${PID} did not exit; sending SIGKILL" >&2
kill -9 "$PID" 2>/dev/null || true
rm -f "$PIDFILE"
echo "killed pid ${PID}"
