#!/usr/bin/env bash
# S2 Report Sniffer — Portable Mode Launcher (macOS/Linux)
# Usage: ./run-s2-report-sniffer.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_BIN="${SCRIPT_DIR}/backend/s2rs-backend"
UI_DIR="${SCRIPT_DIR}/ui"
PORT="${S2RS_PORT:-8000}"

# Find a free port if default is taken
if command -v lsof &>/dev/null; then
  while lsof -ti ":${PORT}" &>/dev/null; do
    PORT=$((PORT + 1))
  done
fi

echo "S2 Report Sniffer — Portable Mode"
echo "  Backend: ${BACKEND_BIN}"
echo "  UI:      ${UI_DIR}"
echo "  Port:    ${PORT}"
echo ""

if [ ! -f "${BACKEND_BIN}" ]; then
  echo "ERROR: Backend binary not found at ${BACKEND_BIN}"
  echo "       Expected in portable folder structure: ./backend/s2rs-backend + ./ui/"
  exit 1
fi

chmod +x "${BACKEND_BIN}" 2>/dev/null || true

export S2RS_HOST=127.0.0.1
export S2RS_PORT="${PORT}"
export S2RS_UI_DIR="${UI_DIR}"
export S2RS_ENVIRONMENT=production

echo "Starting backend on 127.0.0.1:${PORT}..."
echo "Open http://127.0.0.1:${PORT}/ui/ in your browser."
echo "Press Ctrl+C to stop."
echo ""

exec "${BACKEND_BIN}"