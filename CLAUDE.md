# CLAUDE.md — S2 Report Sniffer

AI assistant reference for working in this codebase. Keep this file in sync when changing architecture, APIs, or conventions.

---

## What this project does

S2 Report Sniffer is a **local-first, offline diagnostic tool** for SingleStore support engineers. It parses `sdb-report` archives (`.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`, up to 10 GB), extracts and correlates logs/metrics/telemetry across all cluster nodes, scores findings by risk, and presents a dashboard.

**Core flow:** Upload archive → `server.py` validates & extracts → `parsers.py` walks the directory tree → `superchecker.py` scores findings → `storage.py` persists to SQLite → React UI renders dashboard.

**Important: upload is asynchronous.** The upload endpoint returns as soon as the report is *accepted*; parsing/scoring then continues in a tracked `asyncio` background task (`server.py::_background_tasks` / `_run_analysis_job`). The SQLite row sits in a `processing` state until the job finishes. On desktop, `processing_lifecycle.py` installs restart/cancellation recovery guards so a row is never stuck in `processing` forever (installed by `desktop_entry.py` before uvicorn accepts requests). Frontend polls `getReportStatus` to watch this.

---

## Monorepo layout

```
backend/            FastAPI server + all analysis logic
  server.py         HTTP API entrypoints, middleware, upload handling
  parsers.py        Archive extraction + normalization into report dict
  superchecker.py   Risk-scoring engine (30+ checks)
  grounding.py      Per-checker grounding registry (basis + verified doc source)
  storage.py        SQLite persistence via S2RS_DATA_DIR (~/.s2-report-sniffer)
  validators.py     Input sanitization and UUID validation
  monitoring.py     Structured alerting and audit logging
  investigation.py  Incident clusters, log_context enrichment, Glean packet builder
  investigation_flows.py  Step-by-step investigation flow templates for common issue types
  archive_security.py     Shared archive admission + per-member validation policy (NO extraction code — every extractor validates members here before touching the FS)
  api_models.py     Typed Pydantic response contracts; tolerant of extra fields from older saved reports
  product_features.py     Comparison, exports, anonymization, privacy, local telemetry — deterministic, local-only, imports no network client
  query_tracer.py   Offline query-trace correlation: joins processlist/MV_BLOCKED_QUERIES/MV_QUERIES/query_patterns into a confidence-scored stage graph
  disk_reclamation.py     Disk overhead buckets + blobs-vs-referenced delta accounting
  processing_lifecycle.py Restart/cancellation recovery guards for async report-processing tasks (installed by desktop_entry.py)
  partition_audit.py      CLI helper to count master partitions per (database, host) from showClusterStatus.json
  s3_client.py      Optional boto3 S3 client — only used behind S2RS_ENABLE_CLOUD_EXTENSIONS (boto3 is NOT in requirements.txt)
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
  preload.js        contextBridge for Glean handoff IPC
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
- No external database required — everything is SQLite + files on disk. (A couple of `motor`/`pymongo` imports linger in `migrations_runner.py`/`rollback_runner.py` but neither is in `requirements.txt`; they are dead at runtime.) `s3_client.py` imports `boto3`, also not pinned — it only loads behind the optional cloud-extensions path.

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
python -m pytest test_superchecker.py::test_name -v   # single test by node id
python -m flake8 --select=F821,F822,F823,E9 --exclude=.venv,__pycache__ .   # CI lint gate (error-only)
```

All test files live in `backend/` alongside source. `conftest.py` sets `S2RS_DISABLE_GZIP=1`. Dev-only tooling (`black`, `flake8`, `mypy`, `isort`, `hypothesis`) is in `requirements-dev.txt`.

### Frontend (vitest)

```bash
cd frontend
npm test           # vitest run (one-shot)
npm test -- src/components/Recommendations.test.jsx   # single test file
npm test -- -t "some test name"                       # single test by name
npm run test:watch # vitest in watch mode
npm run typecheck  # tsc --noEmit (runs in CI frontend job)
npm run build      # vite build; bundling validation
```

Test files colocated with source (`*.test.jsx`, `*.test.tsx`).

---

## CI gates (`.github/workflows/ci.yml`)

Three parallel jobs on every PR and push to `main`:

| Job | What runs |
|-----|-----------|
| `backend` | `pip install -r backend/requirements.txt -r backend/requirements-dev.txt` → `pytest -q` |
| `frontend` | `npm ci` → `npm run build` → `npm test` |
| `security` | `bandit -r backend -c bandit.yaml -ll` + `pip-audit` + `security_audit_gate.sh` |

A fourth workflow (`mcp-security.yml`) validates MCP hardening tooling.

---

## Architecture constraints

### Local-first / air-gapped

