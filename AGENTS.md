# AGENTS.md

## Project snapshot
- `S2 Report Sniffer` analyzes offline SingleStore support bundles and turns them into report dashboards, recommendations, and exports.
- Core flow: `backend/server.py` validates uploads, extracts archives, calls `backend/parsers.py`, scores with `backend/superchecker.py`, and persists via `backend/storage.py`.
- Keep `backend/validators.py`, `backend/monitoring.py`, and `backend/storage.py` in sync when changing request or report payloads.

## Architecture to keep in mind
- Local-first. `desktop/main.js` + `backend/desktop_entry.py` launch a bundled FastAPI backend on `127.0.0.1` and load the React UI from `/ui/`.
- When `frontend/build/` exists, `GET /` redirects to `/ui/` so UI and API share one origin.
- Persistence is SQLite/file-based via `S2RS_DATA_DIR` (default `~/.s2-report-sniffer`; use `S2RS_DATA_DIR=./local_data` in dev). Do not assume MongoDB/cloud storage — it is in `requirements.txt` but unused at runtime.
- No data leaves the machine — no telemetry, no crash reporting, no external calls (except optional Glean MCP integration).

## Frontend/backend integration
- React router lives in `frontend/src/App.jsx`: two top-level routes — `/` (ReportList) and `/report/:reportId/*` (ReportDashboard).
- `frontend/src/lib/api.js` uses same-origin `/api` under `/ui`, otherwise `import.meta.env.VITE_BACKEND_URL` (Vite). `@` is aliased to `frontend/src/`.
- `frontend/vite.config.js` proxies dev traffic from Vite dev server (port 3000) to `http://localhost:8000` for `/api`.
- Add new API calls in `frontend/src/lib/api.js`, not inline in components. shadcn/ui primitives in `frontend/src/components/ui/` — do not modify manually.

## Developer workflow
- Backend dev:
  ```bash
  cd backend
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt -r requirements-dev.txt
  S2RS_DATA_DIR=./local_data uvicorn server:app --host 127.0.0.1 --port 8000 --reload
  ```
- Frontend dev: `cd frontend && npm install && npm run dev` (Vite on port 3000). `yarn` also works (`packageManager` set in `package.json`).
- Integrated dev: `./dev-setup.sh` starts backend then frontend. Note: it activates `venv/` not `.venv/` — adjust if your venv is named differently.
- Frontend check: `cd frontend && npm run build && npm test` (build also validates TS/bundling).

## Tests and verification
- Backend core gate: `cd backend && python -m pytest test_parsers.py test_api_smoke.py test_superchecker.py -v`
- Backend full suite: `cd backend && python -m pytest -q` (19 `test_*.py` files live alongside source in `backend/`).
- `backend/conftest.py` auto-sets `S2RS_DISABLE_GZIP=1` for tests — no need to set it manually.
- Single test: `python -m pytest test_parsers.py::TestName -v`.
- Triage bucket mutual-exclusivity tests live in `backend/test_server_endpoints.py` (`TestReportTriage`), not `test_api_smoke.py`.
- Upload validation must preserve accepted formats: `.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz` and multipart field `file` (legacy `report` also accepted).

## CI gates (`.github/workflows/ci.yml`)
Three parallel jobs on every PR and push to `main`:
- `backend`: Python 3.11, `pip install -r requirements.txt -r requirements-dev.txt`, `pytest -q` in `backend/`.
- `frontend`: Node 20, `npm ci` → `npm run build` → `npm test`.
- `security`: `bandit -r backend -c bandit.yaml -ll` + `pip-audit` + `./security_audit_gate.sh`.

