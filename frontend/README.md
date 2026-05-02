# S2 Report Sniffer — frontend

Vite 5 + React 18. Production build outputs to `build/` (same layout the FastAPI app expects: `build/index.html`, `build/static/*`).

## Scripts

- `npm run dev` — Vite dev server (port 3000, proxies `/api` to `http://localhost:8000`)
- `npm run build` — production bundle
- `npm run preview` — preview the production build locally
- `npm test` — Vitest unit tests

## Environment

Optional `VITE_BACKEND_URL` when the UI is not served from the backend under `/ui/` (otherwise the client uses same-origin `/api`).

See repository [README.md](../README.md) and [AGENTS.md](../AGENTS.md) for full workflow.
