# Project Plan: Checker Alignment and Verification

## Objective
Align and verify the diagnostic checkers in S2 Report Sniffer according to SingleStore and `sdb-admin check` rules, expand the test suite, ensure compatibility, and perform a full verification audit.

## Milestones

### Milestone 1: Exploration & Gap Analysis
- **Goal**: Analyze existing diagnostic check logic and identify discrepancies with official SingleStore and `sdb-admin check` guidelines.
- **Tasks**:
  - Spawn an Explorer subagent to inspect `backend/superchecker.py` and `backend/parsers.py` (focusing on THP, vm.swappiness, vm.overcommit_memory, vm.max_map_count, etc.).
  - Identify discrepancies and draft proposed threshold/severity updates.
  - Check `validators.py`, `monitoring.py`, and `storage.py` for integration points.
- **Deliverables**: Detailed exploration report pointing out required changes.

### Milestone 2: Implementation & Alignment
- **Goal**: Align logic, thresholds, and severity scoring of diagnostic checkers.
- **Tasks**:
  - Spawn a Worker subagent to update check logic in `backend/superchecker.py` and `backend/parsers.py`.
  - Propagate changes to `validators.py`, `monitoring.py`, and `storage.py` to maintain compatibility and schema integrity.
  - Verify that no data persistence/API errors are introduced.
- **Deliverables**: Code modifications aligning checkers.

### Milestone 3: Test Expansion & Verification
- **Goal**: Verify updated checkers via a comprehensive test suite.
- **Tasks**:
  - Spawn a Challenger/Worker to run the existing pytest suite and expand tests in `test_superchecker.py` and `test_parsers.py` to cover the new thresholds (healthy, warning, critical).
  - Spawn a Reviewer to verify correctness and correctness verification.
- **Deliverables**: Expanded pytest suite and execution results.

### Milestone 4: Forensic Audit & Handoff
- **Goal**: Conduct a final forensic audit to ensure absolute integrity and prepare the handoff report.
- **Tasks**:
  - Spawn a Forensic Auditor to run integrity checks.
  - Compile the final handoff report.
- **Deliverables**: Clean audit report and `handoff.md`.
