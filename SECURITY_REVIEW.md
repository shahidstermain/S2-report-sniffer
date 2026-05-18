# S2 Report Sniffer — Security Hardening Review

**Review Date:** 2026-05-18
**Reviewer:** Automated Security Review
**Scope:** Backend (Python/FastAPI) + Frontend (JavaScript/React) + Desktop (Electron)

---

## Executive Summary

19 security findings were identified: 2 Critical, 4 High, 6 Medium, 7 Low. The codebase has good foundational practices (archive safety, Electron hardening, input validation), but has gaps in security headers, CORS defaults, path traversal in static file serving, and attack surface that should be addressed before production use.

---

## CRITICAL SEVERITY

### [F1] Missing Security Headers (CSP, X-Frame-Options, X-Content-Type-Options)
**Files:** `frontend/index.html`, `backend/server.py`

No Content Security Policy is defined. The application does not set:
- `Content-Security-Policy`
- `X-Frame-Options`
- `X-Content-Type-Options`
- `Referrer-Policy`
- `Permissions-Policy`

This leaves the application vulnerable to XSS, clickjacking, and MIME-type sniffing attacks.

**Recommendation:** Add a custom middleware in `server.py` that applies security headers to all responses.

---

### [F2] CORS Misconfiguration - Wildcard Origins Allowed
**Files:** `backend/server.py:71-75`, `INTEGRATION.md:52`

The documentation shows `CORS_ORIGINS='*'` for development which could be accidentally deployed to production. While the current code defaults to deny-all, the environment variable approach is risky.

**Recommendation:** Explicitly deny wildcard origins in production. Document required CORS configuration. Add runtime validation.

---

## HIGH SEVERITY

### [F3] Path Traversal in UI Static File Serving
**Files:** `backend/server.py:1332-1346`

```python
@api_router.get("/ui/{path:path}")
async def ui_spa(path: str):
    candidate = (ui_path / path).resolve()
    if str(candidate).startswith(str(root)) and candidate.exists() and candidate.is_file():
        return FileResponse(str(candidate), headers={"Cache-Control": "no-store"})
```

The `startswith` check after `resolve()` can be bypassed via symlinks or encoded paths on case-insensitive filesystems.

**Recommendation:** Use strict allowlist-based path validation with `is_relative_to()` check.

---

### [F4] Local Import Path Traversal
**Files:** `backend/server.py:429-498`

While the code checks file existence and permissions, the path resolution with `.resolve()` follows symlinks, potentially allowing reads outside intended directories.

**Recommendation:** Add explicit parent-directory boundary check using `Path.relative_to()`.

---

### [F5] No Rate Limiting on Upload Endpoint
**Files:** `backend/server.py:170-418`

The `/reports/upload` endpoint has no rate limiting, allowing unlimited upload attempts which could exhaust server resources.

**Recommendation:** Implement rate limiting using `slowapi`.

---

### [F6] Decompression Bomb Prevention Gaps
**Files:** `backend/parsers.py:235`

Zip extraction uses `zf.getinfo(name).file_size` (declared sizes) rather than actual extracted sizes. A zip bomb with highly compressed nested data could potentially bypass detection.

**Recommendation:** Track actual extracted bytes for zip files and apply the same budget check as tar extraction.

---

## MEDIUM SEVERITY

### [F7] Missing CSRF Protection
**Files:** `backend/server.py` (entire API)

The API has no CSRF token mechanism. While the local-first architecture limits exposure, cross-origin requests from browser extensions could trigger state-changing operations.

---

### [F8] Sensitive Data in Logs
**Files:** `backend/monitoring.py:172`, `backend/server.py:405`

Error messages and stack traces may contain sensitive paths, internal IP addresses, or metadata exposed in logs.

**Recommendation:** Sanitize error details before logging using pattern redaction.

---

### [F9] No Input Sanitization on Report Content Rendering
**Files:** `frontend/src/components/*.jsx`

Report content from parsed archives (hostnames, database names, log messages) is rendered without consistent sanitization.

**Recommendation:** Ensure all dynamic content in React components uses proper escaping.

---

