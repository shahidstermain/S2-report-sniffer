# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| Latest (`main`) | Yes |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report security issues by emailing the maintainers directly. Include:

1. A description of the vulnerability and its potential impact.
2. Steps to reproduce or a proof-of-concept (minimised if possible).
3. Any suggested remediation.

You will receive acknowledgement within 3 business days. We aim to release a fix within 14 days of confirmation for critical issues.

## Scope

This project processes **untrusted archive files** supplied by users. The key security boundaries are:

- **Archive extraction** — path traversal protection is enforced in `backend/parsers.py`. Archives containing `../` paths or absolute paths are rejected.
- **File size limits** — uploads are capped at 10 GB; the application does not cap decompressed size (zip-bomb risk is a known open issue).
- **Input validation** — all report IDs, search queries, filenames, and pagination parameters are validated in `backend/validators.py`.
- **No authentication by default** — this is a local-first desktop tool. Do **not** expose port 8000 publicly without adding authentication middleware.
- **CORS** — wildcard CORS origins are disabled. Set `CORS_ORIGINS` to an explicit list for any networked deployment.

## Known Limitations

- No built-in authentication or authorisation layer.
- No rate limiting on upload or processing endpoints.
- Decompressed archive size is not capped (zip-bomb protection is partial).

These are documented in the audit report and tracked as open issues.
