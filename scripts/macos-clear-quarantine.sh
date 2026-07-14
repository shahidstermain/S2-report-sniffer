#!/usr/bin/env bash
# Clear macOS Gatekeeper quarantine on the S2 Report Sniffer app after
# installing from an *unsigned* internal DMG. Run once after first install.
#
# Usage:
#   bash scripts/macos-clear-quarantine.sh
#   bash scripts/macos-clear-quarantine.sh "/Applications/S2 Report Sniffer.app"

set -euo pipefail

APP_PATH="${1:-/Applications/S2 Report Sniffer.app}"

if [[ ! -d "${APP_PATH}" ]]; then
  echo "App not found: ${APP_PATH}" >&2
  echo "Install from the DMG into Applications first, then re-run." >&2
  exit 1
fi

echo "Clearing quarantine attributes on: ${APP_PATH}"
xattr -cr "${APP_PATH}"
echo "Done. You can open S2 Report Sniffer from Applications now."
echo ""
echo "If macOS still blocks it: right-click the app → Open → Open."
