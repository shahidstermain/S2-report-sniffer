# Strategy Brief: S2 Report Sniffer as Core Product

**Date:** April 12, 2026  
**Decision:** Focus on S2-report-sniffer + port UI from singlestore-cluster-intelligence  
**Author:** Strategic Planning Session

---

## TL;DR

**S2 Report Sniffer is the moat.** Parsing real `.tar.gz` support bundles and correlating findings across logs, metrics, and config is irreplaceable work. The UI is solvable. UI frameworks and components are replicable; the parsing engine is not.

**Action:** Eliminate technical debt (private deps, CRA end-of-life, stale build tooling), port the best UI components from `singlestore-cluster-intelligence`, then expand the brain (new checks, better recommendations).

**Timeline:** 6–7 weeks for full modernization + desktop packaging.

---

## Why S2 Report Sniffer Wins

| Dimension | S2 Report Sniffer | singlestore-cluster-intelligence | Winner |
|-----------|------------------|--------------------------------|--------|
| **Parsing engine** | Deep, correlates logs/metrics/config | JSON dashboard only | S2 ✅ |
| **Moat** | Hard (archive handling, data fusion) | Low (standard web UI) | S2 ✅ |
| **Deployment story** | FastAPI + MongoDB + Electron desktop | ICP-only (permanent headache) | S2 ✅ |
| **Recommendation model** | SuperChecker (risk_score + confidence + fix_first) | 47-rule flat list | S2 ✅ |
| **UI polish** | Basic, functional | Better (topology map, score breakdowns) | Other ✅ |
| **Test coverage** | Solid (parsers, API smoke tests) | Lighter | S2 ✅ |

**Verdict:** Keep S2 as core. Steal the UI tricks.

---

## What We're Keeping From S2

1. ✅ **Parser pipeline** (`backend/parsers.py`) — the differentiator
2. ✅ **SuperChecker engine** (`backend/superchecker.py`) — risk scoring with context
3. ✅ **Data model** (`backend/storage.py`) — report schema + findings correlation
4. ✅ **FastAPI backend** — lightweight, fast, cloud-friendly
5. ✅ **Offline desktop path** — built-in Electron launcher + SQLite persistence

---

## What We're Stealing From singlestore-cluster-intelligence

1. 📊 **Topology/cluster map** — interactive node + partition visualization
2. 🎨 **Score gauge animation** — risk/confidence/severity visual indicators
3. 🎯 **Finding card design** — polished, actionable recommendation layout
4. 📈 **Workload chart patterns** — if better than recharts current usage
5. 🎨 **Design system** — colors, spacing, typography consistency

---

## Execution Plan (6–7 weeks)

### Phase 1: Foundation (Weeks 1–2) — **IN PROGRESS**
- [x] Remove private deps (`@emergentbase/visual-edits`, `emergentintegrations`)
- [ ] Migrate frontend: CRA → Vite + TypeScript (3–4 days)
- [ ] Document component porting checklist
- [ ] Update dev workflow docs

**Commit:** `chore: remove unused private deps + add product roadmap` ✅

### Phase 2: UI Modernization (Weeks 3–4)
- [ ] Port topology map visualization
- [ ] Enhance recommendation cards with gauges
- [ ] Refactor dashboard pages for visual consistency

### Phase 3: Brain Expansion (Weeks 3–5, parallel with Phase 2)
- [ ] MVP superchecker rules: ETIMEDOUT, fsync, retry-stall hourly counts
- [ ] Log timeframe detection per node
- [ ] Backup reliability summary

### Phase 4: Desktop Packaging (Weeks 5–7)
- [ ] Finalize Electron + auto-update
- [ ] Code signing (macOS, Windows)
- [ ] CI/CD pipeline for signed installers

---

## Success Metrics

- ✅ Frontend build time <30s (Vite vs CRA baseline ~90s)
- ✅ 3+ new parser rules with test coverage
- ✅ Recommendation UI renders new signals correctly
- ✅ Signed desktop installers ship in CI/CD
- ✅ AGENTS.md reflects all new checks with stable IDs

---

## New Documents Created

1. **`PRODUCT_ROADMAP.md`** — Full 7-week execution plan with risk mitigation
2. **`PHASE1_CHECKLIST.md`** — Detailed tasks for weeks 1–2 (Vite migration + component porting)
3. **`AGENTS.md`** (updated) — Brain expansion guidance for AI agents

All pushed to `main` branch.

---

## Handoff Notes for AI Agents

Using updated `AGENTS.md`:

- **Parser signals first:** New checks belong in `backend/parsers.py` as signal extraction, not in API endpoints
- **Signal families:** Tracelog (ETIMEDOUT/fsync/retry), Resource (sysctl/free/ulimit), Info schema (show-*tsv)
- **Normalize output:** Store numeric aggregates (e.g., `etimedout_per_hour`), not raw logs
- **Keep IDs stable:** Existing tests assert on checker_id and recommendation content
- **Sync schema:** When adding new fields, update `backend/validators.py`, `backend/monitoring.py`, and `backend/storage.py` together

---

## Rejected Option: singlestore-cluster-intelligence

**Why not?**
- ICP deployment model is permanent friction (infrastructure assumptions, config complexity)
- Parsing story is weak (JSON input → charts, not bundle triage)
- 47-rule flat list is less actionable than SuperChecker's risk_score + confidence + fix_first
- UI is better, but months of porting + maintenance overhead not worth it for core product

**Use case:** Reference library for design patterns and component styles. Extract individual patterns as needed for S2-report-sniffer.

---

## Next Steps (This Week)

1. **Review this strategy brief** — confirm alignment with team/stakeholders
2. **Start Phase 1.2** — Vite migration branch (`feat/vite-migration`)
3. **Backend team** — Begin MVP superchecker rule stubs (ETIMEDOUT, fsync, retry) in parallel
4. **Update AGENTS.md** — Refine any brain expansion guidance based on progress

---

## Questions?

- **Build tooling specifics?** See `PHASE1_CHECKLIST.md`
- **Which UI components to port first?** See `COMPONENT_PORT_CHECKLIST.md` (to be created in Phase 1)
- **How to implement a new superchecker rule?** See `AGENTS.md` "Brain expansion playbook"
- **Electron packaging details?** See `PACKAGING.md` and `AIRGAP_TEST_PROTOCOL.md`

---

**Decision Maker Approval:**  
[Pending sign-off]

**Product Owner:**  
shahidster1711

**Engineering Lead:**  
[TBD]

---

*This document is the strategic north star. Keep it updated as phases complete.*

