#!/usr/bin/env bash
# Build an Apple Silicon (arm64) macOS DMG for S2 Report Sniffer.
# Usage: bash scripts/build-macos-arm64-dmg.sh
# Requirements: macOS arm64, Node.js, Python 3, npm
# No code signing or notarization is performed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> Repository root: ${REPO_ROOT}"

# ── 1. Frontend ─────────────────────────────────────────────────────────────

echo ""
echo "==> [1/3] Building frontend..."
cd "${REPO_ROOT}/frontend"
npm ci
npm run build
echo "    Frontend build complete: ${REPO_ROOT}/frontend/build"

# ── 2. Backend (PyInstaller single-file executable) ─────────────────────────

echo ""
echo "==> [2/3] Building backend executable with PyInstaller..."
cd "${REPO_ROOT}"

python3 -m venv .venv
# shellcheck source=/dev/null
source .venv/bin/activate

pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt
pip install --quiet pyinstaller

pyinstaller \
    --name s2rs-backend \
    --onefile \
    --paths backend \
    --noconfirm --clean \
    backend/desktop_entry.py

mkdir -p dist/backend
cp dist/s2rs-backend dist/backend/s2rs-backend
chmod +x dist/backend/s2rs-backend
echo "    Backend executable: ${REPO_ROOT}/dist/backend/s2rs-backend"

deactivate

# ── 3. Desktop DMG (Electron Builder) ───────────────────────────────────────

echo ""
echo "==> [3/3] Building macOS arm64 DMG..."
cd "${REPO_ROOT}/desktop"
npm ci
npm run dist

echo ""
echo "==> Build complete!"
echo "    DMG output directory: ${REPO_ROOT}/desktop/dist"
ls -lh "${REPO_ROOT}/desktop/dist/"*.dmg 2>/dev/null || ls -lh "${REPO_ROOT}/desktop/dist/"
