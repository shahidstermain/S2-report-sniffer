# Pre-Production Deployment Verification Report

**Date:** 2026-07-12  
**Project:** S2 Report Sniffer  
**Branch:** `cursor/prod-readiness-test-d534`  
**Architecture:** Local-first (SQLite / `S2RS_DATA_DIR`) — MongoDB is **not** required at runtime  
**Recommendation:** **GO FOR DEPLOYMENT** (with residual tech-debt notes below)

---

## Gate summary

| Gate | Command | Result |
|------|---------|--------|
| Backend tests | `cd backend && ../.venv/bin/python -m pytest -q` | **PASS** — 450 passed, 2 skipped |
| Backend flake8 (CI select) | `flake8 --select=F821,F822,F823,E9` | **PASS** |
| Frontend build | `cd frontend && npm run build` | **PASS** |
| Frontend typecheck | `npm run typecheck` | **PASS** |
| Frontend tests | `npm test` | **PASS** — 16 tests / 4 files |
| Bandit (HIGH/MEDIUM) | `bandit -r backend -c bandit.yaml -ll` | **PASS** — 0 High/Medium |
| pip-audit | `pip-audit -r backend/requirements.txt` | **PASS** — no known vulns |
| Frontend audit gate | `./security_audit_gate.sh` | **PASS** — 0 High/Critical |
| Integrated prod smoke | UI + API on `:8000` with built assets | **PASS** |

---

## 1. Code testing & build verification

**Status: PASS**

### Backend
- Full suite: **450 passed**, 2 skipped, ~1.5s.
- Core files exercised: `test_parsers.py`, `test_api_smoke.py`, `test_superchecker.py`, `test_archive_security.py`, `test_server_endpoints.py`, `test_upload_success.py`, `test_zip_upload_edge_cases.py`.
- Initial run hit **7 upload failures** caused by a pre-existing root-owned `/tmp/sdb_uploads` (PermissionError → HTTP 500). Fixed by hardening upload staging in `backend/server.py` (`_ensure_upload_dir()` falls back to a private temp dir when the preferred path is not writable). Retest: **all green**.

### Frontend
- Production Vite build succeeded (main JS ~389 KB / ~103 KB gzip; CSS ~83 KB / ~16 KB gzip).
- `tsc --noEmit` clean.
- Vitest: QueryPatternsPanel, MemoryUtilizationPanel, ClusterTopologyMap, ReportList — all passed.

---

## 2. Security scans & dependency audit

**Status: PASS**

- **Bandit:** 0 High / 0 Medium findings in first-party backend code (`bandit.yaml` applied).
- **pip-audit:** no known vulnerabilities in `backend/requirements.txt`.
- **npm audit gate:** 0 High / 0 Critical in production frontend dependencies.
- **CSP (live header):** `script-src 'self'` (no `unsafe-inline` on scripts); `style-src 'self' 'unsafe-inline'`; `connect-src 'self'`; `frame-ancestors 'none'`.
- **Archive path traversal:** realpath + `is_relative_to` validation remains in `parsers.py` (covered by `test_archive_security.py`).

### Residual (non-blocking)
| ID | Item | Notes |
|----|------|-------|
| S-04 | Error message leakage | `S2RS_ENVIRONMENT=production` sanitizes upload **500** responses. Some **400** archive validation messages may still include exception text. Prefer keeping `S2RS_ENVIRONMENT=production` in prod. |
| Docs drift | `CORRECTNESS_CHECKLIST.md` / older reports | MongoDB + Hostinger MCP are no longer release blockers for local-first deploys. |

---

## 3. Persistence & migrations

**Status: PASS (local-first)**

- Runtime store is **SQLite** via `LocalReportStore` / `S2RS_DATA_DIR` (default `~/.s2-report-sniffer`).
- Smoke used `S2RS_DATA_DIR=/workspace/local_data_prod_smoke`; storage health check reported OK.
- `backend/migrations_runner.py` still references legacy MongoDB — **not** required for current production path. Do not treat Mongo connectivity as a release gate.

---

## 4. Integrated production smoke

**Status: PASS**

Commands (from repo layout):

```bash
cd frontend && npm run build
cd ../backend
S2RS_DATA_DIR=./local_data_prod_smoke S2RS_ENVIRONMENT=production \
  ../.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
```

| Check | Result |
|-------|--------|
| `GET /api/health` | `200` — `status=healthy`, `storage=true` |
| `GET /` | `307` → `/ui/` |
| `GET /ui/` | `200` `text/html` |
| Built JS under `/ui/static/` and `/static/` | `200` |
| `POST /api/reports/upload` (synthetic zip) | `200` — queued |
| Status poll | reached `ready` |
| `GET /api/reports/{id}/overview` | `200` — overview payload populated |
| `GET /api/reports/{id}/recommendations` | `200` |
| External network required for core path | **No** |

Evidence artifacts: `/opt/cursor/artifacts/prod-smoke-health.json`, `/opt/cursor/artifacts/prod-smoke-upload.txt`.

---

## 5. Checklist mapping ([CORRECTNESS_CHECKLIST.md](CORRECTNESS_CHECKLIST.md))

| Checklist item | Status |
|----------------|--------|
| Frontend builds | PASS |
| Bandit backend | PASS |
| Backend pytest | PASS |
| Superchecker / parser / API smoke | PASS (included in full suite) |
| Hostinger MCP runtime probe | **Skipped** — optional cloud extension (`S2RS_ENABLE_CLOUD_EXTENSIONS`); not required for local-first prod |
| Mongo / Alembic Mongo check | **Skipped** — runtime is SQLite |
| `PREPROD_TEST_REPORT.md` updated | This document |
| Explicit deployment decision | Below |

---

## 6. Code change included in this verification

- **`backend/server.py`:** `_ensure_upload_dir()` — prefer `{tempdir}/sdb_uploads`, fall back to `mkdtemp(prefix="sdb_uploads_")` when not writable. Prevents upload HTTP 500 when a stale root-owned staging directory exists.
- **`backend/test_upload_dir.py`:** regression coverage for writable preferred path and non-writable fallback.

---

## Identified issues & severity

| ID | Component | Issue | Severity | Mitigation |
|----|-----------|-------|----------|------------|
| 01 | Upload staging | Pre-existing non-writable `/tmp/sdb_uploads` caused upload 500s | Medium (env) | Fixed via `_ensure_upload_dir()` fallback |
| 02 | Error responses | Partial S-04: some 400 paths may echo exception text | Low | Set `S2RS_ENVIRONMENT=production`; tighten 400 messages later |
| 03 | Docs | Older preprod notes still mention MongoDB as required | Low | This report supersedes them for local-first |

---

## Final recommendation

All CI-equivalent gates and the integrated UI+API production smoke passed against the current local-first architecture. The upload-dir writability blocker found during verification was fixed and retested.

**Decision: GO.** Proceed with production deployment using SQLite/`S2RS_DATA_DIR`, with `S2RS_ENVIRONMENT=production`, and cloud extensions left disabled unless explicitly required.
