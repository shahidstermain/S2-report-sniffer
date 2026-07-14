<h1 align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:aa00ff,100:7c3aed&height=180&section=header&text=S2%20Report%20Sniffer&fontSize=48&animation=fadeIn&fontAlignY=35" width="100%" />
</h1>

<p align="center">
  <img src="https://img.shields.io/badge/SingleStore-AA00FF?style=flat-square&logo=singlestore" />
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python" />
  <img src="https://img.shields.io/badge/React-61DAFB?style=flat-square&logo=react" />
  <img src="https://img.shields.io/badge/Electron-47848F?style=flat-square&logo=electron" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square" />
</p>

<p align="center">
  <strong>🕵️ Offline Diagnostic Intelligence for SingleStore Clusters</strong>
</p>

---

## ⚡ Why I Built This

When we troubleshoot self-managed database environments, we are entirely reliant on massive cluster reports. We pull gigabytes of `memsql.log` files, OS metrics, and hardware telemetry across dozens of nodes. Manual grep-based triage is painfully slow, and it's too easy to miss critical warnings. I built **S2 Report Sniffer** as a side project to automate the grunt work so we can focus on actual problem-solving. Here's how it helps us:

| Capability | What It Does For Us |
|------------|---------------------|
| 📥 **Streaming Ingestion** | Parses massive 10GB+ archives locally without crashing your machine with OOM errors. |
| 🔗 **Correlation** | Automatically stitches together `memsql.log`, `dmesg`, and OS metrics to build a timeline. |
| 🎯 **SuperChecker** | Scores findings by actual operational risk so we know what to look at first. |
| 🤖 **Analyze in Glean** | Builds a local Markdown incident packet (findings + suspected log lines). You attach it in Glean Chat — nothing leaves the machine until you do. |

---

## 🏗️ Architecture

Here's how it's wired to keep everything fast and local:

```
┌─────────────────────────────────────────────────────────────┐
│                    S2 Report Sniffer                        │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐     │
│  │   Electron   │◀──│   FastAPI    │◀──│   Parsers    │     │
│  │  Desktop UI  │   │   Backend    │   │   Engine     │     │
│  └──────────────┘   └──────────────┘   └──────────────┘     │
│         │                  │                  │             │
│         ▼                  ▼                  ▼             │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐     │
│  │   SQLite     │   │  Diagnostic  │   │ SuperChecker │     │
│  │ (Local DB)   │   │   Bundles    │   │   Scoring    │     │
│  └──────────────┘   └──────────────┘   └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

**Core flow:** Upload archive → `server.py` validates & extracts → `parsers.py` walks the tree → `superchecker.py` scores findings → `storage.py` persists to SQLite → React UI renders the dashboard.

---

## 🎯 Key Features

### Diagnostic Capabilities

- **Log Timeframe Detection** — Shows exactly what telemetry coverage we actually have per node.
- **Backup Reliability** — Catches silent failures and duration drift before the customer notices.
- **Hardware Pressure** — Highlights IOPS stalls (`fsync is behind`), network drops (`ETIMEDOUT`), and memory pressure (OOM, THP, swappiness).
- **Topology Sanity** — Validates partition distribution and cluster layout so we aren't chasing ghosts.
- **Process Health** — Maps out active queries, runaway workloads, and sleeping/long-running transactions.
- **Replication Lag** — Flags lagging pairs and sync→async transitions.
- **Memory Utilization** — Per-node engine + OS memory profile with hot-node highlighting.

### Engineering Highlights

- 🔒 **Local-First** — Zero customer data leaves your laptop. Full stop.
- 💾 **Bounded Memory** — Uses Python generators so it maintains a fixed memory footprint.
- 🎯 **Risk Scoring** — The Issues / Fix-First dashboard prioritizes the fires, with grounded basis + remediation per finding.
- 🔎 **Log Search** — Dual-mode search over raw tracelogs (with context) or parsed `logs.jsonl`.
- 🤖 **Analyze in Glean** — Local incident-packet handoff for Glean Chat (no auto-egress).

---

## 🚀 Getting Started

If you want to run it from source or contribute (pull requests welcome!), here's the setup.

### Prerequisites

- Python **3.11+** (prefer 3.11 for desktop / PyInstaller builds)
- Node.js **20+**

### Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
S2RS_DATA_DIR=./local_data uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Vite runs on `:3000` and proxies `/api` → `:8000`.

### Full integrated (API + built UI)

```bash
cd frontend && npm run build
cd ../backend && S2RS_DATA_DIR=./local_data .venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000/ui/
```

Or use `./dev-setup.sh` to start backend then frontend for live coding.

### Desktop Build (macOS DMG)

```bash
PYTHON_BIN=python3.11 bash scripts/build-desktop.sh
```

Installer lands at:

```
dist/installers/S2 Report Sniffer-1.0.0-arm64.dmg
```

> **Note:** Prefer Python **3.11** for packaging. The PyInstaller spec excludes `backend/local_data/` so large dev extracts don't bloat the one-file backend.

---

## 📋 How to Use

### Step 1 — Launch the App

Open **S2 Report Sniffer** from your Applications folder. The Electron app bootstraps the backend automatically:

```
Applications/
└── S2 Report Sniffer.app        ← macOS desktop app (recommended)
```

**Dev tip:** Hit the web UI at `http://localhost:3000` while developing, or `http://localhost:8000/ui/` for the production build served by FastAPI.

