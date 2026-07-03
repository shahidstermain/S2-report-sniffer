# AGENTS.md

## Project snapshot
- `S2 Report Sniffer` analyzes offline SingleStore support bundles and turns them into report dashboards, recommendations, and exports.
- Core flow: `backend/server.py` validates uploads, extracts archives, calls `backend/parsers.py`, scores with `backend/superchecker.py`, and persists via `backend/storage.py`.
- Keep `backend/validators.py`, `backend/monitoring.py`, and `backend/storage.py` in sync when changing request or report payloads.

## Architecture to keep in mind
- This is local-first. `desktop/main.js` + `backend/desktop_entry.py` launch a bundled FastAPI backend on `127.0.0.1` and load the React UI from `/ui/`.
- When `frontend/build/` exists, `GET /` redirects to `/ui/` so UI and API share one origin.
- Local persistence is SQLite/file-based through `S2RS_DATA_DIR` (default `~/.s2-report-sniffer`; use `S2RS_DATA_DIR=./local_data` in dev); do not assume MongoDB/cloud storage.
- No data leaves the machine — no telemetry, no crash reporting, no external calls (except optional Glean MCP integration).

## Frontend/backend integration
- React router lives in `frontend/src/App.jsx`: two top-level routes — `/` (ReportList) and `/report/:reportId/*` (ReportDashboard).
- `frontend/src/lib/api.js` uses same-origin `/api` under `/ui`, otherwise `import.meta.env.VITE_BACKEND_URL` (Vite).
- `frontend/vite.config.js` proxies dev traffic from Vite dev server (port 3000) to `http://localhost:8000` for `/api`.
- All API helper functions are exported from `frontend/src/lib/api.js` — add new calls there, not inline in components.
  Key exports: `uploadReport`, `listReports`, `getReportStatus`, `getReportOverview`, `getReportNodes`, `getReportStorage`, `getReportQueries`, `getReportLogs`, `getReportRecommendations`, `getReportConfig`, `deleteReport`.

## Dashboard design source of truth
- Use `DESIGN.md` as the primary UI design reference when enhancing dashboard screens.
- Design system: dark theme (`#050507` canvas, `#00d992` accent green, warm-neutral borders).
- For AI-assisted UI work, prefer `claude-opus-4-8` when working on charts, data visualization, or information design — it produces more analytically meaningful output.
- Keep visual enhancements meaningful (improved information clarity) and visually polished while staying consistent with `DESIGN.md`.
- Charts live in `frontend/src/components/charts/` (Recharts). Dashboard container: `frontend/src/components/ChartsDashboard.jsx`.
- Feature components live in `frontend/src/components/`. Notable components: `ClusterOverview.jsx` (Overview tab), `NodeDownDetails.jsx` (offline node deep-dive — MV_EVENTS timeline, crash reason, dmesg, tracelog window; only renders when offline nodes exist), `ClusterStatePanel.jsx` (rebalance/partition movement panel — only renders when rebalance activity detected). shadcn/ui primitives live in `frontend/src/components/ui/` — do not modify them manually.

## Developer workflow
- Backend dev:
  ```bash
  cd backend
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt -r requirements-dev.txt
  S2RS_DATA_DIR=./local_data uvicorn server:app --host 127.0.0.1 --port 8000 --reload
  ```
- Frontend dev: `cd frontend && npm install && npm run dev` (Vite on port 3000)
- Frontend check: `cd frontend && npm run build && npm test`
- `dev-setup.sh` starts the backend then launches the frontend for integrated dev.

## Tests to run when behavior changes
- Backend parsing/API changes: `cd backend && python -m pytest test_parsers.py test_api_smoke.py test_superchecker.py -v`
- Frontend changes: `cd frontend && npm test && npm run build`
- Upload validation must preserve accepted formats: `.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz` and multipart field `file` (legacy `report` is also accepted).

## Conventions
- Report IDs are UUIDs. `validators.validate_report_id()` raises `ValidationError` on failure — use this in all endpoint handlers before touching the filesystem or DB.
- The upload cap is 10 GB; rate limit is 10 uploads/minute per IP.
- Python 3.11 native type syntax: use `list[str]`, `str | None` — do **not** import `List`, `Optional` from `typing`.
- All external input passes through `validators.py`. `ValidationResult.success(sanitized=...)` / `.failure([errors])` pattern.
- No `try/except/pass` broadly — only in lossy-parser sections where graceful degradation is intentional (Bandit B110 suppression is narrowly scoped).
- SQL: always use parameterized statements — no string interpolation.
- Pre-commit hook (`.githooks/pre-commit`) blocks `.trae-secrets.sh`, `mcp.json`, `.env*`, `*.pem`, `*.key`. Run `git config core.hooksPath .githooks` after cloning.

## Brain expansion playbook
- Add new checks as parser signals first, then score in `backend/superchecker.py`; avoid embedding heavy file scans directly in API endpoints.
- Keep check IDs/messages stable — `test_superchecker.py` and `test_api_smoke.py` assert on specific check identifiers and recommendation content.
- Preferred signal families from support bundles:
  - Tracelog: `*memsql.log` patterns (`ETIMEDOUT`, `fsync is behind`, `Retry loop is stalling`, `from sync to async`, backup start/success/fail).
  - Resource: `sysctl_stdout`, `free_stdout`, `ulimit_stdout`, `df_stdout`, `top_stdout`, `*dmesg_stdout`, `*memsqldProcessLimits*`.
  - Info schema snapshots: `*show-variables.tsv`, `*show-status-extended.tsv`, `*show-cluster-status.tsv`, `*distributed_databases.tsv`, `*processlist.tsv`, `*mv-backup-history.tsv`.
