<br />

<br />

<br />

# Distribution Strategy & Local Installation Guide (Offline / No Deployment)

This document explains how to package and share **S2 Report Sniffer** as a **locally-run** application (not intended for hosted deployment). It is written to help both:

- **Non-technical users** install and run the application safely on their own machines.
- **IT/Admins** package the application, publish it internally, and support users.

The application is designed to run entirely on the user’s machine:

- Frontend UI: React
- Backend API: FastAPI (local loopback only)
- Storage: local SQLite + files
- Supported report inputs: directory import and archives (`.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`)

## Quick Diagram (What Runs Where)

```text
User’s Computer (No Internet Required)

  [Desktop App (Electron)]
          |
          | launches
          v
  [Local Backend (FastAPI)]  ---->  Local storage (SQLite + JSON)
          |
          | serves
          v
  [UI in embedded browser]

  Network access: 127.0.0.1 only
```

## Distribution Options (Recommended Order)

1. **Offline Desktop Installer (Recommended)**
   - Best for: Non-technical users, air-gapped environments
   - Deliverable: MSI (Windows), DMG (macOS), AppImage/DEB/RPM (Linux)
2. **Portable Folder (No installer)**
   - Best for: USB transfer, locked-down devices where installers are blocked
   - Deliverable: a folder containing the backend executable + built UI + a “Run” script
3. **Developer Mode (Source checkout)**
   - Best for: engineers, QA
   - Deliverable: this repository (requires Python + Node)
4. **VS Code extension (launcher only)**
   - Best for: engineers who already use VS Code and want the UI in-editor or one-click external browser
   - Deliverable: a `.vsix` built from `vscode-extension/` (see that folder’s `README.md`); does not embed the backend—start FastAPI as usual

## System Requirements (End Users)

### Windows

- Windows 10/11 (x64)
- 8 GB RAM minimum (16 GB recommended for large reports)
- 2+ GB free disk space (more recommended to store reports)

### macOS

- macOS 13+ recommended
- Apple Silicon or Intel
- 8 GB RAM minimum

### Linux

- Ubuntu 22.04+ recommended (or comparable modern distro)
- 8 GB RAM minimum

### Report Size Guidance

- Large report archives can be multiple GB; leave sufficient disk space.

## External Dependencies (Local Only)

- No remote DB required.
- No cloud services are required. Optional cloud-enrichment integrations are disabled unless explicitly configured.
- Local storage is used:
  - SQLite file for metadata
  - JSON payload/log files per report

## Local Storage Location

- Default data directory:
  - `~/.s2-report-sniffer` (on most systems)
  - In repo/dev runs, the app can also use `./.local_data` depending on write permissions.
- Override:
  - `S2RS_DATA_DIR` (directory path)

Contents:

- `reports.sqlite` (metadata/index)
- `reports/<report_id>/report.json` (parsed report payload)
- `reports/<report_id>/logs.jsonl` (log lines)

## Installation Guide (Non-Technical Users)

### Option A — Install Desktop App (Recommended)

1. Get the installer from your internal source (USB share, company portal, etc.).
2. Install:
   - Windows: double-click the `.msi`
   - macOS: open the `.dmg` and drag the app to **Applications**
   - Linux:
     - AppImage: right click → Properties → allow execute → run
     - DEB/RPM: install via your package manager
3. Launch **S2 Report Sniffer** from Start Menu / Applications.

What to expect on first launch:

- The application starts a local backend on `127.0.0.1` (not exposed to the network).
- The UI opens automatically.
- Data is saved locally.

### Option B — Portable Folder (No Installer)

If your environment blocks installers, provide users a portable folder distribution:

1. Copy the folder onto the machine (USB drive is fine).
2. Run the launcher:
   - Windows: `Run-S2ReportSniffer.bat`
   - macOS/Linux: `./run-s2-report-sniffer.sh`
3. The UI opens in a window.

Portable mode still writes data to `S2RS_DATA_DIR` (defaults apply if unset).

## Configuration (Local Environments)

These settings are optional and mainly used by IT/admins or power users.

### Storage and Data

- `S2RS_DATA_DIR`: where local data is stored.
  - Example (Windows): `C:\Users\<you>\AppData\Local\S2RS`
  - Example (macOS/Linux): `/Users/<you>/.s2-report-sniffer`

### Desktop App / Backend Runtime

- `S2RS_HOST`: hostname binding for backend (desktop uses `127.0.0.1`)
- `S2RS_PORT`: port for backend (desktop picks a free port)
- `S2RS_UI_DIR`: path to the built UI folder (desktop points to bundled `ui/`)

### Running From Source (Developer Mode)

Backend:

