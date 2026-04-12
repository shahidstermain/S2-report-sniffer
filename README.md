# S2 Report Sniffer (SingleStore Report Sniffer v1)

S2 Report Sniffer is a diagnostics platform for analyzing archived SingleStore support reports (`.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`) and transforming raw collector output into actionable cluster health insights.

## 1) Project Overview

### Purpose

- Parse offline SingleStore report bundles safely.
- Surface operational risk, performance bottlenecks, and configuration drift.
- Prioritize remediation through SuperChecker risk scoring and fix-first findings.
- Provide API-driven and UI-driven workflows for support engineers and DB operators.

### Goals

- Eliminate manual grep-based triage of large support bundles.
- Correlate findings across logs, metrics, and configuration data.
- Standardize diagnostics output for incident response and handoff.
- Support export-friendly summaries for collaboration channels.

### High-Level Architecture

```text
┌──────────────────────────┐
│ Report Archive Upload    │  (.zip/.tar.gz)
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ FastAPI Backend          │
│ - Validation             │
│ - Secure Extraction      │
│ - Parsing + Aggregation  │
│ - SuperChecker Engine    │
└────────────┬─────────────┘
             │
   ┌─────────┴─────────┐
   ▼                   ▼
┌──────────────┐   ┌────────────────┐
│ MongoDB      │   │ React Frontend │
│ Report Store │   │ Dashboards     │
└──────────────┘   └────────────────┘
```

## 2) Core Features

- Secure archive handling with path traversal checks.
- Structured report parsing for nodes, storage, queries, logs, pipelines, and config.
- SuperChecker diagnostics engine:
  - finding metadata (`checker_id`, `risk_score`, `confidence`, `fix_first`, `related_findings`)
  - cross-finding correlation
  - remediation-ready findings
- Monitoring endpoints (`/api/health`, `/api/alerts`, `/api/metrics/performance`).
- Export endpoints:
  - Slack-ready summary
  - HTML report payload
- Report diff endpoint (`/api/reports/diff`) for change tracking.
- Dashboard views:
  - Cluster Overview
  - Node Health
  - Storage Distribution
  - Workload Queries
  - Log Explorer
  - Config Health
  - Recommendations

## 3) Repository Structure

```text
S2-report-sniffer/
├─ backend/
│  ├─ server.py            # FastAPI routes, persistence, orchestration
│  ├─ parsers.py           # report extraction and parsing pipeline
│  ├─ superchecker.py      # diagnostics/risk engine
│  ├─ validators.py        # request/input sanitization + validation
│  ├─ monitoring.py        # health/alerts/performance components
│  ├─ test_parsers.py      # parser/superchecker tests
│  └─ test_api_smoke.py    # API smoke tests
├─ frontend/
│  ├─ src/components/      # dashboard widgets
│  ├─ src/pages/           # report list + dashboard pages
│  └─ src/lib/api.js       # API client bindings
├─ backend_test.py         # API smoke script for deployed backend
├─ Dockerfile              # backend container build
└─ README.md
```

## 4) Requirements

### System

- macOS/Linux
- Python 3.10+ (project can run with higher versions; dependency compatibility should be verified)
- Node.js 18+ and npm
- MongoDB 6+ (required for full functionality; degraded mode runs without DB)

### Python packages

- Use `backend/requirements.txt`
- Note: one package in the lock list may be private/unavailable in public indexes (`emergentintegrations==0.1.0`).

## 5) Installation and Setup

### 5.1 Clone

```bash
git clone <your-repo-url>
cd S2-report-sniffer
```

