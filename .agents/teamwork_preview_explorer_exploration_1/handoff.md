# Handoff Report — Checker Exploration 1

## 1. Observation

- **`vm.swappiness` Inconsistency**:
  - `backend/parsers.py` at line 903: `"vm.swappiness": {"max": 1, "severity": "warning"}`
  - `backend/superchecker.py` at line 1292: `if swapn == 0 or swapn > 10:` (inside `_check_preinstall_kernel_memory_network`)
  - `backend/superchecker.py` at line 2063: `if sv > 1:` (inside `_check_memory_pressure_indicators`)
- **`vm.max_map_count` Inconsistency**:
  - `backend/parsers.py` at line 902: `"vm.max_map_count": {"min": 1000000, "severity": "critical"}`
  - `backend/superchecker.py` at line 1261: `if max_map and max_map < 1_000_000_000:`
  - `backend/superchecker.py` at line 2083: `if 0 < mmc < 1_000_000_000:`
- **THP Inconsistency**:
  - `backend/parsers.py` at line 892: `result["status"] = "disabled" if result.get("active") == "never" else "enabled"`
  - `backend/superchecker.py` at line 1245: `if "[never]" not in enabled or "[never]" not in defrag:`
- **Process Limits Inconsistency**:
  - `backend/parsers.py` at line 2675: `low_nofile = {h: v for h, v in process_limits_checks.items() if 0 < v < 100000}`
  - `backend/superchecker.py` at line 1444: `if hard and hard < 1_024_000:`
- **Dead Code for Compatibility Checks**:
  - `backend/superchecker.py` at line 216: `sys_info = metrics.get("sys_info", {})` and lines 219, 234, 249, 264, 279, 294, 342.
  - A grep search for `"sys_info"` in `backend/parsers.py` returned **zero results**, meaning `sys_info` is never populated.
- **Test execution results**:
  - Ran unit tests successfully using `.venv/bin/python -m pytest test_parsers.py test_superchecker.py -v` (177 passed in 0.09s).

---

## 2. Logic Chain

1. **Threshold/Severity Mismatches**:
   - `parsers.py` and `superchecker.py` use conflicting thresholds for the same parameters (`vm.swappiness`, `vm.max_map_count`, `nofile`).
   - Consequently, a system with recommended settings (e.g. `vm.swappiness=10`, `vm.max_map_count=50,000,000`, `nofile=150,000`) will pass the Config Health UI check (defined in `parsers.py`) but trigger a critical warning/error in the Recommendations engine (defined in `superchecker.py`).
2. **Redundant Checker Execution**:
   - `vm.swappiness` and `vm.max_map_count` are checked twice inside `superchecker.py` by two different methods using different checker IDs (`maxMapCount` vs `vmMaxMapCount`).
   - Since `SuperChecker._add` does not deduplicate findings, this results in duplicate warnings on the dashboard for the same host.
3. **Dead Code Verification**:
   - Since the key `sys_info` is never populated by `parsers.py` (which instead populates `sysinfo` with database schema metadata), all checks querying `sys_info` (such as `vm.min_free_kbytes` or SSD partition alignment) can never fire in production.
4. **THP defrag Vulnerability**:
   - `parse_thp` only verifies `enabled` and ignores `defrag` in its status calculation, allowing an enabled `defrag` configuration to bypass the Config Health check.

---

## 3. Caveats

- We did not audit database-level schema checks or query pattern rules, only OS/system parameters and system limits.
- Assumed standard SingleStore system requirements (THP = never/never, swappiness = 1-10, max_map_count = 1B, overcommit = 2, nofile = 1.02M) are the desired target alignment.

---

## 4. Conclusion

- Critical discrepancies exist between how system settings are validated in the UI config health tab vs the recommendations list.
- Seven system compatibility checks are currently dead code due to the unpopulated `sys_info` key.
- Proposed a two-phase alignment strategy: Phase 1 aligns thresholds and status mappings in `parsers.py`, and Phase 2 consolidates redundant checks and prevents duplication in `superchecker.py`.

---

## 5. Verification Method

- **Files to Inspect**: The complete analysis and proposed code changes are written in `/Users/shahidster-macmini/S2-report-sniffer/.agents/teamwork_preview_explorer_exploration_1/exploration_report.md`.
- **Test Commands**: Verify that existing and new tests pass by running:
  ```bash
  cd backend && .venv/bin/python -m pytest test_parsers.py test_superchecker.py -v
  ```
- **Invalidation Condition**: The dead-code finding would be invalidated if there is some preprocessing middleware or tool outside `parsers.py` that injects the `sys_info` dict into the report before it reaches `superchecker.py`. No such code was found in the backend module.
