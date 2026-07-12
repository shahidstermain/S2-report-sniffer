# Exploration & Gap Analysis Report: OS Diagnostic Checks

**Date**: 2026-07-12  
**Explorer**: Checker Explorer 1  
**Target Files**: `backend/parsers.py`, `backend/superchecker.py`  

---

## 1. Executive Summary

This report reviews the system diagnostic checks in the `S2 Report Sniffer` codebase, focusing on OS settings (THP, `vm.swappiness`, `vm.max_map_count`, `vm.overcommit_*`, network sockets, and process limits) and aligning them with official SingleStore and `sdb-admin check` requirements. 

Our analysis revealed several critical discrepancies, redundancies, and integration gaps:
1. **Validation Threshold Mismatch**: Several settings (e.g., `vm.swappiness`, `vm.max_map_count`, `nofile` limits) use different healthy thresholds in `parsers.py` (which powers the Config Health UI) vs. `superchecker.py` (which generates the Recommendations list), causing inconsistent dashboard views.
2. **Redundant Rules and Duplicate Findings**: There are overlapping checker functions for `vm.swappiness` and `vm.max_map_count` in `superchecker.py` that use different checker IDs (`maxMapCount` vs `vmMaxMapCount`) and trigger redundant recommendations for the same host.
3. **Dead Code / Missing Integration**: An entire block of kernel compatibility checks in `superchecker.py` (checking `vm.min_free_kbytes`, `kernel.sched_rt_runtime_us`, memory/disk bandwidths, and block alignment) queries a non-existent `sys_info` dictionary. Because `parsers.py` never populates this data, these checks are completely non-functional.
4. **THP Parsing Weakness**: The Transparent Huge Pages parser fails to validate `defrag` status during its status mapping, and false positives occur in `superchecker.py` when raw configuration strings are missing (e.g., in parsed JSON imports).

---

## 2. Metric-by-Metric Gap Analysis

Below is a detailed analysis of each OS parameter, highlighting its SingleStore/`sdb-admin check` expectation, current codebase behavior, and identified gaps.

### A. Transparent Huge Pages (THP)
*   **Official SingleStore Requirement**: Both `enabled` and `defrag` kernel parameters must be set to `never`.
*   **Current Codebase Logic**:
    *   `parsers.py` (`parse_thp` at line 873) reads `enabled` and sets the node's `status` to `"disabled"` only if `enabled` is `never`. It ignores the status of `defrag`.
    *   `parsers.py` (`build_config_health` at line 2652) flags THP if `status != "disabled"`. Since `defrag` is ignored, this check passes even if `defrag` is enabled (e.g., set to `always`).
    *   `superchecker.py` (`_check_preinstall_kernel_memory_network` at line 1245) triggers a critical finding if `"[never]"` is missing from either `enabled` or `defrag`.
*   **Identified Gap**:
    *   **Dashboard Conflict**: If `enabled` is `never` but `defrag` is `always`, the Config Health UI shows THP as **passing** (green), but the Recommendations tab flags it as a **critical failure** (red).
    *   **False Positives**: If the raw configuration strings (`enabled` and `defrag`) are absent in the node payload (e.g., during database import or mock tests where only parsed fields exist), `superchecker.py` fails back to an empty string `""` and triggers a warning, ignoring the already-parsed `status="disabled"` flag.

### B. `vm.swappiness`
*   **Official SingleStore Requirement**: Set to a low, non-zero value, typically between `1` and `10` inclusive. Setting it to `0` is not recommended by SingleStore because it risks memory allocation stalls and premature OOM kills without utilizing swap space.
*   **Current Codebase Logic**:
    *   `parsers.py` (`parse_sysctl_checks` at line 903) defines `"vm.swappiness": {"max": 1, "severity": "warning"}`. It treats any value `> 1` as a warning and `0` as passing.
    *   `superchecker.py` (`_check_preinstall_kernel_memory_network` at line 1292) warns if `swapn == 0 or swapn > 10`. (Correctly allows 1-10).
    *   `superchecker.py` (`_check_memory_pressure_indicators` at line 2063) warns if `sv > 1`. (Only allows 0-1).
