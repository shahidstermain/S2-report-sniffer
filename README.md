# S2 Report Sniffer

**Local-first, offline analyzer for SingleStore `sdb-report` diagnostic bundles.**

Parses large support archives (`.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`, up to 10 GB), correlates logs and OS/metrics across cluster nodes, scores findings by operational risk, and presents a dashboard. Designed for air-gapped / laptop-only use: **no customer data leaves the machine** unless you explicitly attach a packet in Glean Chat.

| Stack | Role |
|-------|------|
| FastAPI (`backend/`) | Upload, extract, parse, score, SQLite persistence |
| React + Vite (`frontend/`) | Report list + dashboard UI |
| Electron (`desktop/`) | Packaged macOS app that spawns the backend |

---

## What it does

| Capability | Detail |
|------------|--------|
| Streaming ingestion | Parses multi-GB archives with bounded memory (generators + row/byte caps) |
| Correlation | Combines `memsql.log`, dmesg, sysinfo, and info-schema snapshots |
| SuperChecker | Risk-scores findings with remediation and doc grounding |
| Log search | Raw tracelog search (with context) when extracts are kept; parsed fallback otherwise |
| Analyze in Glean | Builds a **local** Markdown incident packet; you attach it in Glean — no auto-egress |

**Pipeline:** Upload → validate/extract (`server.py`) → parse (`parsers.py`) → score (`superchecker.py`) → SQLite (`storage.py`) → UI.

---

## Prerequisites

- Python **3.11+** (use 3.11 for desktop / PyInstaller builds)
- Node.js **20+**

---

## Run from source

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
S2RS_DATA_DIR=./local_data uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

API docs: `http://127.0.0.1:8000/api/docs`

### Frontend (dev)

```bash
cd frontend
npm install
npm run dev
```

Vite on `:3000` proxies `/api` → `:8000`.

### Integrated (API + built UI)

```bash
cd frontend && npm run build
cd ../backend && S2RS_DATA_DIR=./local_data .venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000/ui/
```

`./dev-setup.sh` starts backend then frontend for local development.

### Desktop DMG (macOS)

```bash
PYTHON_BIN=python3.11 bash scripts/build-desktop.sh
```

Output: `dist/installers/S2 Report Sniffer-1.0.0-arm64.dmg`

The PyInstaller spec excludes `backend/local_data/` so large local extracts are not bundled.

---

## How to use

1. **Launch** — Install/open the Electron app from Applications (backend starts on `127.0.0.1`), or use the web UI above.
2. **Upload / import** — Drop an `sdb-report` archive, or import from a local path. Accepted: `.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz` (max 10 GB). Bundles must come from `sdb-report collect` (hand-zipped raw logs will fail).
3. **Wait for status** — `uploading` → `processing` → `ready` (or `errored`). ~1 GB typically takes 30–90s.
4. **Open the report** — Tabs include Overview, Charts, Diagnostics, Nodes, Storage, Queries, Logs, Log Search, Config, and **Issues** (recommendations / triage).

### Issues tab

Findings are ranked by risk. Expanding a finding shows evidence, affected nodes, grounding, remediation, and **View in Logs**. Triage buckets: Act Now / Quick Wins / Act Soon / Backlog. **Analyze in Glean** saves/opens a local packet for Glean Chat.

### Health score (0–100)

| Grade | Score | Guidance |
|-------|-------|----------|
| A | 90–100 | Healthy |
| B | 80–89 | Minor issues |
| C | 70–79 | Review findings |
| D | 60–69 | Investigate promptly |
| F | 0–59 | Critical — prioritize Immediate findings |

Treat the score as triage context; always read evidence and remediation.

---

## Troubleshooting

| Symptom | What to try |
|---------|-------------|
| Blank Electron window | Quit (`⌘Q`), kill orphaned processes in Activity Monitor, free port `8000` (`lsof -i :8000`) |
| Upload “unable to extract” / invalid format | Confirm archive is from `sdb-report collect`; verify with `file report.zip` |
| Stuck in `processing` | Check backend logs for OOM / decompression errors; split large collections with a node filter |
| Empty charts / memory / node panels | Use a real multi-node bundle (not a zero-node smoke zip); request `sdb-report collect --validate-env --include-infra` if OS signals are missing |
| Backend unavailable | Run uvicorn manually from `backend/` with the venv activated; fix missing deps or data-dir permissions |

CLI smoke for a huge archive:

```bash
cd backend && source .venv/bin/activate
python -c "
from parsers import parse_report_archive_streaming
for node in parse_report_archive_streaming('/path/to/bundle.tar.gz'):
    print(node.get('hostname'), node.get('version'))
"
```

---

## Tests

```bash
cd backend && source .venv/bin/activate
python -m pytest test_parsers.py test_api_smoke.py test_superchecker.py -v

cd frontend && npm test && npm run build
```

---

## Security / data handling

- Local-only by default — no product telemetry or crash reporting.
- Persist under `S2RS_DATA_DIR` (default `~/.s2-report-sniffer`; use `./local_data` in dev).
- Extraction is path-bounded with a decompressed size budget.
- Glean handoff is opt-in (local file); data leaves the laptop only if you attach it.

Do **not** commit customer bundles, extracts, `.env` files, or secrets (pre-commit hooks block common secret paths). `.build/` and local data dirs are gitignored — keep them that way.

---

## Further reading

| Doc | Purpose |
|-----|---------|
| `CLAUDE.md` / `AGENTS.md` | Architecture and contributor conventions |
| `PACKAGING.md` | Electron + PyInstaller |
| `DEPLOYMENT.md` | Deployment notes |
| `INTEGRATION.md` / `docs/ai-rca-design.md` | Glean packet design |
| `SECURITY_REVIEW.md` / `AIRGAP_TEST_PROTOCOL.md` | Security / air-gap |
| `DESIGN.md` | UI design system |
