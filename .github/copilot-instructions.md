# Copilot Instructions for S2 Report Sniffer

## Build, test, and lint commands

### Backend (FastAPI / pytest)
```bash
# install deps
cd backend && python -m pip install -r requirements.txt -r requirements-dev.txt

# run full backend test gate (same as CI) — ~669 tests
cd backend && python -m pytest -q

# run core parser/API/scoring tests
cd backend && python -m pytest test_parsers.py test_api_smoke.py test_superchecker.py -v

# run a single backend test file (no venv activation needed)
cd backend && .venv/bin/python -m pytest test_log_search.py -v

# run a single test by name
cd backend && .venv/bin/python -m pytest test_superchecker.py -k "test_runaway_queries" -v
```

### Frontend (Vite / Vitest)
```bash
# install deps
cd frontend && npm ci

# CI gate: typecheck + build + test
cd frontend && npm run typecheck && npm run build && npm test

# run a single frontend test file
cd frontend && npx vitest run src/components/Recommendations.test.jsx

# watch mode
cd frontend && npm run test:watch
```

### Lint / quality / security tools
```bash
# CI flake8 gate (syntax/undefined-name checks only)
cd backend && python -m flake8 --select=F821,F822,F823,E9 --exclude=.venv,__pycache__ .

# additional dev tools (in requirements-dev.txt — no repo-wide lint script)
cd backend && black --check <file_or_dir>
cd backend && mypy <file_or_dir>
cd backend && isort --check-only <file_or_dir>

# security checks used in CI
bandit -r backend -c bandit.yaml -ll
pip-audit -r backend/requirements.txt
```

### Desktop build (macOS DMG)
```bash
PYTHON_BIN=python3.11 bash scripts/build-desktop.sh
# output: dist/installers/S2 Report Sniffer-1.0.0-arm64.dmg
```

## High-level architecture

- **Local-first desktop architecture:** `desktop/main.js` launches a bundled Python backend (`backend/desktop_entry.py`) on `127.0.0.1`, then loads the React app from FastAPI at `/ui/`. No telemetry/crash reporting; data stays local by default.
- **Core analysis pipeline:** upload/import → `backend/server.py` validates & extracts → `backend/parsers.py` walks the archive tree and normalizes into a report dict → `backend/superchecker.py` scores 30+ checks → `backend/storage.py` persists to SQLite + files under `S2RS_DATA_DIR` → React UI renders dashboard.
- **Frontend/backend coupling:** React router (`frontend/src/App.jsx`) has two top-level routes: `/` (ReportList) and `/report/:reportId/*` (ReportDashboard). API calls are centralized in `frontend/src/lib/api.ts` — add new calls there, not inline in components. In integrated mode it uses same-origin `/api`; Vite dev mode proxies `/api` to `http://localhost:8000` (`frontend/vite.config.ts`, dev server on port 3000).
- **Serving model:** when `frontend/build/` exists, backend serves UI/static assets and redirects `GET /` to `/ui/`, so UI and API share one origin in packaged/prod runs.
- **`@` path alias:** `@/` maps to `frontend/src/` in both Vite and `jsconfig.json`/`tsconfig.json`.

## Key repository conventions

### Storage schema changes — 3-place allowlist (critical gotcha)
When adding a new column to the `reports` table in `backend/storage.py`, you must update **all three** places or the column silently won't read/write:
1. `_init_db()` — add `ALTER TABLE reports ADD COLUMN <name> TYPE` (additive migration pattern).
2. `update_report_fields()` — add the column to the `allowed` set, else writes are silently dropped.
3. `get_report_fields()` — add the column to the `allowed` list, else `fields=["<name>"]` selects only `id` and returns `None` for your column.

The payload JSON (`report.json`) is separate from these SQL columns — overview/nodes/etc. go through `write_report_payload`, not `update_report_fields`.