- **No data leaves the machine.** No telemetry, no crash reporting.
- All state is SQLite/file on disk. No network calls from the backend for RCA — Analyze in Glean is a local packet handoff. Optional Hostinger remains behind cloud-extensions.
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
- Every finding carries a `grounding` block (`basis`, `source`, `criterion`) attached in `_add()` via `grounding.get_grounding(checker_id)`. Placeholder/generic doc links are replaced with the checker's verified `source` through `grounding.resolve_doc_link()`.

### `backend/grounding.py`

- Central registry mapping each `checker_id` → `{basis, source, criterion}`. `basis` ∈ `documented` / `toolbox-default` / `heuristic` / `observed`.
- Documented thresholds are grounded in verified SingleStore docs (System Requirements & Recommendations, maximum_memory, replication/durability concepts, backup & restore). Heuristics (query/tx/lag operational cutoffs) are explicitly labeled — never presented as documented requirements.
- `source` URLs are all verified live. **Do not invent URLs** — leave `source=""` when none is confirmed.

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
- All API helpers are exported from this module — add new calls here, not inline in components. Key exports: `uploadReport`, `importReport`, `listReports`, `getReportStatus`, `getReportOverview`, `getReportNodes`, `getReportStorage`, `getReportQueries`, `getReportLogs`, `getReportRecommendations`, `getReportConfig`, `deleteReport`, `getGleanPacket`.

---

## Adding new diagnostic checks

1. **Parse the signal** in `backend/parsers.py` — extract normalized numeric/string values from bundle files using existing glob/TSV patterns. Emit compact aggregates (e.g. `etimedout_per_hour`), not raw shell output.
2. **Score it** in `backend/superchecker.py` — add a `_check_*` method on `_CheckerState` and call it from `run()`. Use stable check IDs.
3. **Ground it** in `backend/grounding.py` — add a `GROUNDING` entry for the new `checker_id` declaring its `basis` (`documented` / `toolbox-default` / `heuristic` / `observed`), a verified `source` URL, and a `criterion` sentence. Every finding carries this via `_add()`; nothing should be arbitrary. Label rule-of-thumb thresholds as `heuristic` — do **not** dress them up as documented. Never invent doc URLs; leave `source=""` if none is verified.
4. **Surface it** in the frontend — verify the finding renders in `Recommendations.jsx` (which now shows the grounding **Basis** chip + criterion) and/or `ClusterOverview.jsx`.
5. **Test it** — add cases to `backend/test_superchecker.py` and `backend/test_api_smoke.py`.
6. **Keep payloads in sync** — if the report dict gains new keys, update `validators.py`, `monitoring.py`, and `storage.py`.

---

## Frontend conventions

- **Components:** shadcn/ui primitives live in `src/components/ui/` — do not modify them manually, use the shadcn CLI pattern. Feature components live directly in `src/components/`.
- **Language:** The codebase is mid-migration from JSX to TypeScript — newer panels are `.tsx` (e.g. `ClusterOverview.tsx`, `QueryTracerPanel.tsx`, `MemoryUtilizationPanel.tsx`) while older components remain `.jsx`. Write new components in TypeScript, run `npm run typecheck`, and note `tsconfig.strict-next.json` is the incremental-strict migration target. A few components ship a hand-written `.d.ts` alongside a `.jsx` (e.g. `ClusterStatePanel.d.ts`).
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
| `S2RS_ENABLE_CLOUD_EXTENSIONS` | off | Enable optional Hostinger routes |
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
- `desktop/preload.js` exposes `window.s2rsDesktop.gleanHandoff` for Analyze in Glean (save packet, copy prompt, open Glean.app).
- Desktop backend spawn may still set `S2RS_ENABLE_CLOUD_EXTENSIONS=1` for optional Hostinger; Glean handoff does not require it.
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
| `INTEGRATION.md` | Glean handoff and external integrations |
| `docs/ai-rca-design.md` | Analyze in Glean incident-packet design |
| `AIRGAP_TEST_PROTOCOL.md` | Air-gapped environment test protocol |
| `SECURITY_REVIEW.md` | Security review findings and mitigations |
| `AUDIT_REPORT.md` | Dependency and code audit |
| `PRODUCT_ROADMAP.md` | Feature backlog and phase planning |
| `LOCAL_FIRST_ARCHITECTURE.md` | Deep-dive on local-first storage design |

## gstack (recommended)

This project uses [gstack](https://github.com/garrytan/gstack) for AI-assisted workflows.
Install it for the best experience:

```bash
git clone --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
cd ~/.claude/skills/gstack && ./setup --team
```

Skills like /qa, /ship, /review, /investigate, and /browse become available after install.
Use /browse for all web browsing. Use ~/.claude/skills/gstack/... for gstack file paths.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
