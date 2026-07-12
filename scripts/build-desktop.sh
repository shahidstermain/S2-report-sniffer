#!/usr/bin/env bash
# ── S2 Report Sniffer — Desktop Packaging Build Script ──
# Builds: frontend UI → backend PyInstaller executable → Electron installer
# Usage: ./scripts/build-desktop.sh [--signed]
# Prerequisites: Python 3.9+ venv, Node.js 16+, npm

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -n "${PYTHON_BIN:-}" ]]; then
    PYTHON_BIN="$PYTHON_BIN"
else
    PYTHON_BIN=""
    for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
            PYTHON_BIN="$candidate"
            break
        fi
    done
    if [[ -z "$PYTHON_BIN" ]]; then
        echo "No Python 3.11+ interpreter found. Set PYTHON_BIN to a compatible interpreter." >&2
        exit 1
    fi
fi

VENV_DIR="${REPO_ROOT}/.venv"
FRONTEND_DIR="${REPO_ROOT}/frontend"
BACKEND_DIR="${REPO_ROOT}/backend"
DESKTOP_DIR="${REPO_ROOT}/desktop"
DIST_DIR="${REPO_ROOT}/dist"
PLATFORM="$(uname -s)"

echo "╔══════════════════════════════════════════╗"
echo "║  S2 Report Sniffer — Desktop Packager    ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Platform: $(uname -s) $(uname -m)"
echo "Python:   $PYTHON_BIN"
echo "Repo:     ${REPO_ROOT}"
echo ""

# ── Step 0: Check prerequisites ──
echo "▸ Step 0: Checking prerequisites..."

if [[ "${1:-}" == "--check" ]]; then
    echo ""
    echo "==> Pre-flight check only"
    PYTHON_BIN="$PYTHON_BIN" INTERACTIVE_MODE=false bash "${SCRIPT_DIR}/pre_install_check.sh" || exit 1
    echo "    All dependencies OK."
    exit 0
fi

if ! command -v npm &>/dev/null; then
  echo "✗ npm not found. Install Node.js 16+ first."
  exit 1
fi

echo "  Python: $(${PYTHON_BIN} --version)"
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

# Keep release dependencies and PyInstaller state separate from developer/Hermes venvs.
BUILD_VENV_DIR="${BUILD_VENV_DIR:-${REPO_ROOT}/.build-venv}"
BUILD_WORK_DIR="${REPO_ROOT}/.build/pyinstaller-work"
BUILD_DIST_DIR="${REPO_ROOT}/.build/pyinstaller-dist"
BUILD_CACHE_DIR="${REPO_ROOT}/.build/pyinstaller-cache"
rm -rf "$BUILD_WORK_DIR" "$BUILD_DIST_DIR" "$BUILD_CACHE_DIR"
mkdir -p "$BUILD_WORK_DIR" "$BUILD_DIST_DIR" "$BUILD_CACHE_DIR"

if [[ ! -d "$BUILD_VENV_DIR" ]]; then
    "$PYTHON_BIN" -m venv "$BUILD_VENV_DIR"
fi
# shellcheck source=/dev/null
source "$BUILD_VENV_DIR/bin/activate"

python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r backend/requirements.txt
python -m pip install --quiet pyinstaller

PYINSTALLER_CONFIG_DIR="$BUILD_CACHE_DIR" pyinstaller --noconfirm --clean \
    --workpath "$BUILD_WORK_DIR" \
    --distpath "$BUILD_DIST_DIR" \
    backend/s2rs-backend.spec

mkdir -p "${DIST_DIR}/backend"
cp "$BUILD_DIST_DIR/s2rs-backend" "${DIST_DIR}/backend/s2rs-backend"
chmod +x "${DIST_DIR}/backend/s2rs-backend"
bash "${SCRIPT_DIR}/smoke-test-backend.sh" "${DIST_DIR}/backend/s2rs-backend"
echo "  ✓ Backend executable built ($(ls -lh "${DIST_DIR}/backend/s2rs-backend" | awk '{print $5}'))"
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
