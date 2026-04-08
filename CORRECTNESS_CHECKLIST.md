# S2 Report Sniffer - Correctness & Release Checklist

This document provides the definitive framework for verifying the purpose, logic, and output correctness of the S2 Report Sniffer application. It serves as the standard quality gate before any production deployment.

## 1. Acceptance Matrix (Purpose Correctness)

Verify that the application fulfills its core business requirements. Every feature must map to a demonstrable outcome.

| Feature Area | Acceptance Criteria | Verification Method |
| :--- | :--- | :--- |
| **Cluster Report Parsing** | Zip files containing SingleStore diagnostic logs (`report.json`, `logs.jsonl`, `showRebalanceStatus.json`) are ingested without crashing. | E2E Upload Test / `test_parsers.py` |
| **Root Cause Engine (Brain)** | Known failure patterns (e.g., Firewall/Port blocking, offline partitions) trigger the correct critical recommendations. | `test_superchecker.py` assertions |
| **Noise Suppression** | Secondary symptoms (e.g., disconnected replication) are suppressed if a root cause (e.g., firewall block) is found. | `test_correlation.py` / `test_superchecker.py` |
| **Hostinger VPS Integration** | API accurately fetches VMs and gracefully handles 401, 403, 429, and 504 Timeout errors with formatted payloads. | `test_hostinger_vps.py` |
| **Frontend Rendering** | Recommendations, cluster overview, and node health are visually rendered without React runtime errors. | Playwright E2E / `npm run build` |

---

## 2. Test Execution Guide (Logic & Output Correctness)

Run these exact commands from the **repository root** to verify the logic and outputs of the application.

### A. Backend Unit & Integration Tests

**Command:**

```bash
PYTHONPATH=. .venv/bin/pytest backend/ -q
```

**Key Test Files to Monitor:**

- `backend/test_superchecker.py`: Validates the recommendation engine and root-cause correlation (Firewall, Redundancy).
- `backend/test_parsers.py`: Validates ingestion of `rebalance_status` and cluster state.
- `backend/test_hostinger_vps.py`: Validates external API error handling.
- `backend/test_correlation.py`: Validates alert suppression logic.

### B. Frontend Production Build Check

Verifies that the React application compiles successfully without type or syntax errors.
**Command:**

```bash
cd frontend && npm run build
```

### C. Security Static Analysis (SAST)

Ensures no hardcoded secrets or risky patterns are introduced in the backend code.
**Command:**

```bash
.venv/bin/bandit -r backend/ -ll -i
```

*(Note: Ignore findings inside `.venv` if they appear in the output. Focus only on first-party code in `backend/`)*

### D. Database Migrations Safety

Verifies that Alembic migrations can be executed and rolled back safely.
**Command:**

```bash
PYTHONPATH=. .venv/bin/python backend/migrations_runner.py check
```

---

## 3. Release Gate Template

Copy this checklist into your Pull Request description or use it as a pre-deployment sign-off sheet.

### 🚀 Pre-Production Release Gate

#### 1. Static & Build Checks

- [ ] Frontend builds successfully (`cd frontend && npm run build`).
- [ ] Bandit security scan passes for `backend/` code (`.venv/bin/bandit -r backend/ -ll -i`).

#### 2. Test Coverage & Logic

- [ ] Backend tests pass (`PYTHONPATH=. .venv/bin/pytest backend/ -q`).
- [ ] `test_superchecker.py` passes (verifies core brain logic).
- [ ] `test_hostinger_vps.py` passes (verifies API resiliency).

#### 3. Output & Integration Integrity

- [ ] Checked for accidental destructive edits in `superchecker.py` (Verify diffs).
- [ ] Alembic migrations check passes (`PYTHONPATH=. .venv/bin/python backend/migrations_runner.py check`).
- [ ] Hostinger MCP status verified via active runtime probe (not just config check).

#### 4. Documentation & Artifacts

- [ ] `CHANGELOG.md` updated and formatted correctly.
- [ ] `PREPROD_TEST_REPORT.md` reflects latest test run status.
- [ ] Deployment decision is explicitly documented.

**Decision:** `[ GO / NO-GO ]`
**Sign-off:** _______________
