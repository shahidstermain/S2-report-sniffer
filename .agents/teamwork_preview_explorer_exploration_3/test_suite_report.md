# Backend Test Suite Analysis & Expansion Proposal

## 1. Executive Summary
This report analyzes the existing backend test suite in the `S2 Report Sniffer` codebase, focusing on `backend/test_superchecker.py` and `backend/test_parsers.py`. It details the existing test coverage, the mock data paradigms (inline dicts, temporary directories, ZIP/TAR archive generators) currently utilized, and identifies critical discrepancies between how OS settings (THP, `vm.swappiness`, `vm.max_map_count`, `vm.overcommit_*`) are handled by parsers and the superchecker. Finally, it outlines a concrete proposal for expanding the test suite to verify the aligned rules, thresholds, and severity changes.

---

## 2. Overview of Existing Tests

The backend test suite consists of 20 test files (~286 tests), with the core validation, parsing, and rule-scoring verified primarily by two files:

### A. `backend/test_superchecker.py` (52 tests, pytest-based)
This file tests the rule execution engine (`run_superchecker`). It evaluates whether specific parsed report payloads generate the correct diagnostic findings (checking `checker_id` and `severity`). 
*   **Methodology**: Constructs dictionary mock objects simulating parsed reports (representing node metrics, schema tables, replication statuses, log summaries, etc.).
*   **Threshold/Severity Testing**: Asserts that if certain thresholds are crossed, findings with expected checker IDs and severities (e.g. `critical`, `warning`, `info`) are appended to the results.
*   **Key Checker Categories Tested**:
    *   **Memory Settings/Pressure**: `clusterMemoryUsage`, `dmesgOOMKill`, `vmSwappiness`, `vmMaxMapCount`, `swapUsageDetected`, `memoryUtilizationCritical`, `memoryUtilizationWarning`.
    *   **Availability & Replication**: `leavesNotOnline`, `replicationLag`, `replicationLagCritical`, `replicationLagDegraded`, `asyncTransitionDetected`, `firewallPortBlocking`, `unkillableTransaction`.
    *   **Storage**: `diskUsage`, `diskInodesUsage`, `diskLatencyRead`/`diskLatencyWrite`, `pressureEvents_fsync_behind`.
    *   **Queries & Transactions**: `blockedQueries`, `queuedQueries`, `highActiveQueryCount`, `sleepingOpenTransactions`, `runawayQueries`, `slowQueries`, `repeatedQueryPatterns`, `highQueryMemoryUsage`, `longRunningTransactions`, `lockContention`, `severeLockContention`.
    *   **Configuration & Scheduling**: `orphanDatabases`, `delayedThreadLaunches`, `backupReliability`, `pressureEvents_etimedout`.

### B. `backend/test_parsers.py` (~50 tests, unittest-based)
This file tests individual parsing functions and helpers defined in `backend/parsers.py` (such as converting raw files, dmesg lines, and system metrics into structured report structures).
*   **Methodology**: Focuses on fine-grained logic checks of functions, mocking the underlying command output files or logs.
*   **Key Functionalities Tested**:
    *   `generate_recommendations`: Generates HTML/markdown recommendations from report models (e.g., THP, disk space, version mismatch).
    *   `detect_log_patterns`: Matches critical logs (OOM, disk full, crash tracebacks).
    *   `classify_dmesg_events`: Identifies OOMs, storage faults, and THP lines.
    *   `extract_alloc_memory_metrics` & `build_alloc_memory_overview`
    *   `parse_free` & `parse_df`
    *   `extract_node_events` (MV_EVENTS parsing)
    *   `extract_query_patterns` & `extract_replication_lag_patterns`
    *   `extract_memory_utilization_trend` & `extract_long_running_transactions`

---

## 3. Mock Payloads and Support Bundles Used

Since S2 Report Sniffer runs in a local-first desktop/CLI environment, the test suite leverages three primary mock paradigms instead of using large static support bundle archives:

1.  **Inline Mock Dictionaries (Report Payloads)**:
    Most tests in `test_superchecker.py` and `TestRecommendationsEngine` in `test_parsers.py` construct mock `report` structures directly in Python:
    ```python
    report = {
        "nodes": [{
            "hostname": "node1",
            "metrics": {
                "memory": {"used_pct": 95, "total_mb": 100000}
            }
        }]
    }
    ```
2.  **On-the-Fly Temp Directories & Files**:
    Functions that parse command stdout files (e.g., `parse_free`, `parse_df`, `parse_rebalance_status`) are tested by creating temporary folders via `tempfile.mkdtemp` and writing raw string mock outputs to files like `free_stdout` or `df_stdout`:
    ```python
    root = Path(tempfile.mkdtemp(prefix="s2rs_free_"))
    node = root / "node-MA" / "free"
    node.mkdir(parents=True, exist_ok=True)
    (node / "free_stdout").write_text("Mem: 8192044 4096022 ...")
    ```
