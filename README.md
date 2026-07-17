<div align="center">

<img src="docs/assets/logo.svg" alt="S2 Report Sniffer" width="160" />

# S2 Report Sniffer

**Local-first, offline analyzer for SingleStore `sdb-report` diagnostic bundles.**

Turn a 10 GB support archive into a ranked triage dashboard — in under two minutes, on a laptop, with no customer data leaving the machine.

<p>
  <a href="https://github.com/shahidstermain/S2-report-sniffer/blob/main/LICENSE"><img src="https://img.shields.io/github/license/shahidstermain/S2-report-sniffer?style=for-the-badge&color=00d992&labelColor=050507" alt="License"/></a>
  <img src="https://img.shields.io/badge/version-1.0.0-00d992?style=for-the-badge&labelColor=050507" alt="Version"/>
  <img src="https://img.shields.io/badge/python-3.11+-00d992?style=for-the-badge&labelColor=050507" alt="Python 3.11+"/>
  <img src="https://img.shields.io/badge/node-20+-00d992?style=for-the-badge&labelColor=050507" alt="Node 20+"/>
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-00d992?style=for-the-badge&labelColor=050507" alt="Platform"/>
  <img src="https://img.shields.io/github/stars/shahidstermain/S2-report-sniffer?style=for-the-badge&color=00d992&labelColor=050507" alt="Stars"/>
</p>

<p>
  <a href="#-quick-start">Quick Start</a> ·
  <a href="#-features">Features</a> ·
  <a href="#-architecture">Architecture</a> ·
  <a href="#-docs">Docs</a> ·
  <a href="#-contributing">Contributing</a>
</p>

</div>

---

## Why

When a SingleStore cluster misbehaves, you get an `sdb-report` archive that can be many gigabytes, spread across every node, mixing `memsql.log`, dmesg, sysinfo, and info-schema snapshots. Finding the *actual* root cause is hours of grep and guesswork — and you can't upload the bundle anywhere sensitive.

**S2 Report Sniffer** ingests the bundle, correlates signals across nodes, risk-scores every finding with grounded remediation, and gives you a triage dashboard you can act on. Fully offline. The optional **Analyze in Glean** step builds a local Markdown incident packet — *you* decide if it ever leaves the laptop.

```
$ s2rs sniff ./cluster-report.tar.gz
[██████░░░░░░░░░░░░░░░] 32%  extracting
[████████████░░░░░░░░░░] 58%  parsing memsql.log (6 nodes)
[██████████████████░░░] 89%  correlating events
[██████████████████████] done  (47.3s, 2.1 GB peak)

  Health Score:  72 / C   ████████████████░░░░░░
  Findings:      3 Immediate · 7 Quick Win · 12 Soon · 4 Backlog
  Top risk:      master_leaf_down on 2/6 nodes
  Top log hit:   ERROR  LEAF_DOWN  partition 384 failed over
  → open http://127.0.0.1:8000/ui/report/a1f9…
```

---

## ✨ Features

| | |
|---|---|
| 🚀 **Streaming ingestion** | Multi-GB archives parsed with bounded memory (generators + row/byte caps). Handles `.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz` up to **10 GB**. |
| 🔗 **Cross-node correlation** | Combines `memsql.log`, dmesg, sysinfo, and info-schema snapshots into a single timeline. Suppresses secondary alerts when a primary root cause is present. |
| 🎯 **SuperChecker scoring** | Every finding is risk-scored with evidence, affected nodes, doc grounding, and one-click remediation. |
| 🔍 **Dual-mode log search** | Raw `memsqlTracelogs/` scan with context windows when extracts are kept; parsed `logs.jsonl` fallback otherwise. Compressed + uncompressed, multi-node. |
| 🧠 **Analyze in Glean** | Builds a **local** Markdown incident packet (findings + suspected log lines). You attach it in Glean Chat — no auto-egress, ever. |
| 🖥️ **Native desktop app** | Electron shell bundles the FastAPI backend and the React UI into a single macOS DMG. Backend spawns on `127.0.0.1`, UI loads from `/ui/`. |
| 🔒 **Air-gap safe** | No telemetry, no crash reporting, no backend egress. Path-bounded extraction, decompressed size budget, rate-limited uploads. |
| 📊 **Polished dashboard** | Dark theme (`#050507` canvas · `#00d992` accent), Recharts visualizations, shadcn/ui primitives, virtualized log list. |