### Adding new diagnostic checks
1. **Parse the signal** in `backend/parsers.py` — extract normalized numeric/string values from bundle files. Emit compact aggregates (e.g. `etimedout_per_hour`), not raw shell output.
2. **Score it** in `backend/superchecker.py` — add a `_check_*` method on `_CheckerState`, call from `run()`. Use stable check IDs.
3. **Ground it** in `backend/grounding.py` — add a `GROUNDING` entry for the new `checker_id` declaring `basis` (`documented`/`toolbox-default`/`heuristic`/`observed`), a verified `source` URL, and a `criterion` sentence. Never invent doc URLs — leave `source=""` if unverified. Label rule-of-thumb thresholds as `heuristic`, not `documented`.
4. **Test it** — add cases to `backend/test_superchecker.py` and `backend/test_api_smoke.py`.
5. **Keep payloads in sync** — if the report dict gains new keys, update `validators.py`, `monitoring.py`, and `storage.py`.

### Never rename superchecker check IDs
`test_superchecker.py` and `test_api_smoke.py` assert on specific check identifiers and recommendation content. Renaming a check ID will break tests silently.

### Frontend TypeScript + JS interop
`tsconfig.json` has `allowJs: false` — `.js` files are not type-checked but can still be imported. When a `.js` module is imported from `.ts`/`.tsx`, TypeScript will error (TS7016) unless a `.d.ts` declaration file exists alongside it. Add `nextSteps.d.ts`-style declarations for any JS modules imported by TS files.

### Input validation
- All external input passes through `backend/validators.py` before touching the filesystem or DB. Use `ValidationResult.success(sanitized=...)` / `.failure([errors])` pattern.
- Call `validators.validate_report_id()` in all endpoint handlers before any storage/filesystem access (raises `ValidationError` on failure).
- SQL: always use parameterized statements — no string interpolation.

### PyInstaller spec — runtime source files
When adding a new backend Python module that is imported at runtime (especially via dynamic import), add it to `_RUNTIME_SOURCE_FILES` in `backend/s2rs-backend.spec`. Otherwise the PyInstaller desktop build will fail to find the module. Also add it to `hiddenimports` if it's dynamically imported.

### Test isolation — importlib.reload gotcha
`test_shutdown.py` calls `importlib.reload(server)` at module level, which replaces `server.store` with a new object. Tests in other files that capture `store` at module level (e.g. `from server import store`) will hold a stale reference. Always use `from server import store` **inside** test methods/functions, not at module level, to get the current `server.store`.

### Environment variables
| Variable | Default | Purpose |
|----------|---------|---------|
| `S2RS_DATA_DIR` | `~/.s2-report-sniffer` | SQLite and file storage root (cwd-relative — `./local_data` from `backend/` writes to `backend/local_data`) |
| `S2RS_DISABLE_GZIP` | unset | Set to `1` to disable GZip middleware (tests set this in `conftest.py`) |
| `S2RS_MAX_EXTRACTED_KEEP_GB` | `2` | Max extracted bundle size to keep on disk for raw log search (`0` disables) |
| `S2RS_ENABLE_CLOUD_EXTENSIONS` | off | Enable optional Hostinger routes |
| `VITE_BACKEND_URL` | `` | Frontend: override backend origin for non-integrated deployments |

### Other conventions
- **Python type syntax:** use `list[str]`, `str | None` — do not import `List`, `Optional` from `typing`.
- **Upload constraints:** max size 10 GB, accepted formats `.zip/.tar.gz/.tgz/.tar/.gz`, multipart field `file` (legacy `report` still accepted), rate limit 10 uploads/minute per IP.
- **Row/byte caps in `parsers.py`:** never remove defensive caps (`MAX_MV_EVENTS_ROWS`, `MAX_BACKUP_HISTORY_ROWS`, etc.) — they prevent OOM on multi-GB bundles.
- **No `try/except/pass`** broadly — only in lossy-parser sections where graceful degradation is intentional (Bandit B110 suppression is narrowly scoped).
- **Pre-commit hook** (`.githooks/pre-commit`) blocks `.env*`, `*.pem`, `*.key`, `mcp.json`, `.trae-secrets.sh`. Run `git config core.hooksPath .githooks` after cloning.
- **Bandit suppressions** (`bandit.yaml`): B110 (intentional bare except in lossy parsers), B603 (guarded subprocess), B404 (tarfile with per-member validation). Do not add new suppressions without review.
- **Do not commit** `.build/` PyInstaller artifacts, `.cursor/`, customer bundles, or `.env` files.