### Step 2 — Upload a Cluster Report

The home screen is your report list / Diagnostic Dashboard.

1. **Drag and drop** a SingleStore diagnostic archive onto the upload zone, or click to browse.
2. **Import from path** — enter a local folder or archive path if the file is massive and already on disk.
3. Click **Import report** to start parsing.

**Accepted formats:** `.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz` — up to **10 GB**.

> **Note on failures:** If it throws an "invalid format" error, double-check that the customer actually used `sdb-report collect`. Raw log dumps zipped by hand won't work.

### Step 3 — Wait for Analysis

Processing time depends on bundle size. A standard ~1GB bundle typically takes about **30–90 seconds**.

| Status | Meaning |
|--------|---------|
| `uploading` | File is transferring to the local workspace. |
| `processing` | Extracting, parsing logs, and running the SuperChecker engine. |
| `ready` | Analysis complete — jump in. |
| `errored` | Something broke. Check Troubleshooting below. |

### Step 4 — Explore the Report Dashboard

Click any **ready** report. Main views include:

#### Overview
Your 10,000-foot view: node counts, partition health, backup status, topology map, memory panels, and recent dmesg / pattern signals.

#### Charts
Visual summaries — backup timeline, log severity, pressure events, node health, database disk, and **Memory Utilization by Node**.

#### Diagnostics / Nodes / Storage / Queries / Logs
Deep dives into node capacity, storage distribution, workload patterns, and tracelog browsing.

#### Log Search
Keyword search across nodes. Prefer **raw** mode when the extracted bundle is still on disk (context before/after each hit); falls back to **parsed** mode otherwise.

#### Issues (Recommendations)
This is the money screen. SuperChecker ranks findings by risk. Click a row for severity, description, **full evidence**, affected nodes, grounding (basis + docs), remediation, and **View in Logs** to jump straight into Log Search. Triage buckets surface Act Now / Quick Wins / Act Soon / Backlog. **Analyze in Glean** builds a local Markdown packet you can attach in Glean Chat.

| Column | What it shows |
|--------|---------------|
| Severity | `critical` / `warning` / `info` |
| Checker ID | Stable SuperChecker ID for this finding |
| Title | Plain-English summary of the issue |
| Risk Score | Composite score indicating impact |
| Nodes | Which hosts are affected |

#### Config
License validity, engine variables, auth/SSL posture, and related config findings.

### Step 5 — Understand the Health Score

SuperChecker grades the cluster from **0–100** so you can quickly gauge how bad things are (critical findings penalize harder than warnings):

| Grade | Score | Meaning |
|-------|-------|---------|
| **A** | 90–100 | Healthy — no immediate action required. |
| **B** | 80–89 | Minor issues — keep an eye on it. |
| **C** | 70–79 | Moderate risk — start reviewing recommendations. |
| **D** | 60–69 | Elevated risk — actively investigate. |
| **F** | 0–59 | Critical — drop everything and fix. |

Use the underlying evidence and remediation — not the grade alone.

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `⌘R` | Refresh reports list. |
| `⌘O` | Open file browser to select a new archive. |
| `⌘⌥I` | Open DevTools (development builds only). |

---

## 🔧 Troubleshooting

Things break. Here's how to fix the app when it acts up.

### App Won't Open / Window Is Blank

**Symptom:** The app launches but shows a white screen.

