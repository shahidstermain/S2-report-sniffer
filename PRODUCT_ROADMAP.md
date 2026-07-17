# S2 Report Sniffer — Product and Engineering Roadmap

## Strategic direction

**Core thesis:** reliable parsing and evidence-based analysis of real SingleStore Cluster Reports is the product moat. Interface quality, packaging, and integrations should strengthen that core rather than obscure it.

The roadmap priorities are:

1. Improve Cluster Report ingestion, parser coverage, and correctness.
2. Expand SingleStore-specific findings with verified evidence and recommended actions.
3. Make investigation workflows faster through evidence navigation and Cluster Report comparison.
4. Preserve local-first and air-gapped operation.
5. Maintain a polished desktop experience across macOS, Windows, and Linux.

All user-facing work must follow [`docs/TERMINOLOGY.md`](docs/TERMINOLOGY.md).

---

## Current product baseline

### Implemented foundation

- Vite + React frontend with gradual TypeScript adoption.
- FastAPI backend with bounded archive extraction and streaming parsing.
- Local SQLite/filesystem persistence under `S2RS_DATA_DIR`.
- Electron desktop packaging with macOS, Windows, and Linux targets.
- Optional pre-storage anonymization.
- Opt-in local usage analytics.
- Signed-release and update-channel infrastructure.

### Implemented investigation capabilities

- Cluster and node overview.
- Cluster Health Score and A–F triage grade.
- Prioritized findings with evidence, grounding, confidence, and recommended actions.
- Tracelog search with raw context windows and parsed fallback.
- Cluster topology and partition distribution.
- Memory, disk, backup, replication, workload, processlist, and configuration analysis.
- Long-Running Queries and queries above Sniffer elapsed-time thresholds.
- Long-running transaction and lock-contention analysis.
- Extended diagnostics from `MV_EVENTS`, sysinfo, CPU, network, compilation, pipeline, and table-skew collectors.
- Query Tracer candidate, timeline, and flow views.
- Cluster Report comparison.
- Local Glean incident-packet handoff.

---

## Phase 1 — Correctness and terminology hardening

### 1.1 Cluster Report terminology

**Status:** In progress.

- Standardize user-facing language against current SingleStore documentation.
- Use **SingleStore Cluster Report** rather than diagnostic/support/report bundle.
- Use **Long-Running Queries** rather than Runaway Queries.
- Clearly label Sniffer-defined thresholds and scoring as heuristics.
- Preserve stable API fields and checker IDs for backward compatibility.
- Add automated terminology tests and presentation-boundary normalization.

### 1.2 Analysis correctness

- Continue validating parser output against real multi-node Cluster Reports.
- Never show measured-looking zeroes when a collector is absent.
- Keep Cluster Health Score and grades backend-owned.
- Verify all thresholds through documentation, Toolbox defaults, or clearly labeled heuristics.
- Expand regression fixtures for sparse, partial, malformed, and very large reports.

### 1.3 Evidence quality

- Every finding should expose:
  - affected nodes
  - evidence source
  - observed value
  - criterion or heuristic basis
  - recommended action
  - relevant documentation link when verified
- Improve direct navigation from a finding to the related tracelog, node, query, transaction, or configuration row.

---

## Phase 2 — Investigation workflow improvements

### 2.1 Evidence navigation

- Add consistent **View in Logs**, **View Node**, **View Query**, and **View Configuration** actions.
- Preserve search terms that appear in actual tracelogs rather than checker IDs.
- Highlight evidence lines and retain surrounding context.
- Add breadcrumbs back to the originating finding.

### 2.2 Cluster Report comparison

- Improve chronological comparison of two Cluster Reports.
- Add categorized views for:
  - new findings
  - resolved findings
  - worsened findings
  - topology changes
  - configuration changes
  - workload and metric changes
- Surface whether observed changes support or contradict the intended remediation.

### 2.3 Query investigation

