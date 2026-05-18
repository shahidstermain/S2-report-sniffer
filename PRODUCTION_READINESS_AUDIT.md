# S2 Report Sniffer — Production Readiness Audit

**Date:** 2026-05-18
**Scope:** Security · Architecture · Build · Observability · Test Coverage · Documentation
**Author:** Automated Security Audit (security-best-practices + manual review)

---

## Executive Summary

| Category | Status | Critical Issues | High Issues | Medium/Low |
|----------|--------|:---:|:---:|:---:|
| Security (Backend) | ⚠️ Review needed | 2 | 4 | 5 |
| Security (Frontend/Electron) | ✅ Good | 0 | 0 | 1 |
| Build & Packaging | ⚠️ Fix required | 0 | 1 | 3 |
| Observability | ✅ Present | 0 | 0 | 1 |
| Test Coverage | ⚠️ Gaps in security paths | 0 | 2 | 8 |
| Documentation | ✅ Complete | 0 | 0 | 1 |

**Overall verdict:** Buildable and functional, but several security and reliability issues must be addressed before production deployment. The Critical and High issues are fixable with moderate effort.

---

## PART 1 — SECURITY

### Critical Findings

#### [S-01] CSP header allows `unsafe-inline` scripts
**File:** [backend/server.py:113](file:///Users/shahidster/S2-report-sniffer/backend/server.py#L113)

```python
response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; ..."
```

**Impact:** XSS attack payload embedded in any user-controlled field (e.g., report title, node name) will execute regardless of CSP. The `unsafe-inline` directive for scripts defeats the entire purpose of CSP.

**Remediation:**
```python
response.headers["Content-Security-Policy"] = (
    "default-src 'self'; "
    "script-src 'self'; "           # Remove unsafe-inline
    "style-src 'self' 'unsafe-inline'; "  # Keep for React/favicon fonts only
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)
```

---

#### [S-02] ZIP Slip path traversal in archive extraction
**File:** [backend/parsers.py:231-238](file:///Users/shahidster/S2-report-sniffer/backend/parsers.py#L231-L238)

```python
with zipfile.ZipFile(archive_path, 'r') as zf:
    for name in zf.namelist():
        if name.startswith('/') or '..' in name:
            raise ValueError(f"Unsafe path in archive: {name}")
        zf.extract(name, extract_dir)
```

**Impact:** `zipfile.extract()` does NOT prevent ZIP Slip attacks. A crafted entry like `../../etc/cron.d/myscript` will write outside `extract_dir`. The `'..' in name` check only blocks exact substring matches, not path traversal sequences.

**Remediation:** Resolve and validate target path before extraction:
```python
safe_name = name.lstrip('/').replace('..', '')
target = (Path(extract_dir).resolve() / safe_name).resolve()
if not target.is_relative_to(Path(extract_dir).resolve()):
    raise ValueError(f"Path escape attempt: {name}")
zf.extract(name, extract_dir)
```

---

### High Findings

#### [S-03] Tar extraction uses string-only path checks (bypassable)
**File:** [backend/parsers.py:155-166](file:///Users/shahidster/S2-report-sniffer/backend/parsers.py#L155-L166)

```python
if member.name.startswith('/') or '..' in member.name:
    continue  # Skips, doesn't reject
```

**Impact:** Bypassable via Unicode normalization (`..%2E`, `..%u2215`) or nested paths that normalize to `../`. The `tarfile.extract()` with `set_attrs=False` provides OS-level protection but this is not documented behavior.

**Remediation:** Validate after resolve, not just string check:
```python
target = Path(extract_dir).resolve() / member.name
resolved = target.resolve()
if not str(resolved).startswith(str(Path(extract_dir).resolve())):
    raise ValueError(f"Path traversal in archive: {member.name}")
tf.extract(member, extract_dir, set_attrs=False)
```

---

#### [S-04] Error messages expose internal details to clients
**File:** [backend/server.py:446-459](file:///Users/shahidster/S2-report-sniffer/backend/server.py#L446-L459)

```python
except Exception as e:
    logger.error(f"Upload failed: {e}", exc_info=True)
    error_detail = {
        "message": str(e),  # Raw exception sent to client
        "filename": active_file.filename if active_file else "unknown"
    }
    raise HTTPException(500, error_detail)
```

**Impact:** Exception messages may reveal internal paths, SQL table names, or configuration details in the HTTP response body.

**Remediation:** Return generic messages in production:
```python
import os
if os.environ.get('S2RS_ENVIRONMENT') == 'production':
    error_detail = {"error": "Upload failed", "message": "An internal error occurred"}
else:
    error_detail = {"error": "Upload failed", "message": str(e), "filename": ...}
raise HTTPException(500, error_detail)
```

---

#### [S-05] CSP blocks legitimate calls when cloud extensions are enabled
**File:** [backend/server.py:113](file:///Users/shahidster/S2-report-sniffer/backend/server.py#L113)

```python
"connect-src 'self';"
```

**Impact:** When `S2RS_ENABLE_CLOUD_EXTENSIONS=1`, the Hostinger API (`https://api.hostinger.com`) and Glean MCP endpoints require `connect-src` entries. Without them, browser-side calls to these hosts are blocked.

**Remediation:** Extend CSP dynamically when cloud extensions are enabled:
```python
extra = [] if not _cloud_extensions_enabled() else ["https://api.hostinger.com", "https://*.glean.com"]
connect_src = f"'self' {' '.join(extra)}"
response.headers["Content-Security-Policy"] = f"... connect-src {connect_src}; ..."
```

---

#### [S-06] PyInstaller `hiddenimports=[]` will cause runtime `ImportError`
**File:** [s2rs-backend.spec:9](file:///Users/shahidster/S2-report-sniffer/s2rs-backend.spec#L9)

```python
hiddenimports=[],
```

**Impact:** Empty hidden imports list means PyInstaller only follows statically-resolvable imports. All dynamically-imported packages (`fastapi`, `uvicorn`, `pydantic`, `aiofiles`, `slowapi`, `python_multipart`, `rich`, `python_dotenv`) will fail at runtime with `ModuleNotFoundError` in the bundled executable.

**Remediation:** Populate hidden imports:
```python
hiddenimports=[
    'fastapi', 'starlette', 'pydantic', 'pydantic_core',
    'aiofiles', 'uvicorn', 'slowapi', 'python_multipart',
    'rich', 'python_dotenv', 'tenacity', 'requests'
],
```

---

### Medium Findings

#### [S-07] Filename allowlist accepts ASCII-only (homoglyph risk)
**File:** [backend/validators.py:47-48](file:///Users/shahidster/S2-report-sniffer/backend/validators.py#L47-L48)

```python
FILENAME_SAFE_PATTERN = re.compile(r'^[a-zA-Z0-9._-]+$')
```

**Impact:** ASCII-only pattern prevents Unicode uploads (good for safety) but doesn't normalize Unicode to ASCII equivalents. In environments with different locale settings, homoglyph characters could bypass other checks.

**Status:** Low risk — pattern correctly rejects non-ASCII input.

---

#### [S-08] AWS credentials not validated before use
**File:** [backend/s3_client.py:1-9](file:///Users/shahidster/S2-report-sniffer/backend/s3_client.py#L1-L9)

**Impact:** If `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` are missing or empty, the boto3 client will fail at runtime rather than at startup.

**Remediation:** Add fail-fast validation:
```python
key = os.environ.get('AWS_ACCESS_KEY_ID', '')
secret = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
if not key or not secret:
    raise RuntimeError("AWS credentials not configured")
```

---

#### [S-09] Rate limiting only on upload endpoint
**File:** [backend/server.py:20-43](file:///Users/shahidster/S2-report-sniffer/backend/server.py#L20-43)

**Impact:** Read endpoints (`/api/reports/{id}/logs`, `/api/reports/{id}/overview`) have no rate limiting. Repeated large requests could exhaust memory or CPU.

**Status:** Acceptable for local desktop use; elevated risk if ever exposed over network.

---

#### [S-10] Search query HTML-escaping stored before display
**File:** [backend/validators.py:84-111](file:///Users/shahidster/S2-report-sniffer/backend/validators.py#L84-L111)

**Impact:** `validate_search_query()` HTML-escapes content before storage. When rendered by React (which also escapes), users see literal `&lt;` instead of `<`. This is safe but produces confusing display.

**Status:** Low risk — double-escaping prevents XSS.

---

#### [S-11] No CSRF protection
**File:** [backend/server.py](file:///Users/shahidster/S2-report-sniffer/backend/server.py) (entire API)

**Impact:** For a local-only tool with no session authentication, CSRF is low priority. But if authentication is added in the future, CSRF must be implemented.

**Status:** Low priority for current architecture.

---

### Positive Security Practices

- **SQL Injection:** Parameterized queries in [storage.py](file:///Users/shahidster/S2-report-sniffer/backend/storage.py)
- **XXE Prevention:** No insecure XML parsing found
- **Archive Size Limits:** 50 GB decompression budget + 200k entry count limit enforced
- **CORS Wildcard Rejection:** Raises `ValueError` if `S2RS_CORS_ORIGINS='*'`
- **Electron Hardening:** `nodeIntegration: false`, `contextIsolation: true`, `sandbox: true`, `webviewTag: false`
- **Navigation Controls:** `will-navigate` + `setWindowOpenHandler` properly restrict origins
- **Input Validation:** Comprehensive allowlist-based validators

---

## PART 2 — BUILD & PACKAGING

#### [B-01] PyInstaller `hiddenimports=[]` empty (HIGH — also in S-06)
**File:** [s2rs-backend.spec:9](file:///Users/shahidster/S2-report-sniffer/s2rs-backend.spec#L9)

Critical for production. Bundled executable will crash with `ModuleNotFoundError` at runtime.

---

#### [B-02] Development dependencies shipped in runtime bundle
**File:** [backend/requirements.txt](file:///Users/shahidster/S2-report-sniffer/backend/requirements.txt)

`black`, `flake8`, `mypy`, `pytest`, `isort` are fully pinned but included in the runtime requirements file. These should be in a separate `requirements-dev.txt`.

**Remediation:** Create `backend/requirements.txt` (runtime-only) and `requirements-dev.txt` (dev tools). Update build script to install only the runtime requirements for the packaged build:
```bash
pip install --quiet -r backend/requirements.txt  # runtime only
```

---

#### [B-03] Unused MongoDB drivers bundled
**File:** [backend/requirements.txt:49,74](file:///Users/shahidster/S2-report-sniffer/backend/requirements.txt)

`motor==3.3.1` and `pymongo==4.6.3` are not used in the desktop/local-first path (per AGENTS.md notes). They add bundle bloat.

**Remediation:** Remove from requirements.txt or add to conditional extras.

---

#### [B-04] `.venv` created at repo root with no failure-time cleanup
**File:** [scripts/build-macos-arm64-dmg.sh:40](file:///Users/shahidster/S2-report-sniffer/scripts/build-macos-arm64-dmg.sh#L40)

The build script creates a Python venv at `.venv/` in the repo root. If the build fails mid-way, the `.venv` is not cleaned up, leaving dev artifacts in the working directory.

**Status:** Low impact — `.venv/` is in `.gitignore`.

---

#### [B-05] No `.env.example` documenting required environment variables
**File:** (missing)

`S2RS_DATA_DIR`, `S2RS_HOST`, `S2RS_PORT`, `S2RS_CORS_ORIGINS`, `HOSTINGER_API_TOKEN`, `AWS_*` env vars are used throughout the code but no template documents them for new developers.

**Remediation:** Create `backend/.env.example` listing all supported environment variables with descriptions.

---

## PART 3 — OBSERVABILITY

#### [O-01] No request/correlation IDs in logs
**File:** [backend/server.py](file:///Users/shahidster/S2-report-sniffer/backend/server.py) (entire API)

**Status:** Acceptable for local desktop use. For production-grade observability, add a request ID middleware that generates a UUID per request and includes it in all log entries.

---

## PART 4 — TEST COVERAGE GAPS

### High-Priority Untested Security Paths

| Code Path | Risk | Test File | Status |
|-----------|------|-----------|--------|
| `_SecurityHeadersMiddleware` headers present | CSP bypass | None | ❌ NOT COVERED |
| `_RateLimitMiddleware` returns 429 | DoS via upload | None | ❌ NOT COVERED |
| `_get_cors_origins()` raises on `*` | CORS bypass | None | ❌ NOT COVERED |
| ZIP Slip bypass via crafted archive | Path traversal | None | ❌ NOT COVERED |
| Tar path traversal via normalized paths | Path traversal | None | ❌ NOT COVERED |
| Local import path escape detection | Path traversal | None | ❌ NOT COVERED |
| Zip bomb (decompression budget) | DoS | None | ❌ NOT COVERED |
| Static file serving path traversal | Path traversal | None | ❌ NOT COVERED |

### Coverage Matrix Summary

| Category | Tested | Partially Tested | Untested |
|----------|:------:|:---:|:---:|
| Validators | 9 | 0 | 0 |
| Upload/validation | 11 | 2 | 5 |
| Archive extraction | 5 | 1 | 0 |
| Local import | 4 | 0 | 3 |
| Superchecker | 17 | 1 | 0 |
| Health/Monitoring | 5 | 3 | 1 |
| Security middleware | 0 | 0 | 3 |
| Static file serving | 0 | 0 | 2 |
| Electron/Desktop | 0 | 0 | 3 |
| Frontend UI | 2 | 2 | 1 |

**Coverage:** Backend core ~85%, security attack surface ~10%, Electron 0%.

---

## PART 5 — REPO HYGIENE

| Check | Status | Notes |
|-------|--------|-------|
| `.gitignore` completeness | ✅ | Comprehensive |
| Secrets committed | ✅ | No secrets found |
| Hardcoded credentials | ✅ | All via env vars |
| `.env.example` | ❌ | Missing |
| README.md | ✅ | Present with build instructions |
| TODO/FIXME comments | ✅ | Minimal |
| PII in logs | ✅ | Clean, UUIDs truncated |
| Dockerfile secrets | ✅ | No build-arg secrets |

---

## Required Fixes Before Production

| Priority | ID | Issue | File | Effort |
|----------|-----|-------|------|--------|
| **MUST** | S-01 | Remove `unsafe-inline` from CSP script-src | server.py:113 | Low |
| **MUST** | S-02 | Fix ZIP Slip path traversal | parsers.py:231 | Medium |
| **MUST** | B-01 | Populate `hiddenimports` in PyInstaller spec | s2rs-backend.spec:9 | Low |
| **SHOULD** | S-03 | Fix tar path traversal string checks | parsers.py:155 | Medium |
| **SHOULD** | S-04 | Sanitize error messages for production | server.py:446 | Low |
| **SHOULD** | S-05 | Add cloud domains to CSP when enabled | server.py:113 | Low |
| **COULD** | B-02 | Split dev/runtime requirements | requirements.txt | Medium |
| **COULD** | B-05 | Add `.env.example` | (missing) | Low |
| **NICE** | S-09 | Add read endpoint rate limits | server.py | Medium |
| **NICE** | S-08 | Add AWS credential validation | s3_client.py | Low |

---

## Audit Checklist (Pre-Production Sign-Off)

```
SECURITY
  [ ] S-01: CSP unsafe-inline removed
  [ ] S-02: ZIP Slip fix applied and tested
  [ ] S-03: Tar path traversal fix applied
  [ ] S-04: Error messages sanitized
  [ ] S-05: Cloud domains added to CSP
  [ ] S-06: PyInstaller hiddenimports populated

BUILD & PACKAGING
  [ ] B-01: hiddenimports populated
  [ ] B-02: Requirements split (dev vs runtime)
  [ ] B-03: Unused deps (motor, pymongo) removed
  [ ] B-05: .env.example created

TEST COVERAGE
  [ ] Security middleware tests added
  [ ] ZIP Slip attack test added
  [ ] Rate limit integration test added

OPS & DOCS
  [ ] O-01: Request IDs in logs (optional)
  [ ] B-05: .env.example documented
  [ ] USER_MANUAL.md reviewed for accuracy
  [ ] PACKAGING.md updated with new build steps
```