---

## 🚀 Quick Start

### Option A — Desktop app (recommended)

Grab the latest DMG from the [Releases](../../releases) page and drag to Applications. The backend auto-spawns on launch.

```bash
# Build from source (macOS, Apple Silicon)
PYTHON_BIN=python3.11 bash scripts/build-desktop.sh
# → dist/installers/S2 Report Sniffer-1.0.0-arm64.dmg
```

### Option B — From source

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
S2RS_DATA_DIR=./local_data uvicorn server:app --host 127.0.0.1 --port 8000 --reload

# 2. Frontend (new terminal)
cd frontend && npm install && npm run dev
# → http://localhost:3000
```

API docs available at `http://127.0.0.1:8000/api/docs`. Or use `./dev-setup.sh` to spin up both in one shot.

### Option C — Integrated (UI + API on one origin)

```bash
cd frontend && npm run build
cd ../backend && S2RS_DATA_DIR=./local_data .venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
# → http://127.0.0.1:8000/ui/
```

---

## 📖 Usage

1. **Upload** — Drop an `sdb-report` archive, or import from a local path. Bundles must come from `sdb-report collect` (hand-zipped raw logs will fail validation).
2. **Wait** — Status walks `uploading` → `processing` → `ready` (or `errored`). ~1 GB typically takes 30–90 s.
3. **Triage** — Tabs: **Overview** · **Charts** · **Diagnostics** · **Nodes** · **Storage** · **Queries** · **Logs** · **Log Search** · **Config** · **Issues**.
4. **Hand off** — On the Issues tab, hit **Analyze in Glean** to save a local incident packet, then attach it in Glean Chat.

### Health score (0–100)

| Grade | Score | What it means |
|:-:|:-:|---|
| 🟢 **A** | 90–100 | Healthy |
| 🟢 **B** | 80–89 | Minor issues |
| 🟡 **C** | 70–79 | Review findings |
| 🟠 **D** | 60–69 | Investigate promptly |
| 🔴 **F** | 0–59 | Critical — prioritize Immediate findings |

> The score is triage context, not a verdict. Always read evidence and remediation.

---

## 🏗️ Architecture <a id="-architecture"></a>

```
        ┌─────────────────────────────────────────────────────┐
        │  Electron (macOS DMG)  ─or─  Browser at :3000       │
        └──────────────────────────┬──────────────────────────┘
                                   │ /api
        ┌──────────────────────────▼──────────────────────────┐
        │              FastAPI  (backend/server.py)           │
        │  upload → validate → extract → parse → score        │
        │       │        │        │        │        │         │
        │  validators extract  parsers  superchecker storage  │
        │                                       (SQLite)       │
        └─────────────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────▼──────────────────────────┐
        │  React + Vite + shadcn/ui + Recharts                │
        │  /           → ReportList                           │
        │  /report/:id → ReportDashboard (10 tabs)            │
        └─────────────────────────────────────────────────────┘
```

**Local-first by design.** All data lives under `S2RS_DATA_DIR` (default `~/.s2-report-sniffer`; `./local_data` in dev). No MongoDB, no cloud storage, no telemetry. The optional Hostinger bridge is gated behind `S2RS_ENABLE_CLOUD_EXTENSIONS`.

---

## 🧰 Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | **FastAPI** + uvicorn | Async streaming for multi-GB uploads; auto-generated OpenAPI docs |
| Parsing | Pure-Python generators | Bounded memory; works on `.zip` / `.tar*` / `.gz` without shelling out |
| Frontend | **React 19** + Vite 5 | Fast HMR, small bundles, modern toolchain |
| UI kit | **shadcn/ui** + Radix + Tailwind | Accessible primitives, fully themeable, no runtime CSS-in-JS |
| Charts | **Recharts** | Composable, declarative, plays well with React 19 |
| Desktop | **Electron** + electron-builder | Ships a single DMG; auto-spawns the bundled backend |
| Persistence | **SQLite** + filesystem | Single-user, single-machine — no DB server to operate |

