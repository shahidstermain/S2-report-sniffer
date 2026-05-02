# Component port checklist (singlestore-cluster-intelligence → S2 Report Sniffer)

Phase 1 deliverable per [PRODUCT_ROADMAP.md](../PRODUCT_ROADMAP.md). Track each port from the reference app into this repo.

| Priority | Component | Source (reference) | S2RS target / status | Notes |
|----------|-----------|--------------------|----------------------|--------|
| P1 | Interactive cluster / topology map | TBD in reference repo | Not present; [ReportDashboard](../frontend/src/pages/ReportDashboard.jsx) uses [ClusterOverview](../frontend/src/components/ClusterOverview.jsx) (non-interactive) | Define source file paths when reference is vendored or linked. |
| P1 | Risk / confidence gauge | TBD | [Recommendations](../frontend/src/components/Recommendations.jsx), KPI strip | Align visuals with [DESIGN.md](../DESIGN.md) and [design_guidelines.json](../design_guidelines.json). |
| P2 | Polished finding / recommendation cards | TBD | List-based recommendations today | Add animations + copy actions per roadmap Phase 2. |
| P2 | Workload chart variants | TBD | `recharts` in dashboard components | Compare with reference charts; port only if materially better. |
| P3 | Shared design tokens | Reference design system | Tailwind + shadcn in `frontend/src/components/ui/*` | `design_guidelines.json` is a manual reference (not imported in code). |

## Porting steps (template)

1. Identify the reference file and props/data contract.
2. Map data from `report.json` / API fields ([backend/storage.py](../backend/storage.py) payload shape).
3. Add or extend a screen under `frontend/src/pages/` and route in [App.js](src/App.js) if needed.
4. Add unit or Playwright coverage ([frontend/e2e/](e2e/), `*.test.jsx`).
5. Update [AGENTS.md](../AGENTS.md) if new parser or recommendation IDs are introduced.

## Status

- Checklist created: **in progress** — fill “Source” column when `singlestore-cluster-intelligence` paths are confirmed by the team.
