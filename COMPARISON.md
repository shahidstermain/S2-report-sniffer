# Repository Comparison: S2 Report Sniffer vs SingleStore Cluster Intelligence

**Decision date:** 2026-04-12  
**Repos compared:**
- A: [`shahidster1711/S2-report-sniffer`](https://github.com/shahidster1711/S2-report-sniffer) ← _this repo_
- B: [`shahidster1711/singlestore-cluster-intelligence`](https://github.com/shahidster1711/singlestore-cluster-intelligence)

---

## TL;DR Recommendation

**Develop S2 Report Sniffer (this repo) as the primary codebase.**

It has an overwhelming technical maturity lead — a proven parsing engine, SuperChecker scoring, 15+ test files, desktop installer support, and full persistence. The cluster-intelligence repo's best ideas (TypeScript frontend, Vite, dark-theme design system, Web Worker streaming parser) are worth importing into this repo over time, but starting fresh there would mean rebuilding ~9,500 lines of battle-tested Python logic from scratch.

---

## Side-by-Side Analysis

| Dimension | S2 Report Sniffer (A) | Cluster Intelligence (B) |
|---|---|---|
| **Age / maturity** | Multiple months of active development | Created 2026-04-12 (same day as this analysis) |
| **Backend language** | Python 3.10+ / FastAPI | Motoko (DFINITY/ICP blockchain) |
| **Frontend stack** | React (CRA) / JavaScript | React + TypeScript / Vite / pnpm |
| **UI library** | Tailwind + custom components | Tailwind + shadcn/ui (OKLCH design tokens) |
| **Persistence** | SQLite (desktop) + MongoDB (server) | ICP canister storage (blockchain) |
| **Parsing** | Server-side: `parsers.py` (1,582 lines) | Client-side Web Worker (4 MB chunk streaming) |
| **Analysis engine** | SuperChecker: 2,090 lines, risk scores 0–100, `fix_first`, correlation | None yet |
| **Test coverage** | 15+ test files, pytest, smoke + unit + integration | None |
| **Documentation** | README, DEPLOYMENT, PACKAGING, USER_MANUAL, AIRGAP_TEST_PROTOCOL, CHANGELOG, CORRECTNESS_CHECKLIST | DESIGN.md only |
| **Offline / air-gap** | ✅ Electron desktop installer (PACKAGING.md) | ✅ Client-side parsing works offline |
| **Report diffing** | ✅ `/api/reports/diff` | ✗ |
| **Export** | ✅ Slack + HTML | ✗ |
| **Monitoring** | ✅ `/api/health`, `/api/alerts`, `/api/metrics/performance` | ✗ |
| **DB migrations** | ✅ Alembic | ✗ |
| **CI/CD** | ✅ GitHub Actions, Vercel, bandit audit gate | ✅ CodeQL workflow added |
| **Backend LoC (core)** | ~9,500 lines Python | ~838 lines Motoko stub |
| **Dashboard tabs** | 7 (Overview, Nodes, Storage, Queries, Logs, Config, Issues) | In progress (landing page + health circle) |

---

## What Each Repo Does Well

### S2 Report Sniffer strengths
1. **Parsing depth** — covers 50+ collector file types: free, df, top, sysctl, dmesg, memsql.log, MV_NODES, MV_QUERIES, processlist, show-variables, backup-history, etc.
2. **SuperChecker engine** — 2,090 lines of diagnostic rules with `checker_id`, `risk_score`, `confidence`, `fix_first`, `related_findings`, and cross-finding correlation.
3. **Persistence** — dual-mode: SQLite + file-based for desktop, MongoDB for server/cloud. Alembic migrations.
4. **Desktop installer** — Electron wrapper (`desktop/main.js`) + PyInstaller backend bundle for fully air-gapped use.
5. **Test infrastructure** — `test_parsers.py`, `test_api_smoke.py`, `test_superchecker.py`, `test_monitoring.py`, `test_validators.py`, `test_correlation.py` + more.
6. **Operational endpoints** — health, alerts, performance metrics, diff, Slack/HTML export.

### Cluster Intelligence strengths
1. **Modern TypeScript stack** — Vite + TypeScript + pnpm workspaces. Type safety everywhere, fast builds, no CRA deprecation concerns.
2. **Streaming Web Worker** — Client-side streaming parser splits large sdb-report files into 4 MB chunks, shows 5-stage progress UI, handles OOM gracefully, supports cancellation.
3. **Design system** — OKLCH color tokens, animated health-score conic-gradient circle, Space Grotesk + JetBrains Mono, dark theme throughout. Purpose-built for diagnostics data density.
4. **shadcn/ui** — Headless, accessible component library already configured with Tailwind v3 + OKLCH palette.
5. **No server required** — Pure client-side parsing is ideal for environments where running a Python server is impractical.

---

## Why B's Backend Is a Problem

The `singlestore-cluster-intelligence` backend is written in **Motoko** — the language for the [Internet Computer Protocol (ICP)](https://internetcomputer.org/) blockchain. The `src/backend/main.mo` stub currently just echoes reports; there is no parsing logic. Rebuilding even 20% of S2 Report Sniffer's parsing depth in Motoko would require:

- Learning Motoko + DFX toolchain
- Porting Python regex/TSV/glob parsing to a statically-typed actor model
- Deploying canisters to the ICP network (or running a local replica)
- Losing all existing MongoDB/SQLite compatibility

This is a fundamental architectural mismatch with SingleStore's enterprise support-bundle workflow.

---

## Recommended Development Path

### Immediate (keep S2 Report Sniffer as the base)
- Continue adding checks in `backend/parsers.py` + `backend/superchecker.py` (see `AGENTS.md` high-value checks list).
- Implement the P0 backlog items from `memory/PRD.md`: error timeline heatmap, replication lag indicator, partition health matrix.

### Short-term frontend modernisation (borrow from B)
Port the cluster-intelligence frontend innovations into this repo's `frontend/`:

1. **Migrate CRA → Vite** — eliminate the deprecated Create React App toolchain. Faster builds, native ESM, better HMR.
2. **Add TypeScript** — incrementally convert `frontend/src` to `.tsx`. Catches API shape mismatches at compile time.
3. **Adopt the dark-theme design system** — import OKLCH color tokens and the animated health-score circle. Replace the current light theme.
4. **Add a Web Worker streaming parser** — for sdb-reports > 10 MB, offload parsing to a Web Worker using the same 4 MB chunk pattern from `singlestore-cluster-intelligence/src/frontend/src/workers/sdbReportParser.worker.ts`.
5. **Switch to shadcn/ui** — replace ad-hoc component wrappers with the headless shadcn primitives already proven in repo B.

### Long-term
- Evaluate whether the ICP/Motoko backend in repo B can be repurposed as a **decentralised report-sharing layer** (public canister storage for sharing diagnostic summaries) while keeping all analysis in S2 Report Sniffer's Python core.
- Archive `singlestore-cluster-intelligence` or redirect it as a pure-frontend companion app that calls S2 Report Sniffer's API.

---

## Decision Matrix

| Factor | Weight | S2 Sniffer (A) | Cluster Intel (B) |
|---|---|---|---|
| Parsing / analysis depth | 30% | 9 | 1 |
| Test coverage | 20% | 9 | 0 |
| Frontend quality | 15% | 5 | 8 |
| Deployment simplicity | 10% | 7 | 6 |
| Backend language fit | 10% | 9 (Python) | 2 (Motoko/ICP) |
| UI/UX design | 10% | 5 | 9 |
| Documentation | 5% | 9 | 2 |
| **Weighted total** | 100% | **7.6** | **3.3** |

---

## Verdict

**Choose S2 Report Sniffer** as your development target. The SuperChecker engine, deep parsing coverage, test suite, and desktop installer represent months of investment that cannot be replicated quickly. Selectively import the TypeScript/Vite/dark-theme/Web Worker innovations from the cluster-intelligence repo to modernise the frontend layer progressively.
