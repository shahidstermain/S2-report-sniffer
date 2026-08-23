<div align="center">

<img src="docs/assets/logo.svg" alt="S2 Report Sniffer" width="132" />

# S2 Report Sniffer

### Evidence-first SingleStore Cluster Report triage

Turn large `sdb-report` bundles into a focused investigation workspace—locally, privately, and fast.

<p>
  <a href="https://github.com/shahidstermain/S2-report-sniffer/releases/latest"><img src="https://img.shields.io/github/v/release/shahidstermain/S2-report-sniffer?display_name=tag&sort=semver&style=for-the-badge&label=latest&labelColor=09090b&color=00d992" alt="Latest S2 Report Sniffer release" /></a>
  <a href="https://github.com/shahidstermain/S2-report-sniffer/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/shahidstermain/S2-report-sniffer/ci.yml?branch=main&style=for-the-badge&label=tests&labelColor=09090b" alt="CI status" /></a>
</p>

[Download](#download) · [Features](#what-it-does) · [Quick start](#quick-start) · [How it works](#how-it-works) · [Privacy](#security-and-privacy) · [Docs](#documentation)

</div>

---

> [!IMPORTANT]
> Cluster Reports stay on your machine. S2 Report Sniffer does not automatically upload report data, telemetry, or generated Glean packets.

## Download

| Platform | Package | Download |
|---|---|---|
| **macOS — Apple Silicon** | M1, M2, M3, M4 (`arm64.dmg`) | **[Download latest macOS build](https://github.com/shahidstermain/S2-report-sniffer/releases/latest)** |
| **macOS — Intel** | Intel Macs (`x64.dmg`) | **[Download latest macOS build](https://github.com/shahidstermain/S2-report-sniffer/releases/latest)** |
| **Windows** | Windows 10/11 x64 (`.exe`) | [View latest release](https://github.com/shahidstermain/S2-report-sniffer/releases/latest) |
| **Linux** | x64 (`.AppImage`, `.deb`) | [View latest release](https://github.com/shahidstermain/S2-report-sniffer/releases/latest) |

> [!NOTE]
> Current community builds are unsigned. On macOS, Control-click the app and choose **Open** on first launch. On Windows, choose **More info → Run anyway** only after verifying the package came from this repository. SHA-256 checksum files are attached to every release.

See [all releases](https://github.com/shahidstermain/S2-report-sniffer/releases) for release notes, checksums, and previous versions.

## Why it exists

A SingleStore Cluster Report can contain gigabytes of node tracelogs, kernel output, system information, configuration, and information-schema snapshots. Diagnosing it manually often means hours of searching files, correlating timestamps, comparing nodes, and separating a primary failure from downstream symptoms.

S2 Report Sniffer turns the Cluster Report into a structured workspace:

```text
SingleStore Cluster Report
        ↓
validate → extract → parse → correlate → score
        ↓
cluster health summary + ranked findings + evidence + recommended actions
```

Everything runs on the local machine. Findings link back to captured evidence so an engineer can validate the analysis instead of trusting an opaque verdict.

## What it does

| Capability | Result |
|---|---|
| **Streaming ingestion** | Parses Cluster Report archives in `.zip`, `.tar.gz`, `.tgz`, `.tar`, and `.gz` formats up to 10 GB with bounded memory. |
| **Cross-node correlation** | Combines tracelogs, host signals, cluster topology, configuration, and information-schema data into one investigation view. |
| **Grounded findings** | Separates documented SingleStore behavior, Toolbox defaults, observed evidence, and Sniffer-owned heuristics. |
| **Finding Severity Index** | Produces a transparent Sniffer-owned 0–100 triage index from finding severities—not an official SingleStore health verdict. |
| **Query analysis and tracing** | Treats processlist time as current-state age, filters idle sessions, traces blockers, and labels uncertain routing or node-level log correlation honestly. |
| **Replication analysis** | Separates directly measured lag, connectivity failures, paused links, throttling, backlog evidence, and unknown elapsed lag. |
| **Tracelog search** | Searches retained raw tracelogs with context windows, with a parsed-log fallback when extracted files are unavailable. |
| **Disk Intelligence** | Breaks down attributed table bytes and non-table disk overhead and restores compatible saved reports from persisted normalized signals. |
| **Table storage inventory** | Classifies columnstore and rowstore tables from documented `information_schema.TABLES.STORAGE_TYPE` values. |
| **Cluster Report comparison** | Compares two reports to highlight new, resolved, worsened, configuration, and metric changes. |
| **Optional anonymization** | Masks hostnames, IP addresses, database names, and credentials before persistent storage. |
| **Glean handoff** | Generates a local Markdown incident packet that the user may manually attach to Glean Chat. |
| **Desktop packaging** | Ships as an Electron desktop application with a bundled FastAPI backend. |

## Product principles

> **Local by default. Explainable by design. Useful under incident pressure.**

- No product telemetry or crash reporting by default.
- No automatic upload of Cluster Report contents.
- Findings include supporting evidence and affected nodes.
- Large Cluster Reports are processed with explicit file, row, and decompression limits.
- The interface is optimized for triage first and deep investigation second.

## Quick start

### Use the desktop app

1. Download the package for your platform from the [latest release](https://github.com/shahidstermain/S2-report-sniffer/releases/latest).
2. Install and launch **S2 Report Sniffer**.
3. Import a Cluster Report generated by `sdb-report collect`.
4. Keep anonymization enabled unless identifiable values are required for the investigation.
5. Start with the highest-severity findings, then validate their evidence in Queries, Replication, Logs, Storage, Nodes, and Config.

### Run from source

Requirements:

- Python 3.11+
- Node.js 22.12+

Start the backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
S2RS_DATA_DIR=./local_data uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

Start the frontend in another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. API documentation is available at `http://127.0.0.1:8000/api/docs`.

Or run `./dev-setup.sh` from the repository root.

### Integrated UI and API

```bash
cd frontend && npm run build
cd ../backend
S2RS_DATA_DIR=./local_data .venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/ui/`.

## Typical workflow

1. **Generate** a Cluster Report with `sdb-report collect`, or use `sdb-report collect-local` for one host.
2. **Upload or import** the generated Cluster Report archive.
3. **Keep anonymization enabled** unless identifiable values are required for the investigation.
4. **Wait for processing** to move from `uploading` to `processing` to `ready`.
5. **Review the Finding Severity Index** and the highest-priority findings.
6. **Inspect evidence** across Overview, Diagnostics, Nodes, Storage, Disk Intelligence, Queries, Logs, Config, and Issues.
7. **Review Long-Running Queries** and other query activity using captured processlist data.
8. **Compare Cluster Reports** when validating whether remediation improved the cluster.
9. **Create a local Glean packet** only when an external handoff is appropriate.

### How the Finding Severity Index works

```text
risk  = min(100, critical findings × 15 + warning findings × 5)
index = max(0, 100 − risk)
```

Informational findings do not reduce the index. This is a Sniffer-owned prioritization heuristic—not cluster vitals, engine health, or an official SingleStore score. Always validate the underlying evidence.

## How it works

```text
┌──────────────────────────────────────────────────────────────┐
│ Electron desktop shell or browser                            │
└──────────────────────────────┬───────────────────────────────┘
                               │ /api
┌──────────────────────────────▼───────────────────────────────┐
│ FastAPI backend                                               │
│ upload → validation → safe extraction → parsing → correlation│
│                       → scoring → SQLite/filesystem storage   │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│ React + Vite + shadcn/ui + Recharts                          │
│ /             Cluster Report workspace                       │
│ /report/:id   Cluster Report dashboard                       │
└──────────────────────────────────────────────────────────────┘
```

All application data is stored under `S2RS_DATA_DIR`—by default `~/.s2-report-sniffer`, or `./local_data` during development.

### Technology stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI and uvicorn |
| Parsing | Python generators and bounded streaming readers |
| Frontend | React 19 and Vite |
| UI | shadcn/ui, Radix UI, and Tailwind CSS |
| Charts | Recharts |
| Desktop | Electron and electron-builder |
| Persistence | SQLite and local filesystem |

## Security and privacy

- Local-only processing by default.
- Path-bounded extraction to prevent archive traversal.
- Decompressed-size limits and upload rate limits.
- A hard 10 GB Cluster Report archive limit.
- Optional pre-storage anonymization.
- Parameterized SQL queries.
- No automatic Glean upload—the generated incident packet stays local.
- Git hooks that block common secret files and credential patterns.

Read [`SECURITY_REVIEW.md`](SECURITY_REVIEW.md), [`AIRGAP_TEST_PROTOCOL.md`](AIRGAP_TEST_PROTOCOL.md), and [`LOCAL_FIRST_ARCHITECTURE.md`](LOCAL_FIRST_ARCHITECTURE.md) for the detailed controls and threat model.

## Testing

Backend:

```bash
cd backend
.venv/bin/python -m pytest -v
```

Frontend:

```bash
cd frontend
npm test
npm run build
```

Focused tracelog-search tests:

```bash
cd backend
.venv/bin/python -m pytest test_log_search.py test_log_search_raw.py -v
```

Enable repository hooks after cloning:

```bash
git config core.hooksPath .githooks
```

## Troubleshooting

| Symptom | Recommended action |
|---|---|
| Blank Electron window | Quit the app, terminate orphaned processes, and confirm port `8000` is free. |
| Invalid archive or extraction error | Confirm the input was generated with `sdb-report collect` and verify the file type. |
| Cluster Report remains in `processing` | Check backend logs for memory, decompression, or malformed-input errors. |
| Empty diagnostics panels | Generate a complete multi-node Cluster Report with the required collectors. |
| Backend unavailable | Activate the backend virtual environment and start uvicorn manually. |

## Documentation

| Document | Purpose |
|---|---|
| [`USER_MANUAL.md`](USER_MANUAL.md) | End-user walkthrough |
| [`CHANGELOG.md`](CHANGELOG.md) | Release history and notable changes |
| [`DESIGN.md`](DESIGN.md) | Interface and visual-system guidance |
| [`AGENTS.md`](AGENTS.md) | Contributor architecture and conventions |
| [`PACKAGING.md`](PACKAGING.md) | Installation, packaging, checksums, and release process |
| [`INTEGRATION.md`](INTEGRATION.md) | Integration and handoff design |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Deployment notes |
| [`PRODUCT_ROADMAP.md`](PRODUCT_ROADMAP.md) | Planned work |

## Contributing

Contributions are welcome. Start with [`AGENTS.md`](AGENTS.md), which documents the architecture, development conventions, and storage-schema allowlists.

```bash
git clone https://github.com/shahidstermain/S2-report-sniffer.git
cd S2-report-sniffer
git config core.hooksPath .githooks
./dev-setup.sh
```

Before opening a pull request, run the backend test suite and the frontend test/build commands shown above.

<div align="center">

**Built for fast, private, evidence-driven SingleStore Cluster Report triage.**

[Download latest](https://github.com/shahidstermain/S2-report-sniffer/releases/latest) · [Report a bug](https://github.com/shahidstermain/S2-report-sniffer/issues/new) · [Read the manual](USER_MANUAL.md)

</div>
