# CLAUDE.md — S2 Report Sniffer

AI assistant reference for working in this codebase. Keep this file in sync when changing architecture, APIs, or conventions.

---

## What this project does

S2 Report Sniffer is a **local-first, offline diagnostic tool** for SingleStore support engineers. It parses `sdb-report` archives (`.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`, up to 10 GB), extracts and correlates logs/metrics/telemetry across all cluster nodes, scores findings by risk, and presents a dashboard.

**Core flow:** Upload archive → `server.py` validates & extracts → `parsers.py` walks the directory tree → `superchecker.py` scores findings → `storage.py` persists to SQLite → React UI renders dashboard.

---

## Monorepo layout

```
backend/            FastAPI server + all analysis logic
  server.py         HTTP API entrypoints, middleware, upload handling
  parsers.py        Archive extraction + normalization into report dict
  superchecker.py   Risk-scoring engine (30+ checks)
  storage.py        SQLite persistence via S2RS_DATA_DIR (~/.s2-report-sniffer)
  validators.py     Input sanitization and UUID validation
  monitoring.py     Structured alerting and audit logging
  glean_mcp.py      Glean MCP client for enterprise knowledge-base queries
  desktop_entry.py  Entry point when launched from Electron
  migrations/       Alembic SQLite migrations (alembic.ini at backend root)
  test_*.py         All backend tests live directly in backend/

frontend/           React 18 + Vite + TailwindCSS + shadcn/ui
  src/App.jsx       Router: / → ReportList, /report/:id/* → ReportDashboard
  src/pages/        ReportList.jsx, ReportDashboard.jsx
  src/components/   Feature components + ui/ (shadcn primitives)
  src/lib/api.js    Axios client — always uses /api relative base
  src/lib/utils.js  cn() and general helpers
  src/hooks/        useTheme.js, use-toast.js
  vite.config.js    Dev server port 3000, proxies /api → localhost:8000

desktop/            Electron wrapper (Node.js)
  main.js           Spawns bundled Python backend, opens BrowserWindow
  package.json      Electron dependencies

vscode-extension/   VS Code extension (TypeScript)
  src/extension.ts  Opens UI in SimpleBrowser or external browser

tools/              MCP hardening tooling (trae_mcp_hardening)
tests/              Integration/E2E tests (separate from backend unit tests)
scripts/            Utility scripts
docs/               Architecture and design docs
.githooks/pre-commit Blocks commits of secrets/keys/pem files
```

---

## Development workflow

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

- SQLite auto-provisions under `S2RS_DATA_DIR` (default: `~/.s2-report-sniffer`).
- Set `S2RS_DATA_DIR=./local_data` in dev to keep data local to the repo (excluded by `.gitignore`).
- No external database required — MongoDB/motor are in `requirements.txt` but unused at runtime.

### Frontend

```bash
cd frontend
npm install        # yarn also works (packageManager = yarn in package.json)
npm run dev        # Vite dev server on :3000, proxies /api → :8000
```

- `@` is aliased to `frontend/src/` in both Vite and `jsconfig.json`.
- Production build: `npm run build` → outputs to `frontend/build/` (served by FastAPI at `/ui/`).

### Full integrated dev

When `frontend/build/` exists, `GET /` on `:8000` redirects to `/ui/`. For live coding, run both servers simultaneously and hit `:3000`.

### Desktop (Electron)

```bash
./dev-setup.sh          # starts backend then frontend
./dev-setup.sh build:mac  # PyInstaller + Electron packager
```

---

## Running tests

### Backend (pytest)

```bash
cd backend && source .venv/bin/activate
python -m pytest -q                    # full suite
python -m pytest test_parsers.py test_api_smoke.py test_superchecker.py -v  # core gate
```

All test files live in `backend/` alongside source. `conftest.py` sets `S2RS_DISABLE_GZIP=1`.

### Frontend (vitest)

```bash
cd frontend
npm test           # vitest run (one-shot)
npm run test:watch # vitest in watch mode
npm run build      # also validates TypeScript and bundling
```

Test files colocated with source (`*.test.jsx`, `*.test.js`).

---

## CI gates (`.github/workflows/ci.yml`)

Three parallel jobs on every PR and push to `main`:

| Job | What runs |
|-----|-----------|
| `backend` | `pip install -r backend/requirements.txt` → `pytest -q` |
| `frontend` | `npm ci` → `npm run build` → `npm test` |
| `security` | `bandit -r backend -c bandit.yaml -ll` + `pip-audit` + `security_audit_gate.sh` |

A fourth workflow (`mcp-security.yml`) validates MCP hardening tooling.

---

## Architecture constraints

### Local-first / air-gapped

