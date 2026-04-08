# SuperChecker Recommendation System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement, validate, and fully deploy the complete SuperChecker recommendation engine, addressing the 50+ advanced diagnostic checks that were flagged for partial implementation, stubbed execution, or missing test coverage in the pre-production validation.

**Architecture:** Python-based deterministic rule engine (`_CheckerState`) running synchronously on `sdb-report` parsed artifacts. The engine evaluates memory, storage, query performance, and replication rules, assigning severity and priority weights. Findings are aggregated, correlated for root-cause analysis, and surfaced via the existing `Recommendations.jsx` React component.

**Tech Stack:** Python 3.10+, FastAPI (backend), pytest (coverage), React/Tailwind (frontend).

---

## 1. Detailed Analysis of Flagged Components

The SuperChecker system (`backend/superchecker.py`) currently contains several structural gaps and stubbed methods flagged by the pre-production test report (QLT-001: 75% coverage) and static analysis (checks placed under `if False:` block).

| Component / Checker | Current State | Impact if Missing |
| :--- | :--- | :--- |
| **Memory & Storage Analyzers** (`_check_cluster_memory_usage`, `_check_disk_usage_and_inodes`) | Partially implemented / Stubbed | Critical. Inability to warn users of impending OOMs or disk-full events. |
| **Node & Replication Health** (`_check_node_online_status`, `_check_replication_health`) | Partially implemented | Critical. Fails to identify degraded clusters or split-brain scenarios. |
| **Performance Analyzers** (`_check_blocked_and_long_queries`, `_check_query_queues`) | Disabled / Mocked | High. Misses obvious query compilation bottlenecks. |
| **Pipeline & Object Analyzers** (`_check_pipeline_analysis`, `_check_collection_errors_and_object_names`) | Missing (identified in `add_missing_checkers.py`) | Medium. Data ingestion failures go unnoticed by the dashboard. |
| **Configuration Checks** (`_check_numa_ssd_filesystem`, `_check_cpu_kernel_model_consistency`) | Disabled (`if False:`) | Low. Sub-optimal performance, but not an immediate outage risk. |
| **Anomaly Correlation Engine** (`correlate()`) | Stubbed / Basic | Medium. Users receive noisy, disconnected alerts instead of a unified root cause. |

---

## 2. Prioritization Matrix & Deferment Strategy

We will use a Phased Rollout approach to mitigate risk and ensure critical path stability.

### Phase 1: Critical Operations (Immediate Implementation)
*Focus: Outage prevention and cluster availability.*
- `_check_node_online_status`
- `_check_cluster_memory_usage`
- `_check_disk_usage_and_inodes`
- `_check_replication_health`

### Phase 2: Performance & Ingestion (Fast Follow)
*Focus: Workload optimization and data freshness.*
- `_check_blocked_and_long_queries`
- `_check_pipeline_analysis`
- `_check_missing_checkers` (Orphan databases, Alerting)
- `correlate()` (Basic parent-child alert suppression)

### Phase 3: Deep Configuration & AI Mining (Deferred)
*Focus: System tuning and proactive anomaly detection.*
- `_check_numa_ssd_filesystem`
- `_check_cpu_kernel_model_consistency`
- `_check_preinstall_kernel_memory_network`
- Advanced NLP log pattern mining inside `correlate()`

---

## 3. Technical Architecture Specifications

1.  **Backend Rules Engine:**
    *   **State Management:** The `_CheckerState` class maintains the `self.findings` array.
    *   **Rule Execution:** Methods like `_check_cluster_memory_usage` parse the `self.report` dictionary.
    *   **Scoring Model:** Use the existing `SEVERITY_WEIGHT` and `PRIORITY_WEIGHT` dictionaries to calculate a deterministic `risk_score` for sorting.
2.  **Frontend Integration:**
    *   The `Recommendations.jsx` component consumes `/api/reports/{id}/recommendations`.
    *   The UI must support filtering by `severity` and `category` (Performance, Alerting, Pre-installation).
3.  **Data Contract:**
    *   Each finding must conform to: `{ checker_id: str, severity: str, category: str, title: str, description: str, evidence: str, remediation: str, confidence: float }`

---

## 4. Resource Allocation & Timeline

**Total Estimated Duration:** 3 Weeks
**Team Requirement:** 1 Backend Engineer (Python), 1 QA Engineer (SDET)

*   **Week 1 (Milestone 1):** Un-stub and implement Phase 1 Critical Checkers. Achieve 90% unit test coverage on the `superchecker.py` core logic.
*   **Week 2 (Milestone 2):** Implement Phase 2 Performance & Pipeline checkers. Integrate `add_missing_checkers.py` logic safely.
*   **Week 3 (Milestone 3):** E2E testing with MongoDB, staging deployment, and Phase 3 deferment documentation.

