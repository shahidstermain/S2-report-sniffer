# S2 Report Sniffer — Product & Engineering Roadmap

## Strategic Direction

**Core thesis:** S2-report-sniffer is the moat. Parsing + analyzing real support bundles is the hard, irreplaceable work. UI and deployment are solvable. We will:

1. **Advance S2-report-sniffer** as the primary product.
2. **Port UI components** from `singlestore-cluster-intelligence` (topology map, score breakdowns, polished card components).
3. **Eliminate technical debt** blocking velocity (private deps, end-of-life CRA, desktop packaging).
4. **Keep singlestore-cluster-intelligence** as a reference UI library and potential alternate deployment target in the future.

---

## Phase 1: Foundation & Debt Elimination (2 weeks)

### 1.1 Remove/Audit Private Dependencies

**Status:** `emergentintegrations==0.1.0` is already **commented out** in `requirements.txt` and not used in codebase ✅

**Remaining audit items:**
- `@emergentbase/visual-edits` in `frontend/devDependencies` — check if actually used in source
- If unused, remove it
- If used, document purpose and consider open replacement

```bash
# Action: grep frontend/src for visual-edits usage
grep -r "visual-edits" frontend/src/ || echo "Not used"
grep -r "emergentbase" frontend/src/ || echo "Not used"
```

**Deliverable:** Comment explaining why any remaining private deps exist (or remove them).

---

### 1.2 Frontend Build System Migration: CRA → Vite + TypeScript

**Current state:** `create-react-app` (CRA) + `@craco/craco` (old, slow rebuilds)

**Target:** Vite 5 + TypeScript (fast HMR, better DX, modern toolchain)

**Scope:**
- Initialize `vite.config.ts` + `tsconfig.json`
- Convert all `.js` → `.jsx` or `.ts` → `.tsx`
- Port env handling (`import.meta.env` instead of `process.env`)
- Validate all component imports/exports still work
- Confirm build size/performance improvements
- Update `AGENTS.md` and `dev-setup.sh` with new commands

**Effort estimate:** 3–4 days

**Why now:** CRA is in maintenance-only mode (React 19 support is minimal). Vite is the industry standard. Unblocks future React ecosystem upgrades and build perf.

**Test gate:**
```bash
npm run build  # Should complete in <30s
npm run preview  # Should load at http://localhost:4173
```

---

### 1.3 Document UI Components to Port

**From:** `singlestore-cluster-intelligence`

**Priority components:**
- Topology/cluster map visualization
- Animated score breakdown (risk gauge, confidence, severity)
- Polished recommendation/finding cards
- Workload chart variants (if better than recharts usage in S2-report-sniffer)

**Deliverable:** `frontend/COMPONENT_PORT_CHECKLIST.md` listing each component, source file, current usage in S2-report-sniffer, and porting steps.

---

## Phase 2: UI Modernization (3–4 weeks)

### 2.1 Port Topology & Cluster Map

**Current gap:** S2-report-sniffer shows `<ClusterOverview>` but no interactive topology.

**Target:** Interactive cluster node/partition map from `singlestore-cluster-intelligence`.

**Includes:**
- Node layout with partition distribution
- Role badges (master/leaf/aggregator)
- Real-time status color coding
- Hover state for detailed node info

**Test coverage:** Storybook story + visual regression test

---

### 2.2 Enhance Recommendation Cards

**Current:** Basic finding list with risk_score, confidence, fix_first.

**Target:** Animated severity gauge, related findings mini-graph, one-click "copy to Slack" per finding.

**Includes:**
- Severity bar chart animation (0–100 risk scale)
- Related findings breadcrumb chain
- Quick-action buttons (export, copy, snooze)

**Test coverage:** Playwright e2e for card interaction

---

### 2.3 Refactor Dashboard Pages for Consistency

Update `frontend/src/pages/ReportDashboard.jsx` and `ClusterOverview.jsx` to use new components cohesively.

**Test gate:** `npm run build && npm test` passes + visual diff review

---

## Phase 3: Backend Brain Expansion (Ongoing, starting week 3)

### 3.1 MVP: Network/Storage Pressure Indicators

**From AGENTS.md "High-value checks":**

Implement three quick wins to validate the parser → superchecker → UI pipeline:

**3.1.1 ETIMEDOUT hourly counts**
- Parse `*memsql.log` for `ETIMEDOUT` pattern
- Aggregate by hour, emit `etimedout_per_hour` dict in parser output
- Score in superchecker: if any hour >10 events, flag as `warning`
- Test in `backend/test_parsers.py` + `backend/test_superchecker.py`

**3.1.2 fsync is behind hourly counts**
- Similar to above, pattern `fsync is behind`
- Threshold: >5 per hour → `warning` + related to ETIMEDOUT