- **No data leaves the machine.** No telemetry, no crash reporting.
- All state is SQLite/file on disk. No network calls from backend except optional Glean MCP integration.
- Archive extraction is bounded: `MAX_DECOMPRESSED_BUDGET = 50 GB`. Individual JSON files have per-filename size caps in `parsers.py`.

### API routing

- Frontend always calls `/api/*` (relative). `api.js` detects if it's running at `/ui/` and keeps paths relative; otherwise falls back to `VITE_BACKEND_URL`.
- Backend exposes all routes under `APIRouter(prefix="/api")`, mounted on the `FastAPI` app.
- Docs at `/api/docs` (Swagger), `/api/redoc`.

### Report IDs

UUIDs (`[a-f0-9]{8}-...-[a-f0-9]{12}`). Validated by `validators.validate_report_id()` (raises `ValidationError` on failure) before any DB or filesystem access. The lower-level `is_valid_report_id()` returns a `(bool, str)` tuple and is used in helper contexts.

### Upload limits

- Max file size: 10 GB.
- Rate limit: 10 uploads/minute per IP (`_RateLimitMiddleware`).
- Accepted MIME/extensions: `.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`.
- Multipart field name: `file` (legacy alias `report` also accepted).

---

## Key modules deep dive

### `backend/parsers.py`

- `parse_report_archive_streaming(path)` — generator, fixed memory footprint, streams node data.
- Node directories matched by `NODE_DIR_PATTERN = r'^(.+?)-(MA|CA|LEAF|AGGREGATOR|MASTER)$'`.
- Defensive row caps per table (`MAX_MV_EVENTS_ROWS`, `MAX_BACKUP_HISTORY_ROWS`, etc.) — never remove these.
- Critical log pattern matching via `get_critical_log_patterns()` — lazy-initialized, regex-based.
- Signal source files: `*memsql.log`, `dmesg_stdout`, `sysctl_stdout`, `free_stdout`, `*show-variables.tsv`, `*processlist.tsv`, `*mv-backup-history.tsv`, and others.

### `backend/superchecker.py`

- `run_superchecker(report: dict) -> list` — returns scored finding list.
- `_CheckerState.run()` dispatches 30+ named check methods.
- Severity weights: `critical=85`, `warning=55`, `info=20`.
- Priority categories: `availability > data-loss > storage > memory > replication > ...`.
- **Never rename check IDs** — `test_superchecker.py` and `test_api_smoke.py` assert on specific check identifiers and recommendation content.

### `backend/storage.py`

- Uses SQLite with WAL mode and 30-second busy timeout.
- Data directory: `default_data_dir()` returns `~/.s2-report-sniffer` unless `S2RS_DATA_DIR` is set.
- Always run `_probe_sqlite_directory()` before first use in a new environment.

### `backend/validators.py`

- All external input passes through validators before touching the filesystem or DB.
- `ValidationResult.success(sanitized={...})` / `.failure([errors])` pattern.
- `FILENAME_SAFE_PATTERN = r'^[a-zA-Z0-9._-]+$'`.

### `backend/monitoring.py`

- Structured JSON alerts, anomaly detection, health monitoring.
- `AlertSeverity` and `AlertCategory` enums define the canonical vocabulary.
- Keep `monitoring.py` in sync with `validators.py` and `storage.py` when changing request/report payloads.

### `frontend/src/lib/api.js`

- Axios instance with 30s timeout.
- Debug interceptors activated only when `import.meta.env.DEV` is true.
- All API helpers are exported from this module — add new calls here, not inline in components. Key exports: `uploadReport`, `importReport`, `listReports`, `getReportStatus`, `getReportOverview`, `getReportNodes`, `getReportStorage`, `getReportQueries`, `getReportLogs`, `getReportRecommendations`, `getReportConfig`, `deleteReport`, plus Glean helpers (`getGleanConfig`, `saveGleanConfig`, `fetchGleanInsights`, `enrichFindings`).

---

## Adding new diagnostic checks

1. **Parse the signal** in `backend/parsers.py` — extract normalized numeric/string values from bundle files using existing glob/TSV patterns. Emit compact aggregates (e.g. `etimedout_per_hour`), not raw shell output.
2. **Score it** in `backend/superchecker.py` — add a `_check_*` method on `_CheckerState` and call it from `run()`. Use stable check IDs.
3. **Surface it** in the frontend — verify the finding renders in `Recommendations.jsx` and/or `ClusterOverview.jsx`.
4. **Test it** — add cases to `backend/test_superchecker.py` and `backend/test_api_smoke.py`.
5. **Keep payloads in sync** — if the report dict gains new keys, update `validators.py`, `monitoring.py`, and `storage.py`.

