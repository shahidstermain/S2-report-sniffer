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
- No cloud services required.
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
npm start
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
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
pip install pyinstaller
```

Build:

```bash
pyinstaller --noconfirm --clean \
  --name s2rs-backend \
  --onefile \
  --paths backend \
  backend/desktop_entry.py
mkdir -p dist/backend
cp dist/s2rs-backend* dist/backend/
```

### Step 3: Build the Desktop Installer

```bash
cd desktop
npm install
npm run dist
```

The Electron config bundles:

- `../frontend/build` -> app resource `ui/`
- `../dist/backend`  -> app resource `backend/`

## Offline Update Mechanism

The packaged app supports an offline update workflow:

1. Download a newer installer package (MSI/DMG/AppImage/DEB/RPM) via any method.
2. Copy it to the target machine.
3. Open the app and use: `File -> Install Update Package`
4. The OS installer handles the update and keeps user data in `S2RS_DATA_DIR`.

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