### 5.2 Backend setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
```

If `emergentintegrations==0.1.0` is unavailable, install required runtime dependencies manually:

```bash
pip install fastapi uvicorn motor pymongo python-dotenv aiofiles python-multipart
```

### 5.3 Frontend setup

```bash
cd frontend
npm install
cd ..
```

### 5.4 Environment configuration

Create `backend/.env`:

```env
MONGO_URL=mongodb://localhost:27017
DB_NAME=s2_sniffer
```

Create `frontend/.env`:

```env
REACT_APP_BACKEND_URL=http://localhost:8000
```

### 5.5 Run locally

Backend:

```bash
. .venv/bin/activate
cd backend
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```bash
cd frontend
npm start
```

Open `http://localhost:3000`.

## 6) API Documentation

Base URL: `http://localhost:8000/api`

### 6.1 Upload and lifecycle

- `POST /reports/upload`  
  Upload an archive file.
- `GET /reports`  
  List reports.
- `GET /reports/{report_id}/status`  
  Check parse progress.
- `GET /reports/{report_id}`  
  Full report payload.
- `DELETE /reports/{report_id}`  
  Delete report and associated artifacts.

### 6.2 Analysis endpoints

- `GET /reports/{report_id}/overview`
- `GET /reports/{report_id}/nodes`
- `GET /reports/{report_id}/storage`
- `GET /reports/{report_id}/queries`
- `GET /reports/{report_id}/logs`
- `GET /reports/{report_id}/pipelines`
- `GET /reports/{report_id}/recommendations`
- `GET /reports/{report_id}/config`

### 6.3 Operational endpoints

- `GET /health`
- `GET /alerts`
- `GET /metrics/performance`
- `GET /reports/diff?from_id=<id>&to_id=<id>`
- `GET /reports/{report_id}/export/slack`
- `GET /reports/{report_id}/export/html`

### 6.4 Example API usage

Upload:

```bash
curl -X POST "http://localhost:8000/api/reports/upload" \
  -F "file=@/path/to/sdb-report.tar.gz"
```

Get recommendations:

```bash
curl "http://localhost:8000/api/reports/<REPORT_ID>/recommendations"
```

Diff two reports:

```bash
curl "http://localhost:8000/api/reports/diff?from_id=<OLD_ID>&to_id=<NEW_ID>"
```

Slack summary export:

```bash
curl "http://localhost:8000/api/reports/<REPORT_ID>/export/slack"
```

## 7) Configuration Parameters

### Backend

- `MONGO_URL`: MongoDB connection string.
- `DB_NAME`: Mongo database name.

### Frontend

- `REACT_APP_BACKEND_URL`: backend base URL used by the API client.

### Limits and validation behavior

- Upload max size: 10 GB.
- Allowed upload extensions: `.tar.gz`, `.tgz`, `.zip`, `.tar`, `.gz`.
- Report IDs validated as UUID format.
- Search and filter inputs sanitized to reduce injection risk.

## 8) Usage Guide

### Typical workflow

1. Upload a report archive from the UI.
2. Wait for parse completion in report status.
3. Open report dashboard and inspect:
   - risk/fix-first recommendations first
   - node/storage/query/log anomalies
4. Export summaries for incident communication.
5. Compare historical snapshots via diff endpoint.

### SuperChecker output semantics

- `severity`: `critical | warning | info`
- `risk_score`: `0..100` per finding
- `confidence`: `0.05..1.00`
- `fix_first`: boolean urgency marker
- `related_findings`: correlated finding IDs

## 9) Troubleshooting

### MongoDB unavailable / degraded mode

Symptoms:

- report-list endpoints return `503`
- health endpoint shows degraded status

Actions:

- verify MongoDB process and connectivity
- validate `MONGO_URL` and `DB_NAME`
- restart backend after correcting env values

### Upload validation failures

Symptoms:

- `400 Invalid file`

Actions:

- ensure supported archive extension
- ensure filename uses safe characters
- verify upload size under configured max

### Frontend cannot call backend

Symptoms:

- network errors in browser

Actions:

- verify `REACT_APP_BACKEND_URL`
- confirm backend reachable at configured URL
- validate CORS/network routing

### Dependency install fails on private package