```bash
cd backend
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Basic Usage (Import/Analyze)

Users can:

- Upload archives from the UI
- Import local paths (file or folder)

Supported file types:

- `.zip`
- `.tar.gz` / `.tgz`
- `.tar`
- `.gz` (expected to contain a tar archive)
- Directory import

## Verification Checklist (Confirm It Works)

Non-technical quick checks:

1. App opens and shows the Reports page.
2. Import a small report directory or archive.
3. Confirm it appears in the list and transitions from `processing` → `ready`.
4. Open a report dashboard and confirm:
   - Overview loads
   - Recommendations render
   - Deployment method is shown after analysis

Admin/IT checks:

- Backend health endpoint responds:
  - `http://127.0.0.1:<port>/api/health`

## Troubleshooting

### “Blank screen” / UI doesn’t load

- Close and reopen the app.
- If using portable mode, ensure you ran the launcher (not the backend executable directly).

### “Upload/import fails”

- Confirm the file type is supported.
- Confirm you have read permissions on the selected file/folder.
- For `.gz`, confirm it contains a tar archive.

### “Permission denied” / database readonly

- Ensure `S2RS_DATA_DIR` points to a directory the user can write to.
- On macOS/Linux, avoid system directories like `/System` or `/usr`.

### “Port already in use”

- If running from source, use a different port for the backend:
  - `uvicorn server:app --port 8001`

### “Stuck in processing”

- Large reports can take time; wait a few minutes.
- Try a smaller test report to confirm the pipeline works.

## Packaging and Sharing (IT/Admin Guide)

This section explains how to build and distribute the recommended offline desktop installer.

## Summary of the Desktop Packaging Model

- Desktop shell: Electron
- Backend: bundled executable (PyInstaller) running FastAPI on a local loopback port
- UI: bundled React build served locally at `/ui/` by the backend
- Storage: local offline-first store (SQLite index + file-based report payload and logs)

```text
Electron App
  └─ spawns backend executable on 127.0.0.1:<free_port>
        ├─ serves UI:  http://127.0.0.1:<port>/ui/
        └─ serves API: http://127.0.0.1:<port>/api/...
             └─ persists data to local storage dir
```

## Local Storage (No Cloud / No MongoDB)

- Default: `~/.s2-report-sniffer` (override via `S2RS_DATA_DIR`)
- Contents:
  - `reports.sqlite` (index/metadata)
  - `reports/<report_id>/report.json` (parsed report payload)
  - `reports/<report_id>/logs.jsonl` (log lines)

## Build Outputs

- Backend executable: `dist/backend/s2rs-backend(.exe)`
- UI build: `frontend/build/`
- Electron installers:
  - Windows: `MSI`
  - macOS: `DMG`
  - Linux: `AppImage`, `DEB`, `RPM`

## Building Installers (Cross-Platform)

Electron installer artifacts must be built on the target OS:

- Build Windows MSI on Windows
- Build macOS DMG on macOS
- Build Linux AppImage/DEB/RPM on Linux

### macOS DMG via GitHub Actions (recommended for sharing)

This repo cannot produce a Mac-native DMG from Linux. Use the CI workflow:

1. Open **Actions → desktop-macos-dmg → Run workflow** (or push a change under `desktop/**` / `scripts/build-desktop.sh` to `main`).
2. Wait for **Build unsigned macOS DMG** on `macos-latest`.
3. Download the artifact **`S2ReportSniffer-macos-unsigned-dmg`** (contains the `.dmg`).
4. Share the `.dmg` (USB / internal portal). On the Mac: open it and drag **S2 Report Sniffer** to **Applications**.

Unsigned builds: Gatekeeper may show “unidentified developer”. Users can right-click → Open, or run `xattr -dr com.apple.quarantine "/Applications/S2 Report Sniffer.app"` after install. Signed/notarized DMGs require Apple Developer ID secrets (`CSC_LINK`, `APPLE_TEAM_ID`) and `scripts/build-desktop.sh --signed`.

Local Mac build (Apple Silicon or Intel):

```bash
PYTHON_BIN="$(command -v python3.11 || command -v python3)"
bash scripts/build-desktop.sh
# → dist/installers/*.dmg  and  desktop/dist/*.dmg
```

### Step 1: Build the Frontend UI

```bash
cd frontend
npm install
npm run build
```

### Step 2: Build the Backend Executable

The backend is packaged as a standalone executable using PyInstaller. The entrypoint is:

- `backend/desktop_entry.py`

Required (developer workstation):

```bash
PYTHON_BIN="$(command -v python3.11 || command -v python3)"
"$PYTHON_BIN" -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
pip install pyinstaller
```

Build:

```bash
PYTHON_BIN="$PYTHON_BIN" bash scripts/build-desktop.sh
```

### Icon regeneration (Radiant Signal)

App icons are committed under `desktop/assets/` (`icon.icns`, `icon.ico`, `icon.png`). The desktop artwork is the same database/sniffer logo used by the README at `docs/assets/logo.svg`; `scripts/icon_render.py` mirrors that geometry for deterministic cross-platform raster output. Regenerate after editing either source. The compact web favicon source remains `docs/s2rs-icon-compact.svg`.

