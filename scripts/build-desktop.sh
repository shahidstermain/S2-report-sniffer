#!/usr/bin/env bash
set -euo pipefail

# ── S2 Report Sniffer — Desktop Packaging Build Script ──
# Builds: frontend UI → backend PyInstaller executable → Electron installer
# Usage: ./scripts/build-desktop.sh [--signed]
# Prerequisites: Python 3.9+ venv, Node.js 16+, npm

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
FRONTEND_DIR="${REPO_ROOT}/frontend"
BACKEND_DIR="${REPO_ROOT}/backend"
DESKTOP_DIR="${REPO_ROOT}/desktop"
DIST_DIR="${REPO_ROOT}/dist"

echo "╔══════════════════════════════════════════╗"
echo "║  S2 Report Sniffer — Desktop Packager    ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Platform: $(uname -s) $(uname -m)"
echo "Repo:     ${REPO_ROOT}"
echo ""

# ── Step 0: Check prerequisites ──
echo "▸ Step 0: Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
  echo "✗ Python 3 not found. Install Python 3.9+ first."
  exit 1
fi

if ! command -v npm &>/dev/null; then
  echo "✗ npm not found. Install Node.js 16+ first."
  exit 1
fi

echo "  Python: $(python3 --version)"
echo "  npm:    $(npm --version)"
echo ""

# ── Step 1: Build Frontend UI ──
echo "▸ Step 1: Building frontend UI..."
cd "${FRONTEND_DIR}"
npm install --silent
npm run build
if [ ! -d "build" ]; then
  echo "✗ Frontend build failed — no build/ directory"
  exit 1
fi
echo "  ✓ Frontend built ($(du -sh build | cut -f1))"
echo ""

# ── Step 2: Build Backend Executable (PyInstaller) ──
echo "▸ Step 2: Building backend executable..."
cd "${REPO_ROOT}"

# Ensure venv exists
if [ ! -d "${VENV_DIR}" ]; then
  echo "  Creating venv..."
  python3 -m venv "${VENV_DIR}"
fi

# Activate venv
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# Install backend deps + pyinstaller
echo "  Installing dependencies..."
pip install --quiet fastapi uvicorn pydantic aiofiles python-multipart httpx 2>/dev/null || true
pip install --quiet pyinstaller 2>/dev/null || true

# Build with PyInstaller
echo "  Running PyInstaller..."
cd "${BACKEND_DIR}"
pyinstaller --noconfirm --clean \
  --name s2rs-backend \
  --onefile \
  --paths .. \
  ../s2rs-backend.spec

# Copy to dist/backend
mkdir -p "${DIST_DIR}/backend"
cp dist/s2rs-backend* "${DIST_DIR}/backend/" 2>/dev/null || \
  cp dist/s2rs-backend "${DIST_DIR}/backend/" 2>/dev/null || true

if [ -f "${DIST_DIR}/backend/s2rs-backend" ] || [ -f "${DIST_DIR}/backend/s2rs-backend.exe" ]; then
  echo "  ✓ Backend executable built"
else
  echo "✗ Backend build failed"
  exit 1
fi
echo ""

# ── Step 3: Build Electron Installer ──
echo "▸ Step 3: Building Electron installer..."
cd "${DESKTOP_DIR}"
npm install --silent

# Build for current platform
npm run dist

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  BUILD COMPLETE                          ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Installer artifacts:"
find "${DESKTOP_DIR}/dist" -maxdepth 2 -type f \( -name "*.dmg" -o -name "*.msi" -o -name "*.AppImage" -o -name "*.deb" -o -name "*.rpm" -o -name "*.exe" \) 2>/dev/null | while read -r f; do
  echo "  → $(basename "$f") ($(du -sh "$f" | cut -f1))"
done
echo ""
echo "Backend executable: ${DIST_DIR}/backend/"
echo "Frontend build:     ${FRONTEND_DIR}/build/"
echo ""
echo "To distribute: copy the installer file from desktop/dist/ to the target machine."