## Conventions
- Report IDs are UUIDs. `validators.validate_report_id()` raises `ValidationError` on failure — use this in all endpoint handlers before touching the filesystem or DB.
- Upload cap: 10 GB. Rate limit: 10 uploads/minute per IP.
- Python 3.11 native type syntax: use `list[str]`, `str | None` — do **not** import `List`, `Optional` from `typing`.
- All external input passes through `validators.py`. `ValidationResult.success(sanitized=...)` / `.failure([errors])` pattern.
- No `try/except/pass` broadly — only in lossy-parser sections where graceful degradation is intentional (Bandit B110 suppression is narrowly scoped; do not add new suppressions without review).
- SQL: always use parameterized statements — no string interpolation.
- Pre-commit hook (`.githooks/pre-commit`) blocks `.trae-secrets.sh`, `mcp.json`, `.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`. Run `git config core.hooksPath .githooks` after cloning.

## Adding diagnostic checks
1. Parse the signal in `backend/parsers.py` — emit compact aggregates (e.g. `etimedout_per_hour`), not raw shell output. Keep row/byte caps intact (they prevent OOM on multi-GB bundles).
2. Score it in `backend/superchecker.py` — add a `_check_*` method on `_CheckerState` and call from `run()`.
3. Surface in frontend — verify rendering in `Recommendations.jsx` and/or `ClusterOverview.jsx`.
4. Test — add cases to `backend/test_superchecker.py` and `backend/test_api_smoke.py`.
5. Keep report dict keys in sync across `validators.py`, `monitoring.py`, `storage.py`.
- **Never rename existing superchecker check IDs** — `test_superchecker.py` and `test_api_smoke.py` assert on specific check identifiers and recommendation content.
- Signal source families: tracelog (`*memsql.log` patterns like `ETIMEDOUT`, `fsync is behind`, backup start/success/fail), resource (`sysctl_stdout`, `free_stdout`, `ulimit_stdout`, `df_stdout`, `top_stdout`, `*dmesg_stdout`), info-schema TSVs (`*show-variables.tsv`, `*show-status-extended.tsv`, `*show-cluster-status.tsv`, `*processlist.tsv`, `*mv-backup-history.tsv`).

## Git workflow (learned preferences)
- Create a feature branch before committing when starting from `main`; do not commit directly on `main`.
- Never stage or commit files under `.cursor/` (it is in `.gitignore`).
- Never commit customer investigation logs or large sample support-bundle archives; keep them local and gitignored.
- Stage explicit file paths with `git add <files…>`; avoid `git add -A` when untracked noise is present.
- Keep commits scoped to one logical change; do not mix unrelated fixes.
- Do not push to remote unless explicitly asked. Do not `git push --force` on `main`.
- Use the `gh` CLI for GitHub tasks (PRs, branch delete, checks, releases).

## Workspace facts
- Active feature work for topology map, incident clusters, desktop packaging, and query/memory/async-pressure diagnostics lives on branch `feat/topology-incident-clusters-desktop-packaging` (open PR against `main`, not yet merged).
- Unified sprint design (compare UI, richer exports, desktop hardening after foundation merge) lives at `docs/superpowers/specs/2026-07-03-unified-sprint-design.md`.
- `scripts/create-feature-pr.sh` and `scripts/close-stale-cursor-prs.sh` automate feature PR creation and closing superseded `cursor/*` PRs; both require `brew install gh` and `gh auth login`.
- Remote GitHub operations (push, branch delete, PR create/close) may fail in the agent sandbox without local git/gh credentials; run authenticated commands in the user's terminal when needed.
- Python virtualenv may exist at repo root `.venv` and/or `backend/.venv`; use whichever is present when running pytest.
- `get_report_triage` bucket assignment is mutually exclusive: priority 1 → `act_now`, elif `quick_win` → `quick_wins`, elif priority 2 → `act_soon`, else `backlog` (priority 1 wins over `quick_win`).

## Reference docs
- `CLAUDE.md` — comprehensive AI assistant reference (architecture, API shapes, module deep dives). Keep in sync when changing architecture.
- `DESIGN.md` — UI design system (colors, typography, spacing) — source of truth for dashboard visual work.
- `DEPLOYMENT.md`, `PACKAGING.md`, `INTEGRATION.md`, `AIRGAP_TEST_PROTOCOL.md`, `SECURITY_REVIEW.md`, `PRODUCT_ROADMAP.md` — topic-specific deep dives.