**Solution:**
1. Quit the app (`⌘Q`).
2. Open Activity Monitor and kill any orphaned `S2 Report Sniffer` processes.
3. Restart from Applications.
4. If it persists, check whether port 8000 is blocked: `lsof -i :8000`

### Upload Fails with "Unable to Extract"

**Symptom:** Report immediately hits `errored` status.

**Likely causes:** The file isn't a valid bundle, the download corrupted, or it's from a legacy `sdb-report` version.

**Solution:**
- Verify file integrity: `file customer-report.zip`
- Re-download from the support portal / Toolbox output
- Bundles from SingleStore versions **&lt; 7.5** may be missing critical telemetry signals

### Report Stays in "Processing" State

**Symptom:** It's been spinning for over 5 minutes.

**Solution:** Check backend logs. If you see `DecompressionBombError` or `MemoryError`, the bundle is likely huge. Ask the customer to split collection with `sdb-report collect` and a node filter.

### "No Data Available" / Empty Memory Chart

**Symptom:** Node Health, Charts, or memory panels are empty on a `ready` report.

**Solution:**
- Confirm you're on a **real** `sdb-report` bundle (not a smoke/test zip with zero nodes).
- The customer may have collected without OS / infra signals. Ask for a fresh bundle:
  ```bash
  sdb-report collect --validate-env --include-infra
  ```
- Stale zip uploads may need directory import or rehydrate for some extended diagnostics panels.

### Backend Errors on Startup

**Symptom:** "Backend unavailable" in the UI.

**Solution:** Boot the backend manually to see the traceback:

```bash
cd backend
source .venv/bin/activate
S2RS_DATA_DIR=./local_data uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

Watch for:
- `ModuleNotFoundError` → `pip install -r requirements.txt`
- `PermissionError` on the data dir → fix permissions on `S2RS_DATA_DIR`
- `Database is locked` → close other instances and retry

### Dark Mode Not Applying

**Symptom:** Badges or borders stay light when toggled.

**Solution:** Known CSS debt — some hardcoded hex values still need CSS variables. Cosmetic only; tracked in the backlog.

### Performance Issues with Huge Bundles

**Symptom:** UI locks up on 2GB+ bundles.

**Solution:** Close other heavy apps. If it's over ~5GB, you can exercise the streaming parser from the CLI:

```bash
cd backend && source .venv/bin/activate
python -c "
from parsers import parse_report_archive_streaming
for node in parse_report_archive_streaming('/path/to/bundle.tar.gz'):
    print(node.get('hostname'), node.get('version'))
"
```

---

## 📦 Supported Formats

| Format | Extension |
|--------|-----------|
| Tarball | `.tar.gz`, `.tgz` |
| ZIP | `.zip` |
| Single File | `.tar`, `.gz` |

**Max Size:** 10 GB

---

## 🧪 Tests

```bash
# Backend core gate
cd backend && source .venv/bin/activate
python -m pytest test_parsers.py test_api_smoke.py test_superchecker.py -v

# Frontend
cd frontend && npm test && npm run build
```

---

## 🔒 Security Posture

We deal with highly sensitive database telemetry. This is architected strictly for **offline / air-gapped** operation:

- ❌ No telemetry leaves your local machine
- ❌ No remote crash reporting or analytics
- ❌ Analyze in Glean does **not** auto-upload — it builds a local packet; egress only if you attach it in Glean
- ✅ State lives under `S2RS_DATA_DIR` (default `~/.s2-report-sniffer`; use `./local_data` in dev)
- ✅ Archive extraction is path-bounded with a decompressed budget to resist zip bombs / traversal

See `SECURITY_REVIEW.md`, `AIRGAP_TEST_PROTOCOL.md`, and `docs/ai-rca-design.md` for deeper notes.

---

## 📚 More Docs

| File | Contents |
|------|----------|
| `CLAUDE.md` / `AGENTS.md` | Architecture reference for contributors / AI assistants |
| `DESIGN.md` | UI design system |
| `PACKAGING.md` | Electron + PyInstaller packaging |
| `DEPLOYMENT.md` | Production deployment |
| `INTEGRATION.md` | Glean handoff and external integrations |

---

<p align="center">
  <img src="https://komarev.com/ghpvc/?repo=S2-report-sniffer&label=Clones&color=aa00ff&style=flat" />
</p>

<div align="center">
  Built for Database Reliability Engineering & Advanced Support Operations 🔧
</div>
