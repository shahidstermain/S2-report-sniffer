# S2 Report Sniffer — Security Hardening Review

**Review Date:** 2026-05-18 (re-verified 2026-07-14)
**Reviewer:** Automated Security Review
**Scope:** Backend (Python/FastAPI) + Frontend (JavaScript/React) + Desktop (Electron)

---

## Executive Summary

19 security findings were identified in the original review: 2 Critical, 4 High, 6 Medium, 7 Low. As of 2026-07-14, Critical and High items are **Fixed** or **Mitigated**; remaining Medium/Low items were closed or accepted with local-first mitigations (Origin check, request IDs, generic client errors, Hostinger token length, Electron flags, export audit logs).

The codebase has strong foundational practices (archive safety, Electron isolation, input validation). This document tracks status against the original checklist.

---

## Status Legend

| Status | Meaning |
|--------|---------|
| **Fixed** | Implemented and verified in current code |
| **Mitigated** | Residual risk reduced to an acceptable local-first posture |
| **Accepted** | Not changing by design (risk accepted) |
| **N/A** | Finding no longer applies to current architecture |

---

## CRITICAL SEVERITY

### [F1] Missing Security Headers (CSP, X-Frame-Options, X-Content-Type-Options)
**Status:** Fixed  
**Files:** `frontend/index.html`, `backend/server.py`

