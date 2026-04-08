# Phase 3 Deferred Tasks (SuperChecker Configuration & AI Mining)

The following advanced diagnostic rules and engines have been officially deferred from the MVP release to ensure a rapid, stable rollout of the critical outage-prevention and performance-bottleneck checkers. 

These tasks have been isolated because they pose a higher risk of generating false positives (alert fatigue) in diverse production environments, or they require significant computational overhead.

---

## 🛠 Ticket: SUP-101
**Title:** Implement Advanced NUMA, SSD, and Filesystem Checks
**Priority:** P3 (Deferred)
**Component:** `backend/superchecker.py` -> `_check_numa_ssd_filesystem`

**Description:**
We need to re-enable and tune the checks for NUMA boundaries, SSD block alignments, and XFS/ext4 mount options. 
- **Risk:** Hardware configurations vary wildly between bare-metal and containerized Kubernetes deployments. A strict rule here might flag standard EKS deployments as "incorrect".
- **Acceptance Criteria:** 
  - Add logic to bypass this check if running inside a containerized environment.
  - Implement unit tests covering bare-metal SSD misalignment payloads.

---

## 🛠 Ticket: SUP-102
**Title:** CPU & Kernel Model Consistency Checker
**Priority:** P3 (Deferred)
**Component:** `backend/superchecker.py` -> `_check_cpu_kernel_model_consistency`

**Description:**
Clusters with mixed CPU architectures (e.g., combining older Intel Xeon with newer generations) can cause query compilation skew and unbalanced performance.
- **Risk:** Mixed-architecture clusters are increasingly common during rolling hardware upgrades. Flagging this as "Critical" causes unnecessary panic.
- **Acceptance Criteria:**
  - Lower the severity of this check to `info` or `warning`.
  - Add a confidence decay algorithm if the node uptime is very low (indicating an active rolling upgrade).

---

## 🛠 Ticket: SUP-103
**Title:** Pre-installation Kernel, Memory, and Network Config Checks
**Priority:** P3 (Deferred)
**Component:** `backend/superchecker.py` -> `_check_preinstall_kernel_memory_network`

**Description:**
This checker validates `sysctl` limits (e.g., `net.core.somaxconn`, `vm.max_map_count`).
- **Risk:** Redundant with existing `sdb-admin check-system` outputs. 
- **Acceptance Criteria:**
  - Audit existing `sdb-admin` outputs. If `sdb-admin` already catches the violation, suppress our dashboard alert to reduce noise.

---

## 🛠 Ticket: SUP-104
**Title:** Advanced NLP Log Pattern Mining for Anomaly Correlation
**Priority:** P4 (Deferred)
**Component:** `backend/superchecker.py` -> `correlate()`

**Description:**
The current `correlate()` engine uses basic deterministic string matching (e.g., if Node is Offline -> suppress Query Timeout). We want to implement an NLP-based log clustering algorithm to group unknown tracelog errors and identify zero-day anomalies.
- **Risk:** High computational overhead during the parse phase. May push the `0.0452 ms/req` performance benchmark over our 10ms budget.
- **Acceptance Criteria:**
  - Integrate a lightweight TF-IDF or embedding-based log clustering algorithm.
  - Run the algorithm asynchronously or cache the embedding model to strictly maintain the 10ms execution budget.