*   **Identified Gap**:
    *   **Threshold Conflict**: A recommended value of `10` triggers a warning in the parser and `_check_memory_pressure_indicators`, but passes in `_check_preinstall_kernel_memory_network`. A value of `0` passes in the parser, but triggers a warning in `_check_preinstall_kernel_memory_network`.
    *   **Redundant Findings**: If swappiness is `60`, both checkers inside `superchecker.py` trigger separately, adding two identical `vmSwappiness` recommendations for the same host.

### C. `vm.max_map_count`
*   **Official SingleStore Requirement**: Set to at least `1,000,000,000` (1 billion) to accommodate the high number of memory maps required by modern SingleStore database engines.
*   **Current Codebase Logic**:
    *   `parsers.py` (`parse_sysctl_checks` at line 902) defines `"vm.max_map_count": {"min": 1000000, "severity": "critical"}`. It passes any value `>= 1,000,000` (1 million).
    *   `superchecker.py` checks `< 1,000,000,000` (1 billion) in both `_check_preinstall_kernel_memory_network` (line 1261) and `_check_memory_pressure_indicators` (line 2083).
*   **Identified Gap**:
    *   **Threshold Conflict**: If `vm.max_map_count` is `5,000,000`, the Config Health UI shows it as **passing** (since it is above 1M), but the Recommendations engine flags it as a **critical failure** (since it is below 1B).
    *   **Checker ID Duplication**: The checkers use two different IDs for the same issue: `maxMapCount` in one function and `vmMaxMapCount` in the other. This prevents deduplication and results in duplicate warnings.

### D. `vm.overcommit_memory` and `vm.overcommit_ratio`
*   **Official SingleStore Requirement**: `vm.overcommit_memory` must be set to `2` for production stability. `vm.overcommit_ratio` is recommended to be set to `90`.
*   **Current Codebase Logic**:
    *   `parsers.py` defines `"vm.overcommit_memory": {"info": True}` and `"vm.overcommit_ratio": {"info": True}`. They are treated as info fields and never validated in the Config Health UI.
    *   `superchecker.py` (`_check_preinstall_kernel_memory_network` at line 1277) triggers a warning (`vmOvercommit`) if `overcommit_memory` is `0` or `1`.
*   **Identified Gap**:
    *   The UI Config Health tab cannot display a fail/warn status for non-recommended overcommit configurations because the parser does not validate them.

### E. Network Sockets (`net.core.somaxconn`, `net.core.wmem_max`, `net.core.rmem_max`)
*   **Official SingleStore Requirement**: `somaxconn` must be `>= 1024` (preferably `4096`). `wmem_max` and `rmem_max` must be at least `8,388,608` (8 MB).
*   **Current Codebase Logic**:
    *   `parsers.py` validates `somaxconn` against `min: 1024`, but marks `wmem_max` and `rmem_max` as `"info": True` (no validation).
    *   `superchecker.py` has no checker for `somaxconn` but checks `wmem_max` and `rmem_max` against `< 8 * 1024 * 1024` in `_check_network_buffers_max`.
*   **Identified Gap**:
    *   **Config Health vs Recommendations Inversion**: `somaxconn` is validated in Config Health but has no recommendation checker. Conversely, `wmem_max`/`rmem_max` are not validated in Config Health but have a recommendation checker.

### F. Process Limits (`nofile` Open Files and `nproc` Max Processes)
*   **Official SingleStore Requirement**: Hard and soft limit for `nofile` must be `>= 1,024,000`. Hard and soft limit for `nproc` must be `>= 128,000`.
*   **Current Codebase Logic**:
    *   `parsers.py` (`build_config_health` at line 2675) checks `0 < open_files_soft < 100000` (100k) and flags it as a failure.
    *   `superchecker.py` (`_check_process_limits_and_processes` at line 1444) checks if `hard < 1_024_000` and flags it as a critical failure.
*   **Identified Gap**:
    *   **Threshold Conflict**: A soft limit of `150,000` passes in the UI Config Health tab (since it is above 100k) but triggers a critical warning in the Recommendations tab (since it is below 1,024,000).