---

## 5. Risk Assessment

| Risk | Likelihood | Impact | Mitigation Strategy |
| :--- | :--- | :--- | :--- |
| **False Positives (Alert Fatigue)** | High | Medium | Implement strict `confidence` scoring (>0.8 required for Critical). Use the `correlate()` method to suppress child alerts if a parent node is offline. |
| **Performance Overhead (Parsing)** | Low | High | Pre-production tests showed `0.0452 ms/req`. Keep rule execution strictly in-memory (no DB calls during `run_superchecker`). |
| **Coverage Regression** | Medium | Medium | Enforce a strict TDD approach. No rule is merged without a synthetic `report` payload test asserting its trigger conditions. |
| **Deferred Feature Debt** | High | Low | Create explicit Jira/GitHub tickets for Phase 3 configuration checks. They are not required for MVP cluster triage. |

---

## 6. Testing Strategies

*   **Unit Testing (TDD):** Create synthetic `dict` payloads simulating OOMs, offline nodes, and pipeline errors. Assert that `superchecker` generates the exact expected finding dictionary.
*   **Integration Testing:** Process known historical `sdb-report` tarballs (from `test_reports/`) and snapshot-test the output JSON.
*   **E2E Testing:** Deploy to staging. Upload a report via the React UI, ensure the `Recommendations.jsx` component renders the warnings without console errors.

---

## 7. Success Metrics

1.  **Code Coverage:** `backend/superchecker.py` coverage increases from 75% to **>= 90%** (resolving QLT-001).
2.  **Performance Benchmark:** Total recommendation generation time remains **< 10ms** per report payload.
3.  **Accuracy Rate:** **0% unhandled exceptions** during parsing of the top 50 historical `sdb-report` archives.
4.  **Adoption/Effectiveness:** Support Engineers utilize the generated remediation steps in **> 60%** of performance-related support tickets.

---

## 8. Implementation Tasks (Bite-Sized)

### Task 1: Restore Phase 1 Critical Checkers

**Files:**
- Modify: `backend/superchecker.py`
- Modify: `backend/test_superchecker.py` (Create if missing)

- [ ] **Step 1: Write failing test for memory usage checker**
```python
# backend/test_superchecker.py
from backend.superchecker import run_superchecker

def test_memory_usage_critical():
    report = {
        "cluster_overview": {"memory_used_mb": 95000, "memory_capacity_mb": 100000}
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "memoryUsage" and f["severity"] == "critical" for f in findings)
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest backend/test_superchecker.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Phase 1 logic in `superchecker.py`**
Move `_check_cluster_memory_usage`, `_check_node_online_status`, and `_check_disk_usage_and_inodes` out of the `if False:` block and ensure they populate `self._add(...)`.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest backend/test_superchecker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add backend/superchecker.py backend/test_superchecker.py
git commit -m "feat(superchecker): restore Phase 1 critical checkers with tests"
```

### Task 2: Implement Phase 2 Missing Checkers (Pipelines & Orphan DBs)

**Files:**
- Modify: `backend/superchecker.py`
- Delete: `add_missing_checkers.py`

- [ ] **Step 1: Write failing test for pipeline and orphan DBs**
```python
# backend/test_superchecker.py
def test_orphan_databases():
    report = {
        "cluster_overview": {"orphan_databases": ["db_test_orphan"]}
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "orphanDatabases" for f in findings)
```

- [ ] **Step 2: Integrate `add_missing_checkers.py` logic into `superchecker.py`**
Copy the `_check_missing_checkers` and `_check_pipeline_analysis` methods into the `_CheckerState` class and add them to the `run()` sequence.

- [ ] **Step 3: Run test to verify it passes**
Run: `pytest backend/test_superchecker.py -v`

- [ ] **Step 4: Clean up loose scripts and commit**
```bash
rm add_missing_checkers.py add_missing_checkers_2.py
git add backend/superchecker.py backend/test_superchecker.py
git commit -m "feat(superchecker): implement pipeline and orphan DB checkers"
```

### Task 3: Basic Correlation Engine (Phase 2)

**Files:**
- Modify: `backend/superchecker.py`

- [ ] **Step 1: Implement `correlate()` to suppress noisy alerts**
Update the `correlate` method to remove "Query Timeout" alerts if an "Offline Node" alert is already present (as the offline node is the root cause).

- [ ] **Step 2: Commit**
```bash
git add backend/superchecker.py
git commit -m "feat(superchecker): add basic root-cause correlation"
```
