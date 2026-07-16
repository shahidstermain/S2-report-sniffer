# AGENTS.md

## Project snapshot
- `S2 Report Sniffer` analyzes offline SingleStore support bundles and turns them into report dashboards, recommendations, and exports.
- Core flow: `backend/server.py` validates uploads, extracts archives, calls `backend/parsers.py`, scores with `backend/superchecker.py`, and persists via `backend/storage.py`.
- Keep `backend/validators.py`, `backend/monitoring.py`, and `backend/storage.py` in sync when changing request or report payloads.

## Architecture to keep in mind
- This is local-first. `desktop/main.js` + `backend/desktop_entry.py` launch a bundled FastAPI backend on `127.0.0.1` and load the React UI from `/ui/`.
- When `frontend/build/` exists, `GET /` redirects to `/ui/` so UI and API share one origin.
- Local persistence is SQLite/file-based through `S2RS_DATA_DIR` (default `~/.s2-report-sniffer`; use `S2RS_DATA_DIR=./local_data` in dev); do not assume MongoDB/cloud storage.
- No data leaves the machine — no telemetry, no crash reporting, no backend egress for RCA. Optional Hostinger remains gated by `S2RS_ENABLE_CLOUD_EXTENSIONS`.
- **Analyze in Glean:** Issues toolbar builds a local Markdown incident packet (`GET /api/reports/{id}/export/glean`) with findings and suspected log lines, then downloads it / opens the Glean macOS app. The user attaches the file in Glean Chat — nothing is sent until they do. See `docs/ai-rca-design.md`.

## Frontend/backend integration
- React router lives in `frontend/src/App.jsx`: two top-level routes — `/` (ReportList) and `/report/:reportId/*` (ReportDashboard).
- `frontend/src/lib/api.js` uses same-origin `/api` under `/ui`, otherwise `import.meta.env.VITE_BACKEND_URL` (Vite).
- `frontend/vite.config.js` proxies dev traffic from Vite dev server (port 3000) to `http://localhost:8000` for `/api`.
- All API helper functions are exported from `frontend/src/lib/api.js` — add new calls there, not inline in components.
  Key exports: `uploadReport`, `listReports`, `getReportStatus`, `getReportOverview`, `getReportNodes`, `getReportStorage`, `getReportQueries`, `getReportLogs`, `getReportRecommendations`, `getReportConfig`, `deleteReport`, `getGleanPacket`.

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
- Run a single backend test file: `cd backend && .venv/bin/python -m pytest test_log_search.py -v` (no need to activate the venv). Full suite: `.venv/bin/python -m pytest` (~538 tests across all test files).
- Backend QA tools (in `requirements-dev.txt`): `black`, `flake8`, `mypy`, `isort`. There is no repo-wide lint script — run `flake8 <file>` / `black --check <file>` directly. `bandit.yaml` configures Bandit security scans.
- Frontend changes: `cd frontend && npm test && npm run build`. **No `npm run lint` or typecheck script exists** — `npm test` (Vitest) + `npm run build` (Vite) are the only frontend gates.
- Log-search behavior: `cd backend && .venv/bin/python -m pytest test_log_search.py test_log_search_raw.py -v` (covers parsed-mode bugs A/B/C/F/G and raw-mode context/compressed/multi-node).
- Upload validation must preserve accepted formats: `.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz` and multipart field `file` (legacy `report` is also accepted).

## Conventions
- Report IDs are UUIDs. `validators.validate_report_id()` raises `ValidationError` on failure — use this in all endpoint handlers before touching the filesystem or DB.
- The upload cap is 10 GB; rate limit is 10 uploads/minute per IP.
- Python 3.11 native type syntax: use `list[str]`, `str | None` — do **not** import `List`, `Optional` from `typing`.
- All external input passes through `validators.py`. `ValidationResult.success(sanitized=...)` / `.failure([errors])` pattern.
- No `try/except/pass` broadly — only in lossy-parser sections where graceful degradation is intentional (Bandit B110 suppression is narrowly scoped).
- SQL: always use parameterized statements — no string interpolation.
- Pre-commit hook (`.githooks/pre-commit`) blocks `.trae-secrets.sh`, `mcp.json`, `.env*`, `*.pem`, `*.key`. Run `git config core.hooksPath .githooks` after cloning.