### [F10] Hostinger API Token Validation Insufficient
**Files:** `backend/server.py:1042-1050`

API token is read directly from environment without validation of minimum length or format.

**Recommendation:** Add token validation to ensure minimum security requirements.

---

### [F11] Lock File in Predictable Location
**Files:** `backend/desktop_entry.py:10`

Using `/tmp` for lock files is susceptible to symlink attacks and denial of service.

**Recommendation:** Use a protected location within the user's home directory.

---

### [F12] Error Message Information Disclosure
**Files:** `backend/server.py:417`, `frontend/src/lib/api.js:48`

Full error messages (including Python tracebacks via `exc_info`) are returned to clients.

**Recommendation:** Return sanitized error messages in production; keep detailed errors for development only.

---

## LOW SEVERITY

### [F13] Insecure Random UUID Generation
**Files:** `backend/server.py:220`

Uses standard `uuid.uuid4()`. Consider `secrets` module for higher-security needs.

---

### [F14] No Request ID / Correlation ID
**Files:** `backend/server.py` (entire API)

No correlation/request ID in logs for tracing requests through the system.

---

### [F15] Glean MCP URL Validation Insufficient
**Files:** `backend/server.py:1169-1170`

URL validation only checks prefix, not whether the URL is well-formed or includes DNS rebinding protection.

---

### [F16] Insecure HTML Export Endpoint
**Files:** `backend/server.py:1123-1134`

Report titles are inserted directly into HTML without escaping, creating XSS vulnerability.

---

### [F17] Electron Shell External Links Bypass
**Files:** `desktop/main.js:103`

Unknown protocols (file://, ftp://, etc.) are opened in the default browser without validation.

**Recommendation:** Allowlist permitted protocols (http, https only).

---

### [F18] Missing Additional Electron Security Settings
**Files:** `desktop/main.js:71-80`

Missing `allowRunningInsecureContent: false`, `enableWebSQL: false`, and other hardening flags.

---

### [F19] Missing Security Audit Logging for Sensitive Operations
**Files:** `backend/monitoring.py:213-249`

AuditLogger exists but is not used for configuration changes, report deletion, or export operations.

---

## Summary Table

| ID | Category | Severity | Location |
|----|----------|----------|----------|
| F1 | Security Headers | CRITICAL | `server.py`, `index.html` |
| F2 | CORS Misconfig | CRITICAL | `server.py:71-75` |
| F3 | Path Traversal | HIGH | `server.py:1337` |
| F4 | Path Traversal | HIGH | `server.py:442` |
| F5 | Rate Limiting | HIGH | `server.py:170` |
| F6 | Decompression Bomb | HIGH | `parsers.py:235` |
| F7 | CSRF | MEDIUM | `server.py` |
| F8 | Log Disclosure | MEDIUM | `monitoring.py:172` |
| F9 | XSS | MEDIUM | `frontend/src/**/*.jsx` |
| F10 | Input Validation | MEDIUM | `server.py:1042` |
| F11 | Lock File | MEDIUM | `desktop_entry.py:10` |
| F12 | Error Disclosure | MEDIUM | `server.py:417` |
| F13 | Random | LOW | `server.py:220` |
| F14 | Observability | LOW | `server.py` |
| F15 | SSRF | LOW | `server.py:1169` |
| F16 | XSS Export | LOW | `server.py:1133` |
| F17 | Electron | LOW | `desktop/main.js:103` |
| F18 | Electron | LOW | `desktop/main.js:71` |
| F19 | Audit Logging | LOW | `monitoring.py` |

---

## Positive Security Practices Observed

The codebase demonstrates several strong security practices:

1. **Archive Extraction Safety:** Good path traversal prevention and symlink handling in `parsers.py`
2. **Size Budget Enforcement:** 50GB decompression budget prevents zip bombs
3. **Electron Hardening:** `nodeIntegration: false`, `sandbox: true`, `contextIsolation: true`
4. **Input Validation:** Comprehensive `validators.py` with XSS pattern detection
5. **Password-Protected Archive Rejection:** Encrypted zip detection
6. **UUID Report IDs:** Cryptographically random UUIDs
7. **Navigation Controls:** External navigation blocked, popups denied
