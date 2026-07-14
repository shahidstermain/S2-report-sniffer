#!/usr/bin/env bash
# ── Windows Authenticode Signing ──
# Signs the Windows installer (.exe/.msi) with an Authenticode certificate.
# Prerequisites:
#   - osslsigncode (brew install osslsigncode) or signtool (Windows SDK)
# Env vars:
#   WINDOWS_CERT_PATH     — Path to .pfx or .p12 certificate file
#   WINDOWS_CERT_PASSWORD — Certificate password
#   WINDOWS_TIMESTAMP_URL — Timestamp server URL (default: http://timestamp.digicert.com)
set -euo pipefail

INSTALLER_PATH="${1:?Usage: sign-win.sh /path/to/installer.exe}"

if [[ ! -f "$INSTALLER_PATH" ]]; then
  echo "Error: $INSTALLER_PATH not found" >&2
  exit 1
fi

: "${WINDOWS_CERT_PATH:?WINDOWS_CERT_PATH not set}"
: "${WINDOWS_CERT_PASSWORD:?WINDOWS_CERT_PASSWORD not set}"

TIMESTAMP_URL="${WINDOWS_TIMESTAMP_URL:-http://timestamp.digicert.com}"

OUTPUT_PATH="${INSTALLER_PATH%.*}-signed.${INSTALLER_PATH##*.}"

if command -v osslsigncode &>/dev/null; then
  echo "▸ Signing with osslsigncode..."
  osslsigncode sign \
    -pkcs12 "$WINDOWS_CERT_PATH" \
    -pass "$WINDOWS_CERT_PASSWORD" \
    -t "$TIMESTAMP_URL" \
    -h sha256 \
    -in "$INSTALLER_PATH" \
    -out "$OUTPUT_PATH"
  echo "  ✓ Signed: $OUTPUT_PATH"
elif command -v signtool &>/dev/null; then
  echo "▸ Signing with signtool..."
  signtool sign \
    /f "$WINDOWS_CERT_PATH" \
    /p "$WINDOWS_CERT_PASSWORD" \
    /tr "$TIMESTAMP_URL" \
    /td sha256 \
    /fd sha256 \
    "$INSTALLER_PATH"
  echo "  ✓ Signed: $INSTALLER_PATH"
else
  echo "Error: Neither osslsigncode nor signtool found." >&2
  echo "Install osslsigncode: brew install osslsigncode" >&2
  echo "Or install Windows SDK for signtool." >&2
  exit 1
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Windows Signing Complete               ║"
echo "╚══════════════════════════════════════════╝"