---

## Frontend conventions

- **Components:** shadcn/ui primitives live in `src/components/ui/` — do not modify them manually, use the shadcn CLI pattern. Feature components live directly in `src/components/`.
- **Styling:** Tailwind utility classes. Design system reference in `DESIGN.md` (VoltAgent-inspired dark theme: `#050507` canvas, `#00d992` accent green, warm-neutral borders).
- **State:** No global state manager. Local `useState`/`useEffect` in pages, shared via props or context where needed.
- **Routing:** React Router v7. Two top-level routes only — `ReportList` and `ReportDashboard`.
- **Error handling:** `ErrorBoundary.jsx` wraps the router. Toast notifications via `sonner`.

---

## Security conventions

- **Pre-commit hook** (`.githooks/pre-commit`) blocks `.trae-secrets.sh`, `mcp.json`, `.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`. Run `git config core.hooksPath .githooks` after cloning.
- **Archive extraction:** All extracted paths are validated against a realpath boundary — no path traversal. Zip bomb budget enforced at the byte level.
- **HTML output:** Use `html.escape()` before embedding any report content in HTML responses.
- **Import paths:** Only allowlisted import paths are accepted for dynamic imports.
- **Bandit config:** `bandit.yaml` suppresses B110 (intentional bare except in lossy parsers), B603 (guarded subprocess), B404 (tarfile with per-member validation). Do not add new suppressions without review.
- **SQL:** All queries use parameterized statements — no string interpolation.

---

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `S2RS_DATA_DIR` | `~/.s2-report-sniffer` | SQLite and file storage root |
| `S2RS_DISABLE_GZIP` | unset | Set to `1` to disable GZip middleware (used in tests) |
| `S2RS_LOG_ROUTES` | unset | Set to `1` to log all registered routes at startup |
| `VITE_BACKEND_URL` | `` (empty) | Frontend: override backend origin for non-integrated deployments |

---

## Alembic migrations

```bash
cd backend && source .venv/bin/activate
alembic upgrade head          # apply all migrations
python migrations_runner.py   # programmatic runner used by desktop entry
```

Migration scripts live in `backend/migrations/`. When adding a new migration:
1. Create `backend/migrations/00N_description.py`.
2. Test upgrade and downgrade paths.
3. Update `backend/rollback_runner.py` if the rollback logic changes.

---

## Desktop (Electron) specifics

- `desktop/main.js` spawns the bundled Python backend on a free port (auto-detected), waits for health check, then opens a `BrowserWindow` pointed at `http://127.0.0.1:{port}/ui/`.
- Logs rotate at 5000 lines under `{userData}/logs/s2rs-startup.log`.
- `desktop/fix-permissions.js` — run once after PyInstaller packaging to fix executable bits.
- PyInstaller spec: `s2rs-backend.spec` at repo root (also symlinked into `backend/`).

---

## VS Code extension

- Command `s2ReportSniffer.open` — opens the UI in SimpleBrowser.
- Command `s2ReportSniffer.openExternal` — opens in the system browser.
- `backendUrl` setting defaults to `http://127.0.0.1:8000/ui/`.
- Built with `npm run compile` in `vscode-extension/`. Output goes to `vscode-extension/out/`.

---

## What NOT to do

- Do not embed file scans or heavy logic directly in API endpoint handlers — put analysis in `parsers.py` and scoring in `superchecker.py`.
- Do not bypass the row/byte caps in `parsers.py` — they prevent OOM on multi-GB bundles.
- Do not rename existing superchecker check IDs — tests assert on them.
- Do not push secrets, `.env` files, or PEM keys — the pre-commit hook will block it.
- Do not use `git push --force` on `main`.
- Do not add `try/except/pass` broadly — only in lossy-parser sections where graceful degradation is intentional (Bandit B110 suppression is narrowly scoped).

---

## Reference documents

| File | Contents |
|------|----------|
| `DESIGN.md` | UI design system — source of truth for colors, typography, spacing |
| `AGENTS.md` | Shorter AI-assistant quick-reference (keep in sync with this file) |
| `DEPLOYMENT.md` | Production deployment guide |
| `PACKAGING.md` | Electron + PyInstaller packaging guide |
| `INTEGRATION.md` | Glean and external integrations |
| `AIRGAP_TEST_PROTOCOL.md` | Air-gapped environment test protocol |
| `SECURITY_REVIEW.md` | Security review findings and mitigations |
| `AUDIT_REPORT.md` | Dependency and code audit |
| `PRODUCT_ROADMAP.md` | Feature backlog and phase planning |
| `LOCAL_FIRST_ARCHITECTURE.md` | Deep-dive on local-first storage design |