## Storage schema changes (3-place allowlist gotcha)
When adding a new column to the `reports` table in `backend/storage.py`, you must touch **all three** places or the column silently won't read/write:
1. `_init_db()` — add `ALTER TABLE reports ADD COLUMN <name> TYPE` (additive migration pattern).
2. `update_report_fields()` — add the column to the `allowed` set, else writes are silently dropped.
3. `get_report_fields()` — add the column to the `allowed` list, else `fields=["<name>"]` selects only `id` and returns `None` for your column.
The payload JSON (`report.json`) is separate from these SQL columns — overview/nodes/etc. go through `write_report_payload`, not `update_report_fields`.

## Log search (dual-mode)
`/api/reports/{id}/logs/search` has two modes, reported in the response as `search_mode`:
- **`raw`** — preferred when an extracted report root is persisted on disk. Calls `search_all_trace_logs` (wraps `search_trace_logs_raw`) across every node's `memsqlTracelogs/`, scans compressed + uncompressed `*_memsql.log`, and returns `context_before`/`context_after`/`line`/`line_number` per match.
- **`parsed`** — fallback over `logs.jsonl` via `LocalReportStore.search_report_logs`. No context windows; matches against `timestamp + message + hostname`.
The extracted root lives at `<S2RS_DATA_DIR>/reports/{id}/extracted/` and is auto-cleaned by `delete_report`'s tree wipe. Persistence is gated by `S2RS_MAX_EXTRACTED_KEEP_GB` (default **2 GB**, env-tunable; `0` disables). Over-cap reports still parse but fall back to parsed mode. Directory imports persist the import path in place (no copy). When adding log-search tests, use `test_log_search.py` (parsed mode) and `test_log_search_raw.py` (raw mode).

