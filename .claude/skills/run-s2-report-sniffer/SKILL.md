---
name: run-s2-report-sniffer
description: Build, run, and drive S2 Report Sniffer. Use when asked to start the app, run the backend, build the frontend, take a screenshot of the dashboard, verify the UI, upload a report, or interact with the running app.
---

S2 Report Sniffer is a FastAPI + React web app. The agent path is:
1. Start the backend (`uvicorn`) — it serves both the API and the built React UI.
2. Drive it via `.claude/skills/run-s2-report-sniffer/driver.mjs` using Playwright against the running server.

All paths below are relative to the repo root (`S2-report-sniffer/`).

## Prerequisites

On this machine (macOS arm64): Python 3.14, Node 26, and Playwright 1.59.1 are available.

```bash
# Confirm Playwright in frontend node_modules:
node -e "import('/Users/shahidster-macmini/S2-report-sniffer/frontend/node_modules/playwright/index.mjs').then(m => console.log('playwright OK'))"

# Chromium is at:
"$HOME/Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" --version
```

No `apt-get` needed. No system-wide Playwright install — use the one in `frontend/node_modules`.

## Setup

```bash
# Backend Python venv (one-time)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Frontend dependencies (one-time)
cd ../frontend && npm install
```

## Build (frontend)

The backend serves the built React app at `/ui/`. Build once before starting:

```bash
cd frontend && npm run build
```

Output goes to `frontend/build/`. Once built, `GET /` redirects to `/ui/`.

## Run (agent path)

**Start the backend** (integrated mode — serves API + built UI):

```bash
cd backend && source .venv/bin/activate
S2RS_DATA_DIR=/tmp/s2rs-data S2RS_DISABLE_GZIP=1 \
  uvicorn server:app --host 127.0.0.1 --port 8000 --log-level warning \
  > /tmp/s2rs-backend.log 2>&1 &
echo $! > /tmp/s2rs-backend.pid

# Wait until healthy (polls every 0.5s, times out at 20s):
timeout 20 bash -c \
  'until curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; do sleep 0.5; done' \
  && echo "READY"
```

**Run the Playwright driver** to verify and interact:

```bash
node .claude/skills/run-s2-report-sniffer/driver.mjs [base-url] [out-dir]
# Defaults: base-url=http://127.0.0.1:8000, out-dir=/tmp/s2rs-shots/
```

The driver:
1. Hits `/api/health` — exits 1 on failure.
2. Screenshots the report list at `/ui/`.
3. Uploads a minimal synthetic ZIP via `POST /api/reports/upload`.
4. Polls `/api/reports/{id}/status` until `ready`.
5. Screenshots the report Overview dashboard.
6. Clicks the Charts tab (`[data-testid="tab-charts"]`) and screenshots.
7. Reports any JS console errors.

Screenshots land in `out-dir/` as `01-report-list.png`, `02-report-overview.png`, `03-charts-dashboard.png`.

**Stop the backend:**

```bash
kill $(cat /tmp/s2rs-backend.pid) 2>/dev/null; rm -f /tmp/s2rs-backend.pid
```

**Quick API smoke (no browser):**

```bash
curl -sf http://127.0.0.1:8000/api/health | python3 -m json.tool
curl -sf http://127.0.0.1:8000/api/reports               # → []
```

## Run (human path)

```bash
# Terminal 1 — backend with hot reload
cd backend && source .venv/bin/activate
S2RS_DATA_DIR=./local_data uvicorn server:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — Vite dev server (proxies /api → :8000)
cd frontend && npm run dev   # → http://localhost:3000
```

Open `http://localhost:3000` in a browser. Ctrl-C both terminals to stop.

## Test

```bash
# Backend
cd backend && source .venv/bin/activate && python -m pytest -q

# Frontend (vitest, one-shot)
cd frontend && npm test

# Frontend build check
cd frontend && npm run build
```

## Gotchas

- **Playwright module path** — `import { chromium } from 'playwright'` fails. Use the full path:
  `frontend/node_modules/playwright/index.mjs`. The driver does this. Do not `npm install playwright` globally.

- **Chromium executable path** — Playwright's auto-detect does not find it. The driver reads
  `CHROMIUM_PATH` env var, falling back to:
  `$HOME/Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`
  If the version has been updated, check `ls ~/Library/Caches/ms-playwright/` for the current chromium-* directory.

- **Charts tab shows "Loading charts..." for smoke-test ZIPs** — the synthetic ZIP has no node
  directories matching `NODE_DIR_PATTERN`, so the report has 0 nodes and no time-series data.
  This is expected. Real `sdb-report` bundles render full charts. The screenshot confirms the
  tab navigation worked; the empty state is not a bug.

- **Dashboard tabs are client-side state** — clicking "Charts", "Nodes", etc. in the sidebar
  does NOT change the URL. Tabs use `useState("overview")` in `ReportDashboard.jsx`. Navigate
  programmatically with `[data-testid="tab-{id}"]` (e.g., `tab-charts`, `tab-nodes`, `tab-logs`).
  Navigating to `/ui/report/{id}/charts` just loads the app at overview.

- **Upload endpoint** is `/api/reports/upload` (not `/api/upload`). POST multipart `file` field.
  Accepted extensions: `.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`. Legacy `report` field also works.

- **`EADDRINUSE` on re-launch** — kill the old process before restarting:
  `kill $(cat /tmp/s2rs-backend.pid)` or `pkill -f "uvicorn server:app"`.

- **`S2RS_DISABLE_GZIP=1`** must be set when running pytest — already set in `backend/conftest.py`,
  but needed when driving the server manually to avoid double-compression issues.

- **AI RCA unavailable** on Overview/Issues when cloud extensions are disabled (the default).
  Set `S2RS_ENABLE_CLOUD_EXTENSIONS=1`, install Cursor CLI, and run `cursor agent login`.

## Troubleshooting

- **`READY` never prints**: backend failed to start. Check `/tmp/s2rs-backend.log`.
- **`Cannot find module 'playwright'`**: the driver imports from an absolute path — verify the
  `frontend/node_modules/playwright/index.mjs` path exists before running.
- **`Error: Failed to launch chromium`**: the chromium-1228 directory may not exist. Run
  `ls ~/Library/Caches/ms-playwright/` and update `CHROMIUM_PATH` in the driver or export the env var.
- **Report stuck in "processing"**: the dummy ZIP has no node directories — status will be `ready`
  with 0 nodes and 2 info-level findings. This is correct behavior.
