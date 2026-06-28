---
name: run-s2-report-sniffer
description: Build, run, and drive S2 Report Sniffer. Use when asked to start the app, run the backend, build the frontend, take a screenshot of the dashboard, verify the UI, upload a report, or interact with the running app.
---

S2 Report Sniffer is a FastAPI + React web app. The agent path is:
1. Start the backend (`uvicorn`) — it serves both the API and the built React UI.
2. Drive it via `.claude/skills/run-s2-report-sniffer/driver.mjs` using Playwright against the running server.

All paths below are relative to the repo root (`/home/user/S2-report-sniffer/`).

## Prerequisites

Python 3.11 and Node 20+ are already available in this container. No `apt-get` needed.

```bash
# Playwright is at a non-default location — confirm before running driver:
node -e "require('/opt/node22/lib/node_modules/playwright'); console.log('OK')"
# Chromium is at:
/opt/pw-browsers/chromium-1194/chrome-linux/chrome --version
```

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

Output goes to `frontend/build/`. Once it exists, `GET /` on the backend redirects to `/ui/`.

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

- **`chromium-cli` is not installed** — it's not in the npm registry. Use Playwright directly via
  `/opt/node22/lib/node_modules/playwright`. The driver does this. Do not `npm install chromium-cli`.

- **Playwright module path** — `require('playwright')` fails. Use the full path:
  `require('/opt/node22/lib/node_modules/playwright')`. Same for ES module import in `.mjs`:
  `import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs'`.

- **Chromium executable path** — Playwright will not find it automatically. Always pass:
  `executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'`
  and `args: ['--no-sandbox', '--disable-gpu']`.

- **Dashboard tabs are client-side state** — clicking "Charts", "Nodes", etc. in the sidebar
  does NOT change the URL. Tabs use `useState("overview")` in `ReportDashboard.jsx`. Navigate
  tabs programmatically with `[data-testid="tab-{id}"]` (e.g., `tab-charts`, `tab-nodes`,
  `tab-logs`). Navigating to `/ui/report/{id}/charts` just loads the app at overview.

- **Upload endpoint** is `/api/reports/upload` (not `/api/upload`). POST multipart `file` field.
  Accepted extensions: `.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`. Legacy `report` field name also works.

- **`EADDRINUSE` on re-launch** — kill the old process before restarting:
  `kill $(cat /tmp/s2rs-backend.pid)` or `pkill -f "uvicorn server:app"`.

- **`S2RS_DISABLE_GZIP=1`** must be set when running pytest — already set in `backend/conftest.py`,
  but needed when driving the server manually in tests to avoid double-compression issues.

## Troubleshooting

- **`Not Found` on `/api/health`**: wrong port, or the backend hasn't started yet. Check `/tmp/s2rs-backend.log`.
- **`Cannot find module 'playwright'`**: use `/opt/node22/lib/node_modules/playwright` explicitly.
- **`Error: Failed to launch chromium`**: add `--no-sandbox --disable-gpu` to the launch args and
  pass `executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'`.
- **Report stuck in "processing"**: the dummy ZIP has no node directories matching `NODE_DIR_PATTERN`;
  that's expected — status will be `ready` with 0 nodes. Real sdb-report bundles have proper structure.