```bash
# Requires Pillow (backend venv) and macOS sips/iconutil for .icns
backend/.venv/bin/python scripts/generate_icon.py
backend/.venv/bin/python scripts/generate_favicon.py
```

Web favicons land in `frontend/public/assets/favicon.{ico,svg}`. Rebuild the frontend (`npm run build`) so they appear under `/ui/assets/` in integrated deployments.

### Step 3: Build the Desktop Installer

```bash
cd desktop
npm install
npm run dist
```

The Electron config bundles:

- `../frontend/build` -> app resource `ui/`
- `../dist/backend`  -> app resource `backend/`

The unified script validates the packaged backend's `/api/health` endpoint before it invokes Electron Builder.

## Offline Update Mechanism

The packaged app supports an offline update workflow:

1. Download a newer installer package (MSI/DMG/AppImage/DEB/RPM) via any method.
2. Copy it to the target machine.
3. Open the app and use: `File -> Install Update Package`
4. The OS installer handles the update and keeps user data in `S2RS_DATA_DIR`.

## Signed Online Update Channel

Packaged users can explicitly enable **Desktop updates** on the report-list screen. When enabled, the app checks the configured GitHub Releases feed at startup; report contents and local diagnostics are never sent. `S2RS_DISABLE_AUTO_UPDATE=1` force-disables all automatic checks for air-gapped deployments. The legacy `S2RS_ENABLE_AUTO_UPDATE=1` override remains available for managed installs.

Releases are built by `.github/workflows/desktop-release.yml` when a `v*` tag matching `desktop/package.json` is pushed. Configure these repository secrets before tagging:

- macOS: `CSC_LINK`, `CSC_KEY_PASSWORD`, `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`
- Windows: `WINDOWS_CERTIFICATE_BASE64`, `WINDOWS_CERT_PASSWORD`, `WINDOWS_PUBLISHER_NAME`

The workflow intentionally fails if signing credentials are absent. It publishes installers, blockmaps, and `latest*.yml` metadata to a draft GitHub Release; publish that draft only after validating every platform artifact. End-user update checks require the release assets to be anonymously readable. For a private source repository, use a separate public release repository/provider rather than embedding a GitHub token in the desktop app.

This project uses the public `shahidstermain/S2-report-sniffer-releases` repository for binaries and update metadata. Configure `RELEASE_GH_TOKEN` in the private source repository as a fine-grained token with Contents write access to that release repository only.

Current Apple Silicon v1.1.0 release:

- Release: <https://github.com/shahidstermain/S2-report-sniffer-releases/releases/tag/v1.1.0>
- Installer: `S2-Report-Sniffer-1.1.0-arm64.dmg`
- SHA-256: `cbe4c26ee33bc7d09ca89aacc05ad862c77460b6637ca8d57596f32a10f73e60`
- Source commit: `dcb69a1a651c726373ad2308f5c6ac7e9d4d9b47`

This refreshed package includes the Disk Intelligence persistence and saved-report hydration fix. It remains ad-hoc signed rather than Apple Developer ID notarized; verify the checksum before internal distribution.

Release sequence:

1. Bump `desktop/package.json` to the intended semantic version.
2. Commit the release change, create the matching tag (for example `v1.0.3`), and push the tag.
3. Validate signatures/notarization and the generated update manifests in the draft release.
4. Publish the draft release, then test from a machine running the preceding signed version.

## Digital Signing

Signing requires platform-specific certificates and must be performed during the build:

- Windows: Authenticode code signing (signtool)
- macOS: Developer ID + notarization
- Linux: package signing (GPG) for repo-delivered DEB/RPM, or detached signatures for AppImage

Electron Builder supports signing configuration via environment variables and per-platform build settings.

## Air-Gapped Validation Checklist

On a machine with no internet access:

1. Install the package.
2. Launch the app.
3. Upload a report archive and verify:
   - report list updates
   - dashboards render
   - recommendations compute
   - logs query endpoint works
4. Confirm data persists across restarts:
   - close app
   - re-open and confirm reports are present
5. Validate no remote dependencies:
   - disable network adapters
   - verify app still starts and functions

## Known Constraints

- Windows/macOS/Linux artifacts require native builds on each OS.
- For full professional signing/notarization, certificates and CI secrets must be supplied by the organization.

## Suggested Internal Distribution Process

1. Build installers per OS and place in a versioned folder:
   - `S2RS-<version>-windows.msi`
   - `S2RS-<version>-macos.dmg`
   - `S2RS-<version>-linux.AppImage`
2. Publish checksums:
   - `sha256sum` per artifact
3. Publish release notes:
   - what changed
   - known issues
4. Provide a rollback plan:
   - keep the previous installer available