**3.1.3 Retry loop is stalling detection**
- Pattern `Retry loop is stalling`
- Presence of any event → `info` (informational, not urgent)

**Deliverable:**
- Parser signals in `backend/parsers.py`
- Superchecker rules in `backend/superchecker.py`
- 3 new test cases per rule in `backend/test_superchecker.py`
- UI update to show these in recommendations list
- AGENTS.md updated with new rule IDs and confidence scores

**Effort estimate:** 3–5 days (tightly scoped)

---

### 3.2 Log Timeframe Detection

**Goal:** Quick report coverage confidence signal.

**Per node (Master, Leaf, Aggregator):**
- Extract `first_log_entry` (earliest timestamp)
- Extract `last_log_entry` (latest timestamp)
- Compute span (hours/days)
- Emit `log_coverage_hours` per node

**Score in superchecker:**
- If any node log span <1 hour → `info` (incomplete coverage)
- If all nodes <4 hours → `warning` (snapshot, not trend)

**Test gate:** Existing test bundles should parse and emit timeframe signals correctly.

---

### 3.3 Backup Reliability Summary

**From logs + info schema:**
- Count backup `BACKUP DATABASE` start events
- Count `Done taking a distributed backup` (success) + `Failed` (fail)
- From `mv-backup-history.tsv`: extract latest success/fail duration

**Emit:**
```python
{
  "backup_success_count": int,
  "backup_failure_count": int,
  "backup_failure_rate": float (0..1),
  "latest_backup_duration_sec": int,
  "backup_reliability": "critical|warning|ok"  # score result
}
```

**Superchecker scoring:**
- failure_rate >10% → `warning`, suggest review backup logs
- latest_duration >3600s → `info`, potential slow backups

---

## Phase 4: Desktop Packaging (2 weeks, Week 5+)

### 4.1 Finalize Electron + Auto-Update

**From:** Lessons learned in this session, Desktop CI/CD.

**Includes:**
- PyInstaller backend executable bundle
- Webpack frontend static asset bundle
- Code signing (macOS + Windows)
- Auto-update via Squirrel/electron-updater
- Offline mode: SQLite + local file storage (already designed in AGENTS.md)

**Deliverable:** Signed installers for macOS (DMG) + Windows (MSI) + Linux (AppImage) in CI/CD pipeline.

**Test gate:** `AIRGAP_TEST_PROTOCOL.md` runs successfully on clean machines.

---

## Implementation Order (Strict Sequencing)

| Week | Task | Owner | Gate |
|------|------|-------|------|
| 1–2 | Audit private deps + frontend build migration start | FE | `npm run build` <30s |
| 2–3 | Vite + TypeScript cutover complete | FE | All existing tests pass |
| 3–4 | Port topology map + card components | FE | Storybook + visual tests |
| 3–5 | MVP superchecker rules (ETIMEDOUT/fsync/retry) | BE | `backend/test_superchecker.py` ✅ |
| 4–5 | Log timeframe detection | BE | Parser tests + UI integration |
| 5–6 | Backup reliability summary | BE | Parser tests + UI integration |
| 6–7 | Desktop packaging final push | DevOps | Signed installers in CI/CD |

---

## Success Metrics

- ✅ Frontend build time <30s (Vite vs CRA)
- ✅ All 3 MVP parser rules pass backend tests
- ✅ Recommendation card renders new signals correctly in UI
- ✅ Desktop installer boots and processes a test bundle offline
- ✅ New AGENTS.md reflects all implemented checks with stable IDs

---

## Docs Updates (Continuous)

- `AGENTS.md`: Add each new check ID, signal family, confidence score
- `frontend/COMPONENT_PORT_CHECKLIST.md`: Track UI ports
- `README.md`: Update build commands (Vite instead of CRA)
- `USER_MANUAL.md`: Desktop installer walkthrough
- `PACKAGING.md`: Electron + code signing process

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Vite migration breaks existing routes | Keep feature branches short; run full smoke tests before main merge |
| Private deps block CI/CD | Audit now; document any unavoidable deps; consider vendoring |
| UI port misses key design | Reference singlestore-cluster-intelligence in Figma or screenshots; ask design review |
| Desktop packaging bloats binary | Profile PyInstaller output; use `--onefile` + UPX if needed |
| SuperChecker rule changes break existing tests | New rules land with test cases; existing tests never removed |

---

## Next Steps (This Week)

1. **Execute Phase 1.1:** Confirm private deps audit (likely 30min).
2. **Create feature branch:** `feat/vite-migration`.
3. **Sketch Phase 2.1:** List exact components to port from the other repo.
4. **Draft Phase 3.1:** Write stub tests for ETIMEDOUT rule in `backend/test_superchecker.py`.

**Owner:** You + AI agents using updated AGENTS.md as playbook.

Good luck! 🚀

