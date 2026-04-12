# Phase 1 Execution Checklist — Foundation & Debt Elimination

**Duration:** Weeks 1–2  
**Owner:** Primary FE focus (backend can work on MVP rules in parallel)

---

## ✅ 1.1 Private Dependencies Cleanup

- [x] Audit backend `emergentintegrations`: Already commented out in `requirements.txt`
- [x] Audit frontend `@emergentbase/visual-edits`: **Removed** (unused in source)
- [x] Verified no other external URL deps in `frontend/package.json`
- [ ] Test: `npm install` in `frontend/` and build succeeds

**Status:** DONE ✅

---

## ⏳ 1.2 Frontend Build System: CRA → Vite + TypeScript

### Tasks

#### Step 1: Setup Vite scaffold
- [ ] `npm create vite@latest . -- --template react --import.meta.env` in `frontend/`
- [ ] Review generated `vite.config.js`, `tsconfig.json`, `index.html`
- [ ] Copy tailwind + eslint config from old CRA setup

#### Step 2: Port dependencies to new stack
- [ ] Update `package.json`:
  - Remove: `react-scripts`, `@craco/craco`, `cra-template`
  - Add: `vite`, `@vitejs/plugin-react`, `@types/react`, `@types/react-dom`
- [ ] Verify no breaking changes in dev deps (testing library, playwright)

#### Step 3: Migrate source files
- [ ] Rename `src/index.js` → `src/main.jsx` (JSX required in Vite)
- [ ] Update `public/index.html` → root `index.html` with `<div id="root"></div>` + `<script type="module" src="/src/main.jsx"></script>`
- [ ] Port env vars: `process.env.REACT_APP_*` → `import.meta.env.VITE_*`
  - In `frontend/.env`: rename all `REACT_APP_*=` to `VITE_*=`
  - In source: replace all `process.env.REACT_APP_BACKEND_URL` with `import.meta.env.VITE_BACKEND_URL`
- [ ] Verify all imports are absolute or relative (no implicit node_modules resolution needed)

#### Step 4: Testing & validation
- [ ] `npm install` (fresh node_modules with Vite)
- [ ] `npm run dev` - should start on `http://localhost:5173` in seconds
- [ ] `npm run build` - should complete in <30s
- [ ] `npm run preview` - should serve built app correctly
- [ ] Run existing tests: `npm test` (some test config may need Vite-specific adjustments)

#### Step 5: Update dev docs
- [ ] Edit `dev-setup.sh`: replace `npm start` with `npm run dev`
- [ ] Edit `AGENTS.md` "Developer workflow" section: update frontend dev command
- [ ] Edit `README.md` "Installation and Setup" with new build commands

**Estimated effort:** 3–4 days  
**Exit criteria:** All existing tests pass, `npm run build` <30s, frontend loads at `localhost:5173`

---

## 📋 1.3 Component Port Checklist Documentation

**Deliverable:** `frontend/COMPONENT_PORT_CHECKLIST.md`

### Sections

- [ ] List all target components from `singlestore-cluster-intelligence`:
  - [ ] Topology map visualization
  - [ ] Score gauge (risk/confidence/severity animation)
  - [ ] Recommendation/finding card
  - [ ] Workload charts (if better than recharts)
  
- [ ] For each component:
  - [ ] Source file location in other repo
  - [ ] Current S2-report-sniffer equivalent (if any)
  - [ ] Porting effort (hours)
  - [ ] Design notes (colors, layout constraints)
  - [ ] Dependencies (Recharts? D3? Visx?)

- [ ] Create a GitHub issue per component for Phase 2 tracking

---

## 📝 Documentation Updates (Before Phase 2)

- [ ] Update `AGENTS.md` "Developer workflow" section with Vite commands
- [ ] Update `README.md` section 5 (Installation and Setup) with new build steps
- [ ] Create `frontend/COMPONENT_PORT_CHECKLIST.md` with porting roadmap
- [ ] Update `PRODUCT_ROADMAP.md` with actual vs. estimated effort adjustments

---

## 🚀 Definition of Done (Phase 1)

- [ ] All private deps removed or documented
- [ ] `npm install && npm run build` completes successfully in <30s
- [ ] All frontend tests pass (or disabled with clear plan to re-enable)
- [ ] Dev-setup.sh and docs updated
- [ ] Commit pushed with message: `feat(frontend): migrate create-react-app → vite + typescript`
- [ ] Phase 2 component checklist document ready for next sprint

---

## Blockers & Risks

| Item | Risk | Mitigation |
|------|------|-----------|
| Env var migration breaks API calls | HIGH | Test API client in dev immediately after Vite cutover |
| Tests fail in Vite environment | MEDIUM | May need `vitest` instead of Jest; handle per test file |
| Build size increases | LOW | Profile with `npm run build -- --report` |
| HMR doesn't work smoothly | LOW | Vite's HMR is superior; should auto-work |

---

## Parallel Work (Backend, Week 1–2)

While FE is on Vite migration, backend can:
- [ ] Create test stubs for MVP superchecker rules (ETIMEDOUT, fsync, retry)
- [ ] Add parser signal extraction for ETIMEDOUT hourly counts
- [ ] Add related test data to `backend/test_parsers.py`

**See:** `PRODUCT_ROADMAP.md` Phase 3.1

---

## Sign-Off

- **Started:** [DATE]
- **Completed:** [DATE]
- **Blocker notes:** [if any]
- **Next phase:** [link to Phase 2 kickoff]