3.  **Mock Zip & Tar Archive Generator**:
    In integration tests (`test_parsers_integration.py` and `test_zip_parsing_variants.py`), the test suite dynamically creates ZIP/TAR archives representing complete bundles, writing JSON files (like `cluster.json` or `informationSchemaMvNodes.json`), config files (`memsql.cnf`), and log files (`tracelogs/memsql.log`) inside them. This tests directory layout traversal and decompression safety without checking in massive binary artifacts.

---

## 4. Identified Discrepancies and Gap Analysis

A forensic review of `parsers.py` and `superchecker.py` reveals several discrepancies and gaps concerning OS settings validation:

| OS Parameter | Current Parser (`parsers.py`) | Current Superchecker (`superchecker.py`) | Discrepancy / Alignment Gap | Recommended Alignment |
| :--- | :--- | :--- | :--- | :--- |
| **`vm.max_map_count`** | Requires `min: 1_000_000` to pass. Under 1M triggers status=`fail`/severity=`critical`. | Requires `>= 1_000_000_000` (1B). Under 1B triggers checker=`maxMapCount`/`vmMaxMapCount` (critical). | Discrepancy of **1000x**. A system with `500,000,000` will show "pass" in the parser UI checks, but trigger a critical superchecker alert. | Align parser min threshold to `1,000,000,000` (1 billion) to match `sdb-admin check` rules. |
| **`vm.swappiness`** | Requires `max: 1` to pass. Over 1 triggers status=`warn`/severity=`warning`. | Conflicting rules:<br>- In `_check_preinstall_kernel_memory_network`: warns if swappiness is `0` or `> 10`. (allows 1-10)<br>- In `_check_memory_pressure_indicators`: warns if swappiness is `> 1`. | Setting `vm.swappiness=10` is highly recommended by SingleStore to prevent OOMs while avoiding heavy paging. Flagging it as a warning is an error. | Align both parser and superchecker to allow `1` to `10` as healthy. Trigger warning only if `0` or `> 10`. |
| **`vm.overcommit_memory`** | Parsed only as `info`. No validation status. | Warns (`vmOvercommit`) if value is `0` or `1`. Recommended is `2`. | Validation is omitted in the parser, meaning it cannot show a red/green pass/fail status in the UI details for this setting. | Validate in parser with `"vm.overcommit_memory": {"min": 2, "max": 2, "severity": "warning"}`. |
| **`vm.overcommit_ratio`** | Parsed only as `info`. No validation status. | Warns if ratio is not near `90`. | Parser does not validate the value. | Validate in parser with `"vm.overcommit_ratio": {"min": 90, "max": 90, "severity": "warning"}`. |
| **Unit Test Coverage** | No direct unit tests for `parse_sysctl_checks` in `test_parsers.py`. | Has tests, but they use incorrect/conflicting thresholds (e.g. testing swappiness=0 doesn't assert warning status correctly). | **Lacks direct unit tests** for sysctl parsing, meaning rule changes inside `parsers.py` are unverified at the unit level. | Add `TestSysctlChecks` and expand `test_superchecker.py` to assert correct aligned states. |

---

## 5. Test Suite Expansion Proposal

To verify the updated checker rules, thresholds, and severities, we propose expanding the test suite in two phases: unit tests in `test_parsers.py` and rule-engine tests in `test_superchecker.py`.

### A. Propose `TestSysctlChecks` class in `backend/test_parsers.py`
This class will directly test `parse_sysctl_checks` by mocking the `sysctl` command output. It will verify that:
1.  Healthy values (swappiness=1-10, max_map_count=1B, overcommit_memory=2, overcommit_ratio=90) result in `status="pass"`.
2.  Unhealthy values trigger the correct `status` (`fail`/`warn`) and `severity`.

#### Proposed Test Code Structure:
```python
class TestSysctlChecks(unittest.TestCase):
    """Direct verification of sysctl parameter parsing and validation thresholds."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="s2rs_sysctl_")
        self.node_path = os.path.join(self.temp_dir, "node-MA")
        os.makedirs(self.node_path, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def _write_sysctl(self, lines: list[str]):
        sysctl_file = os.path.join(self.node_path, "sysctl")
        with open(sysctl_file, "w") as f:
            f.write("\n".join(lines))

    def test_sysctl_healthy_defaults(self):
        """Standard recommended values should pass."""
        self._write_sysctl([
            "vm.max_map_count = 1000000000",
            "vm.swappiness = 10",
            "vm.overcommit_memory = 2",
            "vm.overcommit_ratio = 90",
            "net.core.somaxconn = 2048"
        ])
        checks = parse_sysctl_checks(self.node_path)
        
        self.assertEqual(checks["vm.max_map_count"]["status"], "pass")
        self.assertEqual(checks["vm.swappiness"]["status"], "pass")
        self.assertEqual(checks["vm.overcommit_memory"]["status"], "pass")
        self.assertEqual(checks["vm.overcommit_ratio"]["status"], "pass")

    def test_sysctl_max_map_count_fail(self):
        """vm.max_map_count under 1,000,000,000 should fail as critical."""
        self._write_sysctl(["vm.max_map_count = 999999999"])
        checks = parse_sysctl_checks(self.node_path)
        self.assertEqual(checks["vm.max_map_count"]["status"], "fail")
        self.assertEqual(checks["vm.max_map_count"]["severity"], "critical")

    def test_sysctl_swappiness_warning_low(self):
        """vm.swappiness = 0 is a warning (setting to 0 risks OOM)."""
        self._write_sysctl(["vm.swappiness = 0"])
        checks = parse_sysctl_checks(self.node_path)
        self.assertEqual(checks["vm.swappiness"]["status"], "warn")
        self.assertEqual(checks["vm.swappiness"]["severity"], "warning")

    def test_sysctl_swappiness_warning_high(self):
        """vm.swappiness > 10 is a warning (risks latency from swapping)."""
        self._write_sysctl(["vm.swappiness = 15"])
        checks = parse_sysctl_checks(self.node_path)
        self.assertEqual(checks["vm.swappiness"]["status"], "warn")
        self.assertEqual(checks["vm.swappiness"]["severity"], "warning")
```

### B. Propose Expanded Tests in `backend/test_superchecker.py`
These additions will verify that the rule engine (`run_superchecker`) behaves correctly on the aligned thresholds. We must test both the `sysctl` path (`_check_preinstall_kernel_memory_network`) and the `memory_pressure` path (`_check_memory_pressure_indicators`).

#### Proposed Test Code Structure:
```python
def test_swappiness_alignment_healthy():
    """Verify swappiness=1-10 does not trigger warnings in either checker path."""
    for val in ["1", "10", 1, 10]:
        report = {
            "nodes": [{
                "hostname": "node1",
                "os_checks": {
                    "sysctl": {
                        "vm.swappiness": {"value": str(val), "numeric": int(val), "status": "pass"}
                    }
                }
            }],
            "memory_pressure": {
                "node1": {
                    "vm_swappiness": str(val)
                }
            }
        }
        findings = run_superchecker(report)
        sw = [f for f in findings if f["checker_id"] == "vmSwappiness"]
        assert not sw, f"Swappiness value {val} should be considered healthy and trigger no alerts."

def test_swappiness_alignment_unhealthy():
    """Verify swappiness = 0 and > 10 trigger warning in both checker paths."""
    for val in ["0", "15"]:
        report = {
            "nodes": [{
                "hostname": "node1",
                "os_checks": {
                    "sysctl": {
                        "vm.swappiness": {"value": val, "numeric": int(val), "status": "warn"}
                    }
                }
            }],
            "memory_pressure": {
                "node1": {
                    "vm_swappiness": val
                }
            }
        }
        findings = run_superchecker(report)
        sw = [f for f in findings if f["checker_id"] == "vmSwappiness"]
        assert sw, f"Swappiness value {val} should trigger vmSwappiness warning"
        assert sw[0]["severity"] == "warning"

def test_max_map_count_alignment():
    """Verify max_map_count below 1,000,000,000 is critical, and >= 1B is healthy."""
    # Test Healthy
    report_healthy = {
        "nodes": [{
            "hostname": "node1",
            "os_checks": {
                "sysctl": {
                    "vm.max_map_count": {"value": "1000000000", "numeric": 1000000000, "status": "pass"}
                }
            }
        }],
        "memory_pressure": {
            "node1": {"vm_max_map_count": 1000000000}
        }
    }
    findings = run_superchecker(report_healthy)
    assert not any(f["checker_id"] in ("maxMapCount", "vmMaxMapCount") for f in findings)

    # Test Unhealthy (e.g. 500,000,000)
    report_unhealthy = {
        "nodes": [{
            "hostname": "node1",
            "os_checks": {
                "sysctl": {
                    "vm.max_map_count": {"value": "500000000", "numeric": 500000000, "status": "fail"}
                }
            }
        }],
        "memory_pressure": {
            "node1": {"vm_max_map_count": 500000000}
        }
    }
    findings = run_superchecker(report_unhealthy)
    mmc = [f for f in findings if f["checker_id"] in ("maxMapCount", "vmMaxMapCount")]
    assert mmc
    assert all(f["severity"] == "critical" for f in mmc)
```

---

## 6. Implementation and Migration Strategy

To implement these aligned rules and corresponding tests, the following steps are recommended:
1.  **Update `backend/parsers.py`**:
    *   Change `"vm.max_map_count": {"min": 1000000}` to `"vm.max_map_count": {"min": 1000000000}`.
    *   Change `"vm.swappiness": {"max": 1}` validation rules to allow values in range `1 <= x <= 10`, setting status `"warn"` if outside this range.
    *   Add validation mappings for `vm.overcommit_memory` (expected=2) and `vm.overcommit_ratio` (expected=90).
2.  **Update `backend/superchecker.py`**:
    *   Align the rule logic in `_check_memory_pressure_indicators` to warn on swappiness `sv == 0 or sv > 10` rather than `sv > 1`, eliminating the internal conflict with `_check_preinstall_kernel_memory_network`.
3.  **Execute the Expanded Test Suite**:
    Run pytest with the new tests to verify behavior:
    `cd backend && .venv/bin/python -m pytest test_parsers.py test_superchecker.py -v`