Symptoms:

- pip error for `emergentintegrations==0.1.0`

Actions:

- use internal package index or wheel
- for local smoke runs, install runtime dependencies manually

## 10) Testing

### Backend unit/integration

```bash
. .venv/bin/activate
cd backend
python -m unittest test_parsers.py -v
python -m unittest test_api_smoke.py -v
```

### Coverage

```bash
. .venv/bin/activate
cd backend
coverage run -m unittest test_parsers.py test_api_smoke.py
coverage report -m
```

### Frontend

```bash
cd frontend
npm test -- --watchAll=false
npm run build
```

## 11) Monitoring and Alerts

- `/api/health` aggregates registered health checks.
- `/api/alerts` returns active alerts from the monitoring subsystem.
- `/api/metrics/performance` returns performance counters/timing windows.

Recommended production integration:

- scrape health and alert endpoints regularly
- route alert signals to pager/incident channels
- archive diagnostics payloads for post-incident review

## 12) Deployment

### Docker

```bash
docker build -t s2-sniffer .
docker run --rm -p 8000:8000 \
  -e MONGO_URL="mongodb://host.docker.internal:27017" \
  -e DB_NAME="s2_sniffer" \
  s2-sniffer
```

### Offline Desktop Installers

This project supports a self-contained offline desktop distribution (Windows/macOS/Linux) that bundles:

- backend runtime as a local executable
- frontend UI as bundled static assets
- local persistence (SQLite + file-based report payload/logs)

Build and packaging documentation:

- [PACKAGING.md](file:///Users/shahidmoosa/cr-sniffer/S2-report-sniffer/PACKAGING.md)
- [USER_MANUAL.md](file:///Users/shahidmoosa/cr-sniffer/S2-report-sniffer/USER_MANUAL.md)
- [AIRGAP_TEST_PROTOCOL.md](file:///Users/shahidmoosa/cr-sniffer/S2-report-sniffer/AIRGAP_TEST_PROTOCOL.md)

## 13) Building the Apple Silicon macOS DMG

A one-command script is provided to produce a self-contained, installable `.dmg` for Apple Silicon (arm64) Macs. No code signing or notarization is performed.

### Prerequisites

- macOS running on Apple Silicon (arm64)
- [Node.js](https://nodejs.org/) (v18+) and `npm`
- Python 3 (`python3` must be on `PATH`)

### Run the build

From the repository root:

```bash
bash scripts/build-macos-arm64-dmg.sh
```

The script performs three steps automatically:

1. **Frontend** – runs `npm ci && npm run build` inside `frontend/`, producing `frontend/build/`.
2. **Backend** – creates a Python virtual environment, installs dependencies from `backend/requirements.txt`, and uses **PyInstaller** to produce a single-file executable `dist/backend/s2rs-backend`.
3. **DMG** – runs `npm ci && npm run dist` inside `desktop/` via **electron-builder**.

The finished `.dmg` installer is written to **`desktop/dist/`**.

> **Note:** This script does not sign or notarize the application. For distribution outside your own machine, follow Apple's [notarization guide](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution).

## 14) Contribution Guidelines

1. Create a feature branch.
2. Keep changes focused and tested.
3. Add/adjust backend tests for parser/checker/API behavior.
4. Build frontend before opening PR.
5. Include risk/impact notes in PR description.

Suggested PR checklist:

- [ ] Unit tests pass
- [ ] API smoke tests pass
- [ ] Frontend build passes
- [ ] Security scan reviewed
- [ ] README/docs updated

## 15) Documentation Quality Notes

- Use code blocks for every shell command and payload example.
- Keep endpoint behavior synchronized with actual route handlers.
- Document degraded-mode behavior whenever DB dependencies are involved.

## 16) License

No explicit license file is currently included in the repository.  
Add a `LICENSE` file (for example MIT/Apache-2.0/Proprietary) before external distribution.