### G. Dead Code / Unpopulated `sys_info` Checks
*   **Current Codebase Logic**:
    *   `superchecker.py` (`_check_compatibility_inputs` starting at line 213) extracts `sys_info = metrics.get("sys_info", {})` from each node's metrics.
    *   It then runs checks for:
        *   `vm.min_free_kbytes` (expects `>= 153600`) -> `minFreeKbytes`
        *   `cpu_memory_bandwidth` (expects no `"low"`) -> `cpuMemoryBandwidth`
        *   `disk_bandwidth` (expects no `"low"`) -> `diskBandwidth`
        *   `kernel.sched_rt_runtime_us` (expects `>= 950000`) -> `maxNicePriority`
        *   `partitions_start` (expects no `"unaligned"`) -> `partitionsConsistency`
        *   `installed_permissions` (expects no `"fail"`) -> `installedPermissions`
        *   `cgroup_memory` (expects no `"enabled"`) -> `cgroupDisabled`
*   **Identified Gap**:
    *   **Dead Code**: In `parsers.py`, there is no parser code that writes to the `sys_info` key. The database metrics are parsed into a key named `sysinfo` (without underscore) which holds SQL tables, but has none of these keys. Thus, `sys_info` is always empty, and **none of these seven checkers can ever execute or fire in production**.

---

## 3. Proposed Fix Strategy

To resolve these misalignments and gaps, we propose the following implementation strategy for the next phase.

### Phase 1: Align Parsers (`backend/parsers.py`)

#### 1. Align `parse_sysctl_checks` (Lines 901-909)
Update the validation criteria to allow correct ranges, enable validation for overcommit values, and add sysctl variables for `vm.min_free_kbytes` and `kernel.sched_rt_runtime_us`:

```python
    key_params = {
        "vm.max_map_count": {"min": 1000000000, "severity": "critical"},
        "vm.swappiness": {"min": 1, "max": 10, "severity": "warning"},
        "net.core.somaxconn": {"min": 1024, "severity": "warning"},
        "net.core.wmem_max": {"min": 8388608, "severity": "warning"},
        "net.core.rmem_max": {"min": 8388608, "severity": "warning"},
        "vm.overcommit_memory": {"min": 2, "max": 2, "severity": "warning"},
        "vm.overcommit_ratio": {"min": 90, "max": 90, "severity": "warning"},
        "vm.min_free_kbytes": {"min": 153600, "severity": "warning"},
        "kernel.sched_rt_runtime_us": {"min": 950000, "severity": "warning"},
    }
```

#### 2. Align `build_config_health` for Process Limits (Lines 2675-2680)
Align the Config Health check for `nofile` to use the standard `1,024,000` limit:

```python
    # Process limits
    low_nofile = {h: v for h, v in process_limits_checks.items() if 0 < v < 1024000}
```

#### 3. Update `parse_thp` Status (Line 892)
Ensure that the status calculation considers both `enabled` and `defrag` being set to `never`:

```python
    enabled_active = result.get("active_enabled", "unknown")
    if "enabled" in result:
        m = re.search(r'\[(\w+)\]', result["enabled"])
        enabled_active = m.group(1) if m else "unknown"
        result["active"] = enabled_active

    defrag_active = "unknown"
    if "defrag" in result:
        m = re.search(r'\[(\w+)\]', result["defrag"])
        defrag_active = m.group(1) if m else "unknown"
        result["active_defrag"] = defrag_active

    if enabled_active == "never" and defrag_active == "never":
        result["status"] = "disabled"
    else:
        result["status"] = "enabled"
```

---

### Phase 2: Align Superchecker (`backend/superchecker.py`)

#### 1. Consolidate and Align `_check_memory_pressure_indicators` (Lines 2057-2095)
Modify this method to prevent conflicting thresholds and deduplicate finding additions by checking if a finding has already been added:

```python
            swappiness = info.get("vm_swappiness")
            if swappiness is not None:
                try:
                    sv = int(swappiness)
                except (TypeError, ValueError):
                    sv = -1
                if sv < 1 or sv > 10:  # Aligned threshold
                    self._add_unique(
                        checker_id="vmSwappiness",
                        severity="warning",
                        ...
                    )
```
Change `vmMaxMapCount` checker ID to use `maxMapCount` consistently, matching `_check_preinstall_kernel_memory_network`:
```python
                if 0 < mmc < 1_000_000_000:
                    self._add_unique(
                        checker_id="maxMapCount",  # Consolidated ID
                        severity="critical",
                        ...
                    )
```

