#!/usr/bin/env bash
# ── macOS Code Signing & Notarization ──
# Signs the .app bundle and submits for notarization.
# Prerequisites:
#   - Apple Developer ID Application certificate in keychain
#   - App-specific password for notarization
# Env vars:
#   APPLE_DEVELOPER_ID  — Developer ID Application identity (e.g. "Developer ID Application: Name (TEAMID)")
#   APPLE_TEAM_ID       — Apple Team ID
#   APPLE_APP_SPECIFIC_PASSWORD — App-specific password for notarytool
#   APPLE_ID            — Apple ID email (for notarytool)
set -euo pipefail

APP_PATH="${1:?Usage: sign-mac.sh /path/to/S2 Report Sniffer.app}"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Error: $APP_PATH is not a valid .app bundle" >&2
  exit 1
fi

# ── Check required env vars ──
: "${APPLE_DEVELOPER_ID:?APPLE_DEVELOPER_ID not set}"
: "${APPLE_TEAM_ID:?APPLE_TEAM_ID not set}"

echo "▸ Signing frameworks and helpers..."
# Sign internal frameworks and helpers first (deep sign)
for helper in "$APP_PATH"/Contents/Frameworks/*.app; do
  [[ -d "$helper" ]] || continue
  echo "  Signing: $(basename "$helper")"
  codesign --force --options runtime --timestamp --sign "$APPLE_DEVELOPER_ID" "$helper"
done

# Sign the backend binary
BACKEND_BIN="$APP_PATH/Contents/Resources/backend/s2rs-backend"
if [[ -f "$BACKEND_BIN" ]]; then
  echo "  Signing: s2rs-backend"
  codesign --force --options runtime --timestamp --sign "$APPLE_DEVELOPER_ID" "$BACKEND_BIN"
fi

echo "▸ Signing main .app bundle..."
codesign --force --options runtime --timestamp --deep --sign "$APPLE_DEVELOPER_ID" \
  --entitlements "$(dirname "$0")/../desktop/assets/entitlements.mac.plist" \
  "$APP_PATH"

echo "  ✓ App signed"

# ── Notarization (optional — requires APPLE_ID + APPLE_APP_SPECIFIC_PASSWORD) ──
if [[ -n "${APPLE_ID:-}" && -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" ]]; then
  echo "▸ Creating notarization zip..."
  ZIP_PATH="${APP_PATH%.app}-notarize.zip"
  ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

  echo "▸ Submitting for notarization..."
  xcrun notarytool submit "$ZIP_PATH" \
    --apple-id "$APPLE_ID" \
    --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_SPECIFIC_PASSWORD" \
    --wait

  echo "▸ Stapling notarization ticket..."
  xcrun stapler staple "$APP_PATH"
  echo "  ✓ Notarization complete"

  rm -f "$ZIP_PATH"
else
  echo "  ⚠ Skipping notarization (APPLE_ID or APPLE_APP_SPECIFIC_PASSWORD not set)"
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  macOS Signing Complete                  ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Signed app: $APP_PATH"