## Brain expansion playbook
- Add new checks as parser signals first, then score in `backend/superchecker.py`; avoid embedding heavy file scans directly in API endpoints.
- Keep check IDs/messages stable — `test_superchecker.py` and `test_api_smoke.py` assert on specific check identifiers and recommendation content.
- **Ground every check.** Add a `GROUNDING` entry in `backend/grounding.py` for each new `checker_id`: `basis` (`documented`/`toolbox-default`/`heuristic`/`observed`), a verified `source` URL, and a one-line `criterion`. `_add()` attaches this to every finding and `resolve_doc_link()` swaps generic `https://docs.singlestore.com/` placeholders for the grounded source. Label rule-of-thumb thresholds as `heuristic`; never fabricate doc URLs (leave `source=""` if unverified). The UI shows a **Basis** chip + criterion in the finding detail panel.
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
- Query pattern analysis (`extract_query_patterns` in `parsers.py`) — identifies slow (>{30s), runaway (>{5min) queries, repeated normalized SQL patterns (≥3x), and top queries by memory; exposed as `query_patterns` in overview response; rendered in **QueryPatternsPanel**. Superchecker rules: `runawayQueries` (critical), `slowQueries` (warning/critical), `repeatedQueryPatterns` (info), `highQueryMemoryUsage` (warning >4GB).
- Replication lag analysis (`extract_replication_lag_patterns` in `parsers.py`) — detects lagging pairs (>{5s warning, >{30s critical), computes avg/max lag, counts sync→async transitions from log patterns; classifies state as healthy/degraded/critical; exposed as `replication_lag_patterns` in overview response; rendered in **ReplicationLagPanel**. Superchecker rules: `replicationLagCritical` (critical), `replicationLagDegraded` (warning), `asyncTransitionDetected` (critical).
- Interactive cluster topology map (`ClusterTopologyMap.tsx`) — tiered MA → CA → Leaf layout (replaced force-directed) with three labeled role bands, replication edges colored by lag severity (green/amber/red with lag labels in seconds), per-node resource rings (inner = memory %, outer = disk %), zoom/pan, hover tooltips, and click-to-select details panel.
- Per-node memory utilization trend (`extract_memory_utilization_trend` in `parsers.py`) — combines MV_NODES engine memory + OS `free` memory + swap; computes table vs non-table (working set), per-node status (healthy/warning/critical), cluster summary (avg %, nodes over 80%/90%, highest node); exposed as `memory_utilization` in overview; rendered in **MemoryUtilizationPanel**. Superchecker rules: `memoryUtilizationCritical` (critical >90%), `memoryUtilizationWarning` (warning >80%), `swapUsageDetected` (warning >25%, critical >50%).
- Long-running transaction & lock contention (`extract_long_running_transactions` in `parsers.py`) — detects transactions running >60s, lock-waiting connections, blocking chains from `MV_BLOCKED_QUERIES`, unkillable transactions; classifies contention as none/moderate/severe; exposed as `long_running_transactions` in overview; rendered in **LongRunningTransactionsPanel**. Superchecker rules: `longRunningTransactions` (warning >60s, critical >300s), `lockContention` (warning, blocking chains), `severeLockContention` (critical, chain ≥10), `unkillableTransaction` (critical, unkillable).

## Implemented Phase 2 + Phase 4 features
- **Interactive cluster topology map** (Phase 2.1): SVG-based node layout in `TopologyMap.jsx` — MA/CA/LEAF hierarchy with connection lines, memory/disk bars, partition heatmap, hover tooltips, click-to-select. Integrated into `ClusterOverview.jsx`.
- **Animated severity gauge** (Phase 2.2): Animated SVG ring gauge for health score, animated risk bars in findings table, mini risk/confidence gauges in finding detail panel. CSS keyframe animations in `App.css`.
- **Incident clusters + triage** (Phase 2.3): `superchecker.py` groups related findings; `/api/reports/{id}/triage` returns prioritized action lists; rendered in **Recommendations**.
- **Desktop packaging** (Phase 4): PyInstaller spec (`s2rs-backend.spec`) + Electron builder config in `desktop/package.json` with signed installer support (macOS DMG, Windows MSI, Linux AppImage/DEB/RPM). Build script: `scripts/build-desktop.sh`. Portable mode launchers: `scripts/run-s2-report-sniffer.sh` (macOS/Linux) and `scripts/Run-S2ReportSniffer.bat` (Windows). macOS entitlements in `desktop/assets/entitlements.mac.plist`.

## High-value checks to implement next
- Code signing and notarization for desktop builds (macOS Developer ID, Windows Authenticode).
- Auto-update mechanism for desktop app (electron-updater + GitHub releases).

## Good reference files
- `CLAUDE.md` — comprehensive AI assistant reference (architecture, API shapes, module deep dives, security conventions).
- `DESIGN.md` — UI design system (colors, typography, spacing).
- `README.md`, `DEPLOYMENT.md`, `PACKAGING.md`, `INTEGRATION.md`, `AIRGAP_TEST_PROTOCOL.md`.
- Several one-off `*_REPORT.md` / `*_CHECKLIST.md` files at the root are historical snapshots (audit, preprod, phase1) — verify before relying on them.

## Learned User Preferences
- Create a feature branch before committing when starting from `main`; do not commit directly on `main`.
- Never stage or commit files under `.cursor/`.
- Never commit customer investigation logs or large sample support-bundle archives; keep them local and gitignored.
- Never commit `.build/` PyInstaller artifacts to git — GitHub rejects files >100MB; `.build/` is gitignored but was previously tracked.
- Stage explicit file paths with `git add <files…>`; avoid `git add -A` when `.cursor/` or other untracked noise is present.
- Keep commits scoped to one logical change; do not mix unrelated fixes in a single commit.
- Do not push to remote unless explicitly asked.
- Do not edit attached implementation plan files; implement changes in the codebase only.
- Ground analysis thresholds and user-facing terminology against docs.singlestore.com; when analysis logic is uncertain, use Glean MCP for company evidence before inventing rules.
- Never invent client-side health scores/grades or measured-looking zeros when backend data is absent — show unknown/`—`.
- Keep stable checker IDs/API fields; align visible labels with SingleStore docs vocabulary (e.g. prefer “long-running” over undocumented “runaway”).

## Learned Workspace Facts
- Analyze in Glean builds a whole-report Markdown packet via `build_glean_packet()` / `GET /api/reports/{id}/export/glean`; desktop handoff is `window.s2rsDesktop.gleanHandoff` (preload IPC). Packet includes per-cluster `log_context`, `detected_log_patterns`, and `node_events`; egress only when user attaches in Glean. `gleanHandoff.js` handles Electron IPC + browser fallback; `gleanConstants.js` URL helpers (`gleanWebAppOrigin()` strips `-be`; MCP Settings opens `app.glean.com`). Distinct from Copy Summary (short human brief) and Export JSON (machine dump).
- Incident clusters gain `log_context` on `/api/reports/{id}/triage` and `/overview` reads via `resolve_incident_clusters()` when missing — no re-upload required. One sdb-report is one cluster; the Recommendations “Incident Clusters” UI section was removed as misleading.
- Log search keywords must be tracelog message/pattern terms, not superchecker checker IDs (e.g. `runawayQueries` never appears in `memsql.log`).
- Table-skew analytics excludes zero-row hosts and cannot detect partitionless idle leaves — use `clusterLayoutImbalance` for layout skew.
- `get_report_triage` bucket assignment is mutually exclusive: priority 1 → `act_now`, elif `quick_win` → `quick_wins`, elif priority 2 → `act_soon`, else `backlog` (priority 1 wins over `quick_win`).
- `health_score`/`health_grade` are backend-owned (numeric + letter); legacy stored string scores need normalization. Missing memory/replication/processlist signals should be null/`unknown`, not `0`/`healthy`.
- Python virtualenv may exist at repo root `.venv` and/or `backend/.venv`; use whichever is present when running pytest.
- `S2RS_DATA_DIR` is cwd-relative — `S2RS_DATA_DIR=./local_data` from `backend/` writes to `backend/local_data`, not repo-root `.local_data`.
- Stale zip-upload reports lack `extended_diagnostics` until directory import or `POST /api/reports/{id}/rehydrate-diagnostics`; MV_EVENTS/CPU/network panels need file-backed bundles with sysinfo. `missingClusterDb` checks the `cluster` system database (not `cluster_management`).
- TypeScript 6 deprecates `baseUrl` in `frontend/jsconfig.json`/`tsconfig.json` — remove `baseUrl` and use explicit `"@/*": ["./src/*"]` path aliases.
- Desktop DMG: `PYTHON_BIN=python3.11 bash scripts/build-desktop.sh` → `dist/installers/S2 Report Sniffer-1.0.0-arm64.dmg`; prefer Python 3.11 over 3.14 for PyInstaller. `backend/s2rs-backend.spec` `_SKIP_DIRS` must include `local_data`. Packaging must ad-hoc reseal the `.app` with sealed resources and pass `codesign --verify --deep --strict` or Gatekeeper reports “damaged”; quarantine clear: `scripts/macos-clear-quarantine.sh` / `xattr -cr`. Electron Copy/Paste needs an Edit menu plus `window.s2rsDesktop.clipboardWriteText` (prefer over `navigator.clipboard` in the sandbox).
- Chart/overview table fields (`backup_history`, `database_disk_usage`, `cluster_overview.nodes_detail`) may arrive as `{ rows: [...] }` wrappers; normalize with frontend `asRowList()` and backend `_as_row_list()` before `.map()`.

## Skill routing
gstack skills are available on this machine (invoke by name, e.g. `/investigate`, `/qa`, `/review`, `/ship`). The full trigger→skill table is enumerated in this session's `available_skills`; match on the trigger description there rather than maintaining a copy here.

## Log search (dual-mode)
`/api/reports/{id}/logs/search` has two modes, reported in the response as `search_mode`:
- **`raw`** — preferred when an extracted report root is persisted on disk. Calls `search_all_trace_logs` (wraps `search_trace_logs_raw`) across every node's `memsqlTracelogs/`, scans compressed + uncompressed `*_memsql.log`, and returns `context_before`/`context_after`/`line`/`line_number` per match.
- **`parsed`** — fallback over `logs.jsonl` via `LocalReportStore.search_report_logs`. No context windows; matches against `timestamp + message + hostname`.
The extracted root lives at `<S2RS_DATA_DIR>/reports/{id}/extracted/` and is auto-cleaned by `delete_report`'s tree wipe. Persistence is gated by `S2RS_MAX_EXTRACTED_KEEP_GB` (default **2 GB**, env-tunable; `0` disables). Over-cap reports still parse but fall back to parsed mode. Directory imports persist the import path in place (no copy). When adding log-search tests, use `test_log_search.py` (parsed mode) and `test_log_search_raw.py` (raw mode).

## Storage schema changes (3-place allowlist gotcha)
When adding a new column to the `reports` table in `backend/storage.py`, you must touch **all three** places or the column silently won't read/write:
1. `_init_db()` — add `ALTER TABLE reports ADD COLUMN <name> TYPE` (additive migration pattern).
2. `update_report_fields()` — add the column to the `allowed` set, else writes are silently dropped.
3. `get_report_fields()` — add the column to the `allowed` list, else `fields=["<name>"]` selects only `id` and returns `None` for your column.
The payload JSON (`report.json`) is separate from these SQL columns — overview/nodes/etc. go through `write_report_payload`, not `update_report_fields`.

