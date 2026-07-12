#!/usr/bin/env bash
# Compatibility entry point for Apple Silicon DMG builds.
# The unified script owns all build logic and accepts PYTHON_BIN.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/build-desktop.sh" "$@"
