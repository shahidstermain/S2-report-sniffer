# AGENTS.md

## Project snapshot
- `S2 Report Sniffer` analyzes offline SingleStore support bundles and turns them into report dashboards, recommendations, and exports.
- Core flow: `backend/server.py` validates uploads, extracts archives, calls `backend/parsers.py`, scores with `backend/superchecker.py`, and persists via `backend/storage.py`.
- Keep `backend/validators.py`, `backend/monitoring.py`, and `backend/storage.py` in sync when changing request or report payloads.

## Architecture to keep in mind
- This is local-first. `desktop/main.js` + `backend/desktop_entry.py` launch a bundled FastAPI backend on `127.0.0.1` and load the React UI from `/ui/`.
- When `frontend/build` exists, `GET /` redirects to `/ui/` so UI and API share one origin.
- Local persistence is SQLite/file-based through `S2RS_DATA_DIR` (or repo-local `.local_data` in dev); do not assume MongoDB/cloud storage for the desktop path.

## Frontend/backend integration
- React routes live in `frontend/src/App.js`: `/`, `/report/:reportId/*`.
- `frontend/src/lib/api.js` uses same-origin `/api` under `/ui`, otherwise `REACT_APP_BACKEND_URL`.
- `frontend/package.json` proxies dev traffic to `http://localhost:8000`.

## Dashboard design source of truth
- Use `DESIGN.md` as the primary UI design reference when enhancing dashboard screens.
- For AI-assisted UI work, prefer the highest-tier model available in the environment (for example, GPT-5.3-Codex or Claude Sonnet 4.5 when available) and require design decisions (colors, typography, spacing, component treatment) to map back to `DESIGN.md`.
- Keep visual enhancements meaningful (improved information clarity) and visually polished while staying consistent with `DESIGN.md`.

## Developer workflow
- Backend dev: `cd backend && uvicorn server:app --host 0.0.0.0 --port 8000 --reload`
- Frontend dev: `cd frontend && npm start`
- Frontend check: `cd frontend && npm run build`
- `dev-setup.sh` starts the backend if needed and then launches the frontend.

## Tests to run when behavior changes
- Backend parsing/API changes: `backend/test_parsers.py`, `backend/test_api_smoke.py`, `backend/test_superchecker.py`, and related `backend/test_*` files.
- Frontend changes: `cd frontend && npm test -- --watchAll=false && npm run build`.
- Upload validation must preserve accepted formats: `.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz` and multipart field `file` (legacy `report` is also accepted).

## Conventions
- Report IDs are UUIDs.
- The upload cap is 10 GB and filenames must stay safe.
- If you change ingestion or report schema code, update the UI screens and server response shape together.

## Brain expansion playbook (from manual bash workflows)
- Add new checks as parser signals first, then score in `backend/superchecker.py`; avoid embedding heavy file scans directly in API endpoints.
- Keep check IDs/messages stable (existing tests assert recommendation content in `backend/test_superchecker.py` and API shapes in `backend/test_api_smoke.py`).
- Preferred signal families from support bundles:
  - Tracelog: `*memsql.log` patterns (`ETIMEDOUT`, `fsync is behind`, `Retry loop is stalling`, `from sync to async`, backup start/success/fail).
  - Resource: `sysctl_stdout`, `free_stdout`, `ulimit_stdout`, `df_stdout`, `top_stdout`, `*dmesg_stdout`, `*memsqldProcessLimits*`.
  - Info schema snapshots: `*show-variables.tsv`, `*show-status-extended.tsv`, `*show-cluster-status.tsv`, `*distributed_databases.tsv`, `*processlist.tsv`, `*mv-backup-history.tsv`.
- Use parser extraction patterns already present in `backend/parsers.py` (glob/TSV parsing + defensive fallbacks) and store normalized numeric counters, not raw shell output.
- For time-bucketed diagnostics (hour/minute counts), emit compact aggregates in parser output (for example `etimedout_per_hour`) and convert to user-facing recommendations in `superchecker`.
- Keep request/report payload sync across `backend/validators.py`, `backend/monitoring.py`, and `backend/storage.py` when adding new analysis fields.
- If a new recommendation appears in backend output, validate frontend rendering paths under report views in `frontend/src` (especially recommendation and overview screens).

## High-value checks to implement next
- Log timeframe detection per node (`first_log_entry`, `last_log_entry`) for quick report coverage confidence.
- Backup reliability summary from logs + `mv-backup-history` (`success_count`, `failure_count`, latest duration).
- Network/storage pressure indicators: counts of `ETIMEDOUT`, `fsync is behind`, and retry-stall events by hour.
- Memory pressure indicators: THP status, `vm.swappiness`, `vm.overcommit*`, `vm.max_map_count`, OOM-killer evidence in dmesg.
- Cluster layout sanity: partition counts by role/host from `show-cluster-status` and database totals from `distributed_databases`.
- Process health snapshot: non-sleeping queries and sleeping-open transactions from processlist files.

## Good reference files
- `README.md`, `DEPLOYMENT.md`, `PACKAGING.md`, `INTEGRATION.md`, and `AIRGAP_TEST_PROTOCOL.md`.
