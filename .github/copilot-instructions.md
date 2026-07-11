# Copilot Instructions for S2 Report Sniffer

## Build, test, and lint commands

### Backend (FastAPI / pytest)
```bash
# install deps
cd backend && python -m pip install -r requirements.txt -r requirements-dev.txt

# run full backend test gate (same as CI)
cd backend && python -m pytest -q

# run core parser/API/scoring tests
cd backend && python -m pytest test_parsers.py test_api_smoke.py test_superchecker.py -v

# run a single backend test file
cd backend && .venv/bin/python -m pytest test_log_search.py -v
```

### Frontend (Vite / Vitest)
```bash
# install deps
cd frontend && npm ci

# build + test (same as CI)
cd frontend && npm run build && npm test

# run a single frontend test file
cd frontend && npm test -- src/<path-to-test-file>.test.jsx
```

### Lint / quality / security tools in use
```bash
# backend style/type checks (no repo-wide lint script)
cd backend && flake8 <file_or_dir>
cd backend && black --check <file_or_dir>
cd backend && mypy <file_or_dir>
cd backend && isort --check-only <file_or_dir>

# security checks used in CI
bandit -r backend -c bandit.yaml -ll
pip-audit -r backend/requirements.txt
./security_audit_gate.sh
```

## High-level architecture

- **Local-first desktop architecture:** `desktop/main.js` launches a bundled Python backend (`backend/desktop_entry.py`), then loads the React app from FastAPI at `/ui/`. No telemetry/crash reporting; data stays local by default.
- **Core analysis pipeline:** upload/import request enters `backend/server.py` → archive/directory parsing in `backend/parsers.py` → findings scored in `backend/superchecker.py` → report metadata/payload persisted by `backend/storage.py` (SQLite + files under `S2RS_DATA_DIR`).
- **Frontend/backend coupling:** React router has two top-level routes in `frontend/src/App.jsx` (`/` and `/report/:reportId/*`). API calls are centralized in `frontend/src/lib/api.js`; in integrated mode it uses same-origin `/api`, while Vite dev mode proxies `/api` to `http://localhost:8000` (`frontend/vite.config.js`).
- **Serving model:** when `frontend/build/` exists, backend serves UI/static assets and redirects `GET /` to `/ui/`, so UI and API share one origin in packaged/prod runs.

## Key repository conventions

- **Validate report IDs at endpoint boundaries:** call `validators.validate_report_id()` before any storage/filesystem access in report-scoped API handlers.
- **All external input goes through validators:** use validator helpers and `ValidationResult.success(...)/failure(...)` patterns from `backend/validators.py`.
- **Storage schema change rule (critical):** when adding a `reports` SQL column in `backend/storage.py`, update all three places:
  1. `_init_db()` migration/`ALTER TABLE`
  2. `update_report_fields()` allowlist
  3. `get_report_fields()` allowlist
- **Add diagnostics in parser+checker layers, not endpoints:** extract normalized signals in `parsers.py`, then score/recommend in `superchecker.py`.
- **Keep check IDs stable:** existing tests assert specific check identifiers and recommendation text.
- **Frontend API access pattern:** add/modify API calls in `frontend/src/lib/api.js`; avoid inline request logic inside components.
- **Local storage assumptions:** SQLite/file storage via `S2RS_DATA_DIR` is the default architecture; do not assume remote DB/cloud services.
- **Upload constraints that must remain compatible:** max size 10 GB, accepted formats `.zip/.tar.gz/.tgz/.tar/.gz`, multipart field `file` (legacy `report` still accepted).