#### 2. Implement `_add_unique` Helper (Lines 134-162)
Add a helper in `SuperChecker` to avoid duplicate findings for the same host:
```python
    def _add_unique(self, checker_id: str, severity: str, category: str, title: str, 
                    description: str, evidence: str, remediation: str, confidence: float = 0.8, 
                    nodes=None, related_views=None, tags=None, doc_link: str = ""):
        nodes = sorted(set(nodes or []))
        for f in self.findings:
            if f["checker_id"] == checker_id and set(f["nodes"]) == set(nodes):
                # Update evidence if more detailed, but do not append duplicate
                if len(evidence) > len(f["evidence"]):
                    f["evidence"] = evidence
                return
        self._add(checker_id, severity, category, title, description, evidence, 
                  remediation, confidence, nodes, related_views, tags, doc_link)
```

#### 3. Update `_check_preinstall_kernel_memory_network` for THP Robustness (Lines 1245-1258)
Add fallback parsing in the superchecker for instances where raw configuration files are missing:
```python
            thp = node.get("os_checks", {}).get("thp", {}) or {}
            enabled = str(thp.get("enabled", ""))
            defrag = str(thp.get("defrag", ""))
            
            # Robust verification falling back to parsed flags
            is_enabled_never = "[never]" in enabled or thp.get("active") == "never" or thp.get("status") == "disabled"
            is_defrag_never = "[never]" in defrag or thp.get("active_defrag") == "never" or thp.get("status") == "disabled"
            
            if not (is_enabled_never and is_defrag_never):
                self._add_unique(
                    checker_id="transparentHugepage",
                    severity="critical",
                    ...
                )
```

#### 4. Revive Dead Code for `sys_info` (Lines 213-308)
To revive the unpopulated compatibility checks, map these fields in `parsers.py` (e.g. in `parse_node_directory`) to `node["metrics"]["sys_info"]` using values retrieved from the parsed `sysctl` dictionary and support bundle tables:

```python
    # Inside parse_node_directory inside parsers.py:
    sysctl_data = node["os_checks"].get("sysctl", {})
    node["metrics"]["sys_info"] = {
        "vm.min_free_kbytes": (sysctl_data.get("vm.min_free_kbytes") or {}).get("value"),
        "kernel.sched_rt_runtime_us": (sysctl_data.get("kernel.sched_rt_runtime_us") or {}).get("value"),
        # Map additional hardware metrics extracted from benchmark files if present
        "cpu_memory_bandwidth": "normal", # Example placeholder
        "disk_bandwidth": "normal",       # Example placeholder
        "partitions_start": "aligned",    # Example placeholder
        "installed_permissions": "pass",  # Example placeholder
        "cgroup_memory": "disabled",      # Example placeholder
    }
```
Alternatively, update `_check_compatibility_inputs` in `superchecker.py` to directly fetch `vm.min_free_kbytes` and `kernel.sched_rt_runtime_us` from the parsed `node["os_checks"]["sysctl"]` dictionary.

#### 5. Add `net.core.somaxconn` Checker in Superchecker
Add a checker for `somaxconnLimit` in `superchecker.py` within `_check_preinstall_kernel_memory_network`:
```python
            somax = _to_float((sysctl.get("net.core.somaxconn") or {}).get("numeric"))
            if somax and somax < 1024:
                self._add_unique(
                    checker_id="somaxconnLimit",
                    severity="warning",
                    category="Environment",
                    title=f"net.core.somaxconn too low on {host}",
                    description="Low somaxconn limits maximum connection backlog queue, which can cause connection timeouts under high spikes.",
                    evidence=f"net.core.somaxconn={int(somax)} (required >= 1024)",
                    remediation="Set net.core.somaxconn=1024 in /etc/sysctl.conf.",
                    confidence=0.85,
                    nodes=[host],
                    related_views=["sysctl"],
                    tags={"environment", "network"},
                )
```

---

## 4. Verification Methods

1.  **Direct Unit Testing of `parse_sysctl_checks`**:
    Implement the `TestSysctlChecks` class in `test_parsers.py` to verify that values are correctly categorized as `pass`, `warn`, or `fail` according to the aligned thresholds.
2.  **Rule Integration Testing in `test_superchecker.py`**:
    Implement range-based tests (like `test_swappiness_alignment_healthy` and `test_swappiness_alignment_unhealthy`) to verify that the superchecker fires or passes cleanly.
3.  **Run All Tests**:
    Ensure the test suite is executed and all tests pass:
    `cd backend && .venv/bin/python -m pytest test_parsers.py test_superchecker.py -v`
