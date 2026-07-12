#!/usr/bin/env bash
# Smoke-test a PyInstaller backend artifact before it is embedded in Electron.
set -euo pipefail

BINARY="${1:?Usage: smoke-test-backend.sh /path/to/s2rs-backend}"
if [[ ! -x "$BINARY" ]]; then
  echo "Backend artifact is not executable: $BINARY" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
PORT="$({ python3 - <<'PY'
import socket
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
} )"
LOG_FILE="$TMP_DIR/backend.log"
PID=""

cleanup() {
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

S2RS_HOST=127.0.0.1 S2RS_PORT="$PORT" S2RS_DATA_DIR="$TMP_DIR/data" S2RS_RUNTIME_DIR="$TMP_DIR/runtime" \
  "$BINARY" >"$LOG_FILE" 2>&1 &
PID=$!

for _ in $(seq 1 50); do
  if curl --fail --silent "http://127.0.0.1:$PORT/api/health" >/dev/null; then
    echo "Packaged backend smoke test passed on port $PORT."
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "Packaged backend exited before health check:" >&2
    cat "$LOG_FILE" >&2
    exit 1
  fi
  sleep 0.2
done

echo "Timed out waiting for packaged backend health endpoint:" >&2
cat "$LOG_FILE" >&2
exit 1
