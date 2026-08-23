#!/usr/bin/env bash
# ── S2 Report Sniffer — Desktop Packaging Build Script ──
# Builds: frontend UI → backend PyInstaller executable → Electron installer
# Usage: ./scripts/build-desktop.sh [--signed] [--mac] [--win] [--linux]
#   --signed  Enable code signing (requires env vars: APPLE_DEVELOPER_ID, etc.)
#   --mac     Build macOS .dmg (default on macOS)
#   --win     Build Windows .exe installer (requires cross-compile env on macOS)
#   --linux   Build Linux .AppImage/.deb (requires cross-compile env on macOS)
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

ICON_ICNS="${DESKTOP_DIR}/assets/icon.icns"
if [[ ! -f "${ICON_ICNS}" ]]; then
  echo "✗ Missing desktop app icon: ${ICON_ICNS}" >&2
  echo "  Run: backend/.venv/bin/python scripts/generate_icon.py" >&2
  exit 1
fi

echo "  Python: $(${PYTHON_BIN} --version)"
echo "  npm:    $(npm --version)"
echo ""

# ── Step 1: Build Frontend UI ──
echo "▸ Step 1: Building frontend UI..."
cd "${FRONTEND_DIR}"
npm ci --silent
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
command rm -rf "$BUILD_WORK_DIR" "$BUILD_DIST_DIR" "$BUILD_CACHE_DIR"
mkdir -p "$BUILD_WORK_DIR" "$BUILD_DIST_DIR" "$BUILD_CACHE_DIR"

if [[ ! -d "$BUILD_VENV_DIR" ]]; then
    "$PYTHON_BIN" -m venv "$BUILD_VENV_DIR"
fi

if [[ -x "$BUILD_VENV_DIR/Scripts/python.exe" ]]; then
    BUILD_PYTHON="$BUILD_VENV_DIR/Scripts/python.exe"
else
    BUILD_PYTHON="$BUILD_VENV_DIR/bin/python"
fi

"$BUILD_PYTHON" -m pip install --quiet --upgrade pip
"$BUILD_PYTHON" -m pip install --quiet -r backend/requirements.txt
"$BUILD_PYTHON" -m pip install --quiet -r backend/requirements-build.txt

PYINSTALLER_CONFIG_DIR="$BUILD_CACHE_DIR" "$BUILD_PYTHON" -m PyInstaller --noconfirm --clean \
    --workpath "$BUILD_WORK_DIR" \
    --distpath "$BUILD_DIST_DIR" \
    backend/s2rs-backend.spec

BACKEND_FILENAME="s2rs-backend"
case "$PLATFORM" in
    MINGW*|MSYS*|CYGWIN*|Windows_NT) BACKEND_FILENAME="s2rs-backend.exe" ;;
esac

mkdir -p "${DIST_DIR}/backend"
cp "$BUILD_DIST_DIR/$BACKEND_FILENAME" "${DIST_DIR}/backend/$BACKEND_FILENAME"
chmod +x "${DIST_DIR}/backend/$BACKEND_FILENAME"
PYTHON_BIN="$PYTHON_BIN" bash "${SCRIPT_DIR}/smoke-test-backend.sh" "${DIST_DIR}/backend/$BACKEND_FILENAME"
echo "  ✓ Backend executable built ($(ls -lh "${DIST_DIR}/backend/$BACKEND_FILENAME" | awk '{print $5}'))"
echo ""

# ── Step 3: Build Electron Installer ──
if [[ "${S2RS_COMPONENTS_ONLY:-0}" == "1" ]]; then
  echo "  ✓ Desktop components ready; installer build delegated to caller"
  exit 0
fi

echo "▸ Step 3: Building Electron installer..."
cd "${DESKTOP_DIR}"
npm ci --silent