`_SecurityHeadersMiddleware` sets CSP (including `font-src 'self'`, `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, and `Permissions-Policy`. Google Fonts CDN links were removed from `index.html` so CSP stays self-only.

---

### [F2] CORS Misconfiguration - Wildcard Origins Allowed
**Status:** Fixed  
**Files:** `backend/server.py`

`_get_cors_origins()` defaults to deny-all and raises if `S2RS_CORS_ORIGINS` contains `*`.

---

## HIGH SEVERITY

### [F3] Path Traversal in UI Static File Serving
**Status:** Fixed  
**Files:** `backend/server.py` (`ui_spa`)

Resolved paths must satisfy `is_relative_to(ui_root)` after `resolve()`; `..` and absolute path segments are rejected.

---

### [F4] Local Import Path Traversal
**Status:** Fixed  
**Files:** `backend/server.py` (`_resolve_allowed_import_path`)

Import/rehydrate paths are validated with an allowlist and `Path.is_relative_to()`.

---

### [F5] No Rate Limiting on Upload Endpoint
**Status:** Fixed  
**Files:** `backend/server.py`

`_RateLimitMiddleware` limits uploads to 10/minute per client IP.

---

### [F6] Decompression Bomb Prevention Gaps
**Status:** Fixed  
**Files:** `backend/parsers.py`

Zip/tar/gzip extraction tracks **actual** decompressed bytes against `MAX_EXTRACTED_BYTES`.

---

## MEDIUM SEVERITY

### [F7] Missing CSRF Protection
**Status:** Mitigated  
**Files:** `backend/server.py`

Local-first loopback app: `_OriginCheckMiddleware` rejects mutating methods (`POST`/`PUT`/`PATCH`/`DELETE`) when `Origin` is present and is not a loopback/`null` origin. No session CSRF tokens (overkill for desktop/local API). Absent Origin (curl, same-origin Electron) is allowed.

---

### [F8] Sensitive Data in Logs
**Status:** Mitigated  
**Files:** `backend/server.py`, `backend/monitoring.py`

Upload/security paths use `_redact_sensitive()` to strip filesystem paths before security event details; full traces remain in server logs only as needed for operators.

---

### [F9] No Input Sanitization on Report Content Rendering
**Status:** Mitigated  
**Files:** `frontend/src/components/*.jsx`

React escapes text by default; no `dangerouslySetInnerHTML` usage found. HTML export uses `html.escape`.

---

### [F10] Hostinger API Token Validation Insufficient
**Status:** Fixed  
**Files:** `backend/server.py`

When cloud extensions are enabled, `HOSTINGER_API_TOKEN` must be non-empty and at least 20 characters.

---

### [F11] Lock File in Predictable Location
**Status:** Fixed  
**Files:** `backend/desktop_entry.py`

Lock file lives under `~/Library/Logs/S2ReportSniffer` (or `S2RS_RUNTIME_DIR`), not world-writable `/tmp`.

---

### [F12] Error Message Information Disclosure
**Status:** Fixed  
**Files:** `backend/server.py`

Upload failures return a generic client message; details are logged server-side with redaction.

---

## LOW SEVERITY

### [F13] Insecure Random UUID Generation
**Status:** Accepted  
**Files:** `backend/server.py`

`uuid.uuid4()` is cryptographically suitable for report IDs; no change required.

---

### [F14] No Request ID / Correlation ID
**Status:** Fixed  
**Files:** `backend/server.py`

`_RequestIdMiddleware` accepts inbound `X-Request-ID` or generates a UUID and echoes it on the response.

---

### [F15] Glean MCP URL Validation Insufficient
**Status:** N/A  
**Files:** *(removed / obsolete)*

Analyze in Glean is a **local** Markdown packet handoff; there is no backend MCP URL fetch for RCA.

---

### [F16] Insecure HTML Export Endpoint
**Status:** Fixed  
**Files:** `backend/server.py`

Report fields in HTML export are passed through `html.escape`.

---

### [F17] Electron Shell External Links Bypass
**Status:** Fixed  
**Files:** `desktop/main.js`

External navigation / window open only allows `http:` and `https:`.

---

### [F18] Missing Additional Electron Security Settings
**Status:** Fixed  
**Files:** `desktop/main.js`

`allowRunningInsecureContent: false` and `enableWebSQL: false` set alongside existing `sandbox` / `contextIsolation` / `nodeIntegration: false`.

---

### [F19] Missing Security Audit Logging for Sensitive Operations
**Status:** Fixed  
**Files:** `backend/server.py`, `backend/monitoring.py`

Audit log covers upload, delete, HTML export, and Glean export (plus existing security events).

---

## Summary Table

| ID | Category | Severity | Status | Location |
|----|----------|----------|--------|----------|
| F1 | Security Headers | CRITICAL | Fixed | `server.py`, `index.html` |
| F2 | CORS Misconfig | CRITICAL | Fixed | `server.py` |
| F3 | Path Traversal | HIGH | Fixed | `server.py` (`ui_spa`) |
| F4 | Path Traversal | HIGH | Fixed | `server.py` (import path) |
| F5 | Rate Limiting | HIGH | Fixed | `server.py` |
| F6 | Decompression Bomb | HIGH | Fixed | `parsers.py` |
| F7 | CSRF | MEDIUM | Mitigated | `server.py` (Origin check) |
| F8 | Log Disclosure | MEDIUM | Mitigated | `server.py` |
| F9 | XSS | MEDIUM | Mitigated | `frontend/src/**` |
| F10 | Input Validation | MEDIUM | Fixed | `server.py` (Hostinger token) |
| F11 | Lock File | MEDIUM | Fixed | `desktop_entry.py` |
| F12 | Error Disclosure | MEDIUM | Fixed | `server.py` |
| F13 | Random | LOW | Accepted | `server.py` |
| F14 | Observability | LOW | Fixed | `server.py` |
| F15 | SSRF | LOW | N/A | Glean local handoff |
| F16 | XSS Export | LOW | Fixed | `server.py` |
| F17 | Electron | LOW | Fixed | `desktop/main.js` |
| F18 | Electron | LOW | Fixed | `desktop/main.js` |
| F19 | Audit Logging | LOW | Fixed | `server.py` / `monitoring.py` |

---

## Positive Security Practices Observed

The codebase demonstrates several strong security practices:

1. **Archive Extraction Safety:** Path traversal prevention and symlink handling in `parsers.py`
2. **Size Budget Enforcement:** Decompression budget prevents zip bombs (actual bytes counted)
3. **Electron Hardening:** `nodeIntegration: false`, `sandbox: true`, `contextIsolation: true`, insecure content / WebSQL disabled
4. **Input Validation:** Comprehensive `validators.py` with XSS pattern detection
5. **Password-Protected Archive Rejection:** Encrypted zip detection
6. **UUID Report IDs:** Cryptographically random UUIDs
7. **Navigation Controls:** External navigation blocked except allowlisted http(s); popups denied
8. **Local-first data:** No product telemetry; Glean packet egress only when the user attaches the file