- Use parser extraction patterns already present in `backend/parsers.py` (glob/TSV parsing + defensive fallbacks) and store normalized numeric counters, not raw shell output.
- For time-bucketed diagnostics (hour/minute counts), emit compact aggregates in parser output (e.g., `etimedout_per_hour`) and convert to user-facing recommendations in `superchecker`.
- Keep request/report payload sync across `backend/validators.py`, `backend/monitoring.py`, and `backend/storage.py` when adding new analysis fields.
- If a new recommendation appears in backend output, validate frontend rendering under `frontend/src/components/` (especially `Recommendations.jsx` and `ClusterOverview.jsx`).

## Implemented checks (current)
All checks are in `backend/parsers.py` + `backend/superchecker.py` and exposed via the `/api/reports/{id}/overview` endpoint:
- Log timeframe detection per node (`first_log_entry`, `last_log_entry`) — rendered in **ClusterOverview** "Tracelog Coverage by Node" strip.
- Backup reliability summary (`success_count`, `failure_count`, `latest_duration_sec`) — KPI card + `BackupTimeline` chart.
- Network/storage pressure indicators: hourly `ETIMEDOUT`, `fsync is behind`, retry-stall counts — `PressureEventsChart` + superchecker findings.
- Memory pressure indicators: THP, `vm.swappiness`, `vm.overcommit*`, `vm.max_map_count`, OOM in dmesg.
- Cluster layout sanity: partition counts by role/host — per-node cards with `NP` badge and AG indicator.
- Process health snapshot: active queries, sleeping open transactions — "Queries" KPI card.
- Database disk usage: per-DB disk bytes — `DatabaseDiskChart` (top 15) and ClusterOverview table.
- Node health distribution: online/offline/degraded/recovering — `NodeHealthChart` (donut).
- Log severity breakdown: critical/error/warn/info/debug per-node — `LogSeverityChart` (donut).
- dmesg critical events table and detected log pattern list — rendered in **ClusterOverview**.
- Node state-transition event extraction (`extract_node_events` in `parsers.py`) — normalizes MV_EVENTS rows into `{event_type, event_time, severity, node_id, description, category}` with categories `node_down/node_up/failover/state_change`; exposed as `node_events` in overview response; rendered in **NodeDownDetails** (MV_EVENTS timeline + inferred crash reason).
- Rebalance/partition movement extraction (`extract_rebalance_events` in `parsers.py`) — scans MV_EVENTS for rebalance/partition/sync/move keywords and `rebalance_status` rows; exposes `{status, reason, events, raw_status}` as `rebalance_events` in overview response; rendered in **ClusterStatePanel**.
- Process restart log pattern detection — matches `starting up, version`, `memsqld started`, etc. in tracelogs; category `restart`, severity `warning`; used in NodeDownDetails crash reason inference.

## Implemented Phase 2 + Phase 4 features
- **Interactive cluster topology map** (Phase 2.1): SVG-based node layout in `TopologyMap.jsx` — MA/CA/LEAF hierarchy with connection lines, memory/disk bars, partition heatmap, hover tooltips, click-to-select. Integrated into `ClusterOverview.jsx`.
- **Animated severity gauge** (Phase 2.2): Animated SVG ring gauge for health score, animated risk bars in findings table, mini risk/confidence gauges in finding detail panel. CSS keyframe animations in `App.css`.
- **Incident clusters + triage** (Phase 2.3): `superchecker.py` groups related findings; `/api/reports/{id}/triage` returns prioritized action lists; rendered in **Recommendations**.
- **Desktop packaging** (Phase 4): PyInstaller spec (`s2rs-backend.spec`) + Electron builder config in `desktop/package.json` with signed installer support (macOS DMG, Windows MSI, Linux AppImage/DEB/RPM). Build script: `scripts/build-desktop.sh`. Portable mode launchers: `scripts/run-s2-report-sniffer.sh` (macOS/Linux) and `scripts/Run-S2ReportSniffer.bat` (Windows). macOS entitlements in `desktop/assets/entitlements.mac.plist`.

## High-value checks to implement next
- Per-node memory utilization trend over time (from process snapshots).
- Replication lag detection from async-transition log patterns.
- Query pattern analysis: identify slow/runaway queries from processlist snapshots.
- Long-running transaction detection and lock contention indicators.

## Good reference files
- `CLAUDE.md` — comprehensive AI assistant reference (architecture, API shapes, module deep dives, security conventions).
- `DESIGN.md` — UI design system (colors, typography, spacing).
- `README.md`, `DEPLOYMENT.md`, `PACKAGING.md`, `INTEGRATION.md`, `AIRGAP_TEST_PROTOCOL.md`.

## Learned User Preferences
- Create a feature branch before committing when starting from `main`; do not commit directly on `main`.
- Never stage or commit files under `.cursor/`.
- Stage explicit file paths with `git add <files…>`; avoid `git add -A` when `.cursor/` or other untracked noise is present.
- Keep commits scoped to one logical change; do not mix unrelated fixes in a single commit.
- Do not push to remote unless explicitly asked.

## Learned Workspace Facts
- Active feature work for topology map, incident clusters, and desktop packaging lives on branch `feat/topology-incident-clusters-desktop-packaging` (not yet merged to `main`).
- `get_report_triage` bucket assignment is mutually exclusive: priority 1 → `act_now`, elif `quick_win` → `quick_wins`, elif priority 2 → `act_soon`, else `backlog` (priority 1 wins over `quick_win`).
- Triage bucket mutual-exclusivity tests live in `backend/test_server_endpoints.py` (`TestReportTriage`), not `test_api_smoke.py`.
- Python virtualenv may exist at repo root `.venv` and/or `backend/.venv`; use whichever is present when running pytest.