# Build for current platform (electron-builder + PyInstaller are OS-native).
# Default to unsigned build; use --signed to enable code signing via env vars.
if [[ "${1:-}" == "--signed" ]]; then
  case "${PLATFORM}" in
    Darwin) npm run dist:mac ;;
    Linux)  npm run dist:linux ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT) npm run dist:win ;;
    *) npm run dist ;;
  esac
else
  export CSC_IDENTITY_AUTO_DISCOVERY=false
  case "${PLATFORM}" in
    Darwin)
      # Host-arch unsigned DMG (arm64 on Apple Silicon runners, x64 on Intel).
      # identity="-" ad-hoc signs the whole .app with sealed resources. Leaving
      # signing skipped produces a linker-signed stub that macOS reports as
      # "S2 Report Sniffer is damaged and can't be opened."
      npx electron-builder --mac dmg --publish never \
        --config.mac.identity=- \
        --config.mac.notarize=false \
        --config.mac.hardenedRuntime=false
      APP_BUNDLE=$(/usr/bin/find "${DESKTOP_DIR}/dist" -maxdepth 2 -type d -name '*.app' | head -n 1 || true)
      if [[ -z "${APP_BUNDLE}" ]]; then
        echo "✗ No .app bundle found under desktop/dist after electron-builder" >&2
        exit 1
      fi
      if ! /usr/bin/codesign --verify --deep --strict "${APP_BUNDLE}"; then
        echo "✗ codesign verify failed for ${APP_BUNDLE}" >&2
        exit 1
      fi
      /usr/bin/xattr -cr "${APP_BUNDLE}" || true
      echo "  ✓ Ad-hoc signature verified: ${APP_BUNDLE}"
      ;;
    Linux)
      npx electron-builder --linux AppImage deb --publish never
      ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
      npx electron-builder --win msi --publish never --config.win.forceCodeSigning=false
      ;;
    *)
      echo "✗ Unsupported platform for installer packaging: ${PLATFORM}" >&2
      exit 1
      ;;
  esac
fi

# Stable path for CI / sharing
mkdir -p "${DIST_DIR}/installers"
/usr/bin/find "${DESKTOP_DIR}/dist" -maxdepth 2 -type f \( -name "*.dmg" -o -name "*.msi" -o -name "*.AppImage" -o -name "*.deb" -o -name "*.rpm" -o -name "*.exe" \) -print0 2>/dev/null \
  | while IFS= read -r -d '' f; do
      command cp -f "$f" "${DIST_DIR}/installers/"
    done

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  BUILD COMPLETE                          ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Installer artifacts:"
/usr/bin/find "${DESKTOP_DIR}/dist" -maxdepth 2 -type f \( -name "*.dmg" -o -name "*.msi" -o -name "*.AppImage" -o -name "*.deb" -o -name "*.rpm" -o -name "*.exe" \) 2>/dev/null | while read -r f; do
  echo "  → desktop/dist/$(basename "$f") ($(du -sh "$f" | cut -f1))"
done
/usr/bin/find "${DIST_DIR}/installers" -maxdepth 1 -type f 2>/dev/null | while read -r f; do
  echo "  → ${f#${REPO_ROOT}/} ($(du -sh "$f" | cut -f1))"
done
if command -v shasum >/dev/null 2>&1; then
  /usr/bin/find "${DIST_DIR}/installers" -maxdepth 1 -type f -print0 \
    | sort -z \
    | xargs -0 shasum -a 256 > "${DIST_DIR}/installers/SHA256SUMS"
elif command -v sha256sum >/dev/null 2>&1; then
  /usr/bin/find "${DIST_DIR}/installers" -maxdepth 1 -type f -print0 \
    | sort -z \
    | xargs -0 sha256sum > "${DIST_DIR}/installers/SHA256SUMS"
fi
echo ""
echo "Backend executable: ${DIST_DIR}/backend/"
echo "Frontend build:     ${FRONTEND_DIR}/build/"
echo ""
echo "To distribute: copy the installer from dist/installers/ (or desktop/dist/) to the target Mac."
