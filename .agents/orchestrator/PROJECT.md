# Project: S2 Report Sniffer Checker Alignment

## Architecture
- `backend/parsers.py`: Parses support bundles and extracts OS parameters (THP, swappiness, overcommit, etc.) and cluster state metrics.
- `backend/superchecker.py`: Analyzes parsed metrics and applies scoring rules (healthy, warning, critical).
- `backend/validators.py`: Sanitizes and validates request and report payloads.
- `backend/monitoring.py`: Tracks monitoring telemetry/events.
- `backend/storage.py`: Manages SQLite database and local reports.
- `backend/tests/`: Diagnostic and API test suite.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Exploration & Gap Analysis | Auditing existing checkers in `superchecker.py` and `parsers.py` | None | DONE |
| 2 | Implementation & Alignment | Modify check logic, align thresholds, propagate to validators, monitoring, and storage | M1 | DONE |
| 3 | Test Expansion & Verification | Run/expand backend pytests, verify with reviewer and challenger | M2 | DONE |
| 4 | Forensic Audit & Handoff | Forensic integrity audit and handoff generation | M3 | DONE |

## Interface Contracts
- No new API endpoints. Existing endpoints (`/api/reports/{id}/overview`, etc.) must remain compatible.
- Check payload and recommendation JSON schemas must match what frontend/storage expects.