- Expand Query Tracer with additional documented signal sources:
  - `MV_ACTIVITIES`
  - `MV_FINISHED_TASKS`
  - `MV_PLANCACHE` / `PLANCACHE`
  - workload management status
  - Visual Explain / `EXPLAIN` / `PROFILE` imports where available
- Keep static-snapshot confidence visible at every stage.
- Distinguish cluster-wide `MV_PROCESSLIST` from per-node `information_schema.PROCESSLIST`.

### 2.4 Desktop workflow polish

- Improve empty states, progressive disclosure, keyboard navigation, and large-table usability.
- Add consistent terminology to menus, dialogs, update messages, and installer metadata.
- Continue accessibility and reduced-motion support.

---

## Phase 3 — Parser and finding expansion

### 3.1 Resource pressure

- Refine memory-pressure correlation across engine memory, host RAM, swap, OOM, and allocation contexts.
- Improve storage analysis across disk utilization, latency, bandwidth, and Universal Storage signals where present.
- Add confidence-aware handling of missing collectors.

### 3.2 Replication and availability

- Improve replica lag, synchronous-to-asynchronous transition, and partition-availability correlation.
- Expand node-state transition and failover narratives using `MV_EVENTS` and tracelog evidence.
- Validate availability-group and master/replica partition terminology in all visible output.

### 3.3 Workload Management and resource pools

- Correlate queued queries, resource pools, workload management status, and high-memory query activity.
- Distinguish Long-Running Queries from queries waiting on locks or workload management.
- Avoid universal “slow query” classifications; always state the observed duration and Sniffer threshold.

### 3.4 Backup and recovery

- Expand backup reliability, duration, freshness, and restore-point analysis.
- Add clearer differentiation between failed, stale, incomplete, and currently running backups.
- Ground recommended actions in current SingleStore backup documentation.

---

## Phase 4 — Performance and scale

### 4.1 Large Cluster Reports

- Profile multi-gigabyte Cluster Reports on representative hardware.
- Reduce peak extraction, parsing, and indexing memory.
- Add clearer progress stages and cancellation behavior.
- Optimize tracelog indexing and search for high-volume multi-node reports.

### 4.2 Storage and retention

- Add configurable retention policies.
- Make retained raw tracelog size and cleanup state visible.
- Provide safe export/import of anonymized investigation workspaces.

### 4.3 Test scale

- Add synthetic large-report generators.
- Add performance budgets for parser throughput, memory, and frontend rendering.
- Validate desktop packaging against clean operating-system images.

---

## Phase 5 — Release and operational maturity

- Complete production code signing and notarization for every supported platform.
- Validate anonymous access to update assets from the selected release provider.
- Add rollback and update-channel documentation.
- Maintain air-gap verification as a release gate.
- Add release notes that use the canonical terminology guide.

---

## Quality gates

Every feature branch should satisfy the relevant gates:

### Backend

```bash
cd backend
.venv/bin/python -m pytest
```

### Frontend

```bash
cd frontend
npm test
npm run build
```

### Security and packaging

- Bandit and dependency audit gates pass.
- Archive traversal and decompression protections remain intact.
- Desktop packaging verifies signatures where signing is enabled.
- No customer Cluster Reports, tracelogs, credentials, or local data are committed.

---

## Success metrics

- Reduced time from Cluster Report import to a grounded investigation hypothesis.
- Higher percentage of findings with direct evidence navigation.
- No user-facing legacy terms identified by terminology tests or review.
- Stable processing of multi-gigabyte Cluster Reports without unbounded memory growth.
- Consistent results across repeated analysis of the same report.
- Desktop installers start reliably and preserve local data across updates.

---

## Near-term priorities

1. Complete the repository-wide terminology audit.
2. Run frontend tests and production build for terminology normalization.
3. Improve direct finding-to-evidence navigation.
4. Expand real Cluster Report regression coverage.
5. Profile ingestion and tracelog search on large multi-node reports.
