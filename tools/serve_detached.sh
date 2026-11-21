#!/usr/bin/env bash
# Start the local V6 service, idempotently.
#
#   tools/serve_detached.sh
#
# If /api/health already answers, this prints it and exits 0 — it never starts a
# second server. Otherwise it starts one detached process on 127.0.0.1:8766,
# writes a PID file and waits for an honest health response.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8766}"
LOG_DIR="${LOG_DIR:-/tmp/opencode}"
LOG="$LOG_DIR/german-v6-server.log"
PIDFILE="$LOG_DIR/german-v6-server.pid"
HEALTH="http://127.0.0.1:${PORT}/api/health"

mkdir -p "$LOG_DIR"

if curl -fsS --max-time 2 "$HEALTH" >/dev/null 2>&1; then
  echo "already running on 127.0.0.1:${PORT}"
  curl -fsS --max-time 2 "$HEALTH"
  echo
  exit 0
fi

cd "$ROOT"
PYTHONPATH=src setsid nohup python3 -m v5 serve --host 127.0.0.1 --port "$PORT" \
  >>"$LOG" 2>&1 &
PID=$!
echo "$PID" >"$PIDFILE"

for _ in $(seq 1 60); do
  if curl -fsS --max-time 1 "$HEALTH" >/dev/null 2>&1; then
    echo "started pid ${PID} on 127.0.0.1:${PORT} (log: ${LOG})"
    curl -fsS --max-time 2 "$HEALTH"
    echo
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "server exited during startup; last log lines:" >&2
    tail -n 40 "$LOG" >&2 || true
    rm -f "$PIDFILE"
    exit 1
  fi
  sleep 0.25
done

echo "server did not answer ${HEALTH}; last log lines:" >&2
tail -n 40 "$LOG" >&2 || true
exit 1