---

## 🧪 Tests

```bash
# Backend (~538 tests)
cd backend && .venv/bin/python -m pytest -v

# Frontend
cd frontend && npm test && npm run build
```

Log-search behavior is split across two test files for the two search modes:

```bash
cd backend && .venv/bin/python -m pytest test_log_search.py test_log_search_raw.py -v
```

Pre-commit hooks (`.githooks/pre-commit` + `pre-push`) block common secret paths and credential patterns — run `git config core.hooksPath .githooks` after cloning.

---

## 🛠️ Troubleshooting

| Symptom | Try this |
|---|---|
| Blank Electron window | Quit (`⌘Q`), kill orphans in Activity Monitor, free port `8000` (`lsof -i :8000`) |
| "Unable to extract" / invalid format | Confirm the archive came from `sdb-report collect`; verify with `file report.zip` |
| Stuck in `processing` | Check backend logs for OOM / decompression errors; split with a node filter |
| Empty charts / memory / node panels | Use a real multi-node bundle; `sdb-report collect --validate-env --include-infra` if OS signals are missing |
| Backend unavailable | Run uvicorn manually from `backend/` with the venv activated |

CLI smoke for a huge archive without the API:

```bash
cd backend && source .venv/bin/activate
python -c "
from parsers import parse_report_archive_streaming
for node in parse_report_archive_streaming('/path/to/bundle.tar.gz'):
    print(node.get('hostname'), node.get('version'))
"
```

---

## 🔒 Security & Data Handling

- **Local-only by default** — no product telemetry, no crash reporting, no background egress.
- **Path-bounded extraction** with a decompressed size budget; no zip-slip.
- **Rate-limited uploads** (10/min per IP) and a hard 10 GB cap.
- **Glean handoff is opt-in** — the incident packet is a local file. Data leaves the laptop only if you attach it.
- **Parameterized SQL only** — no string interpolation in queries.
- **Pre-commit hooks** block `.env*`, `*.pem`, `*.key`, AWS/GitHub/Slack tokens, and SSH/PGP private keys.

See `SECURITY_REVIEW.md` and `AIRGAP_TEST_PROTOCOL.md` for the full review.

---

## 📚 Docs

| Doc | What's in it |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) | Architecture, conventions, contributor playbook |
| [`DESIGN.md`](DESIGN.md) | UI design system (dark theme, accent green) |
| [`PACKAGING.md`](PACKAGING.md) | Electron + PyInstaller build pipeline |
| [`INTEGRATION.md`](INTEGRATION.md) · [`docs/ai-rca-design.md`](docs/ai-rca-design.md) | Glean packet design |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Deployment notes |
| [`LOCAL_FIRST_ARCHITECTURE.md`](LOCAL_FIRST_ARCHITECTURE.md) | Why and how we stay local-only |
| [`USER_MANUAL.md`](USER_MANUAL.md) | End-user walkthrough |
| [`PREPROD_TEST_REPORT.md`](PREPROD_TEST_REPORT.md) | Pre-release QA report |
| [`PRODUCT_ROADMAP.md`](PRODUCT_ROADMAP.md) | What's next |

---

## 🤝 Contributing

Issues and PRs welcome. Start with `AGENTS.md` for the architecture, conventions, and the storage-schema **3-place allowlist gotcha** (it will save you an afternoon).

```bash
git clone https://github.com/shahidstermain/S2-report-sniffer.git
cd S2-report-sniffer
git config core.hooksPath .githooks
./dev-setup.sh
```

Before opening a PR:

```bash
# Backend
cd backend && .venv/bin/python -m pytest -v
# Frontend
cd ../frontend && npm test && npm run build
```

---

## 📝 License

MIT — see [`LICENSE`](LICENSE).

---

<div align="center">

Built by [Shahid Moosa](https://github.com/shahidstermain) · SingleStore DB Support Engineer · Port Blair, A&N Islands

<sub>🐕 Sniffing bundles so you don't have to.</sub>

</div>
