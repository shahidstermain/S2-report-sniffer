<div align="center">

<img src="docs/assets/logo.svg" alt="S2 Report Sniffer" width="150" />

# S2 Report Sniffer

### Turn large SingleStore diagnostic bundles into an actionable triage dashboard—locally, privately, and fast.

**A local-first analyzer for `sdb-report` archives, built for support engineers who need evidence—not more grep.**

<p>
  <a href="../../releases"><img src="https://img.shields.io/badge/download-latest%20release-00d992?style=for-the-badge&labelColor=09090b" alt="Download latest release" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/shahidstermain/S2-report-sniffer?style=for-the-badge&color=b100ff&labelColor=09090b" alt="License" /></a>
  <img src="https://img.shields.io/badge/privacy-local--first-00d992?style=for-the-badge&labelColor=09090b" alt="Local-first" />
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-b100ff?style=for-the-badge&labelColor=09090b" alt="Platforms" />
</p>

[Quick start](#quick-start) · [What it does](#what-it-does) · [Architecture](#architecture) · [Security](#security-and-privacy) · [Contributing](#contributing)

</div>

---

## The problem

A SingleStore `sdb-report` can contain gigabytes of node logs, kernel output, system metadata, configuration, and information-schema snapshots. Diagnosing it manually often means hours of searching files, correlating timestamps, comparing nodes, and separating a primary failure from its downstream noise.

S2 Report Sniffer turns that archive into a structured workspace:

```text
sdb-report archive
        ↓
validate → extract → parse → correlate → score
        ↓
health summary + ranked findings + evidence + remediation
```

Everything runs on the local machine. Customer data is not uploaded to a hosted service.

## What it does

| Capability | Result |
|---|---|
| **Streaming ingestion** | Parses `.zip`, `.tar.gz`, `.tgz`, `.tar`, and `.gz` archives up to 10 GB with bounded memory. |
| **Cross-node correlation** | Combines logs, host signals, topology, configuration, and information-schema data into one incident view. |
| **Risk-ranked findings** | Prioritizes findings as Immediate, Quick Win, Soon, or Backlog with evidence and remediation guidance. |
| **Health scoring** | Produces a 0–100 health score and grade for rapid triage—not as a substitute for engineering judgment. |
| **Log search** | Searches retained raw logs with context windows, with a parsed-log fallback when extracts are unavailable. |
| **Snapshot comparison** | Compares two reports to highlight new, resolved, worsened, configuration, and metric changes. |
| **Optional anonymization** | Masks hosts, IP addresses, database names, and credentials before persistent storage. |
| **Glean handoff** | Generates a local Markdown incident packet that the user may manually attach to Glean Chat. |
| **Desktop packaging** | Ships as an Electron desktop application with a bundled FastAPI backend. |

## Product principles

> **Local by default. Explainable by design. Useful under incident pressure.**

- No product telemetry or crash reporting by default.
- No automatic upload of report contents.
- Findings include supporting evidence and affected nodes.
- Large archives are processed with explicit file, row, and decompression limits.
- The interface is optimized for triage first and deep investigation second.

## Quick start

### Desktop application

Download the current build from the [Releases](../../releases) page, install it, and open an `sdb-report` archive from the home screen.

Build the macOS Apple Silicon package from source:

```bash
PYTHON_BIN=python3.11 bash scripts/build-desktop.sh
```

The installer is written to:

```text
dist/installers/S2 Report Sniffer-1.0.0-arm64.dmg
```

### Run from source

Requirements:

- Python 3.11+
- Node.js 20+

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

You can also run `./dev-setup.sh` from the repository root.

### Integrated UI and API

```bash
cd frontend && npm run build
cd ../backend
S2RS_DATA_DIR=./local_data .venv/bin/uvicorn server:app \
  --host 127.0.0.1 \
  --port 8000
```

Open `http://127.0.0.1:8000/ui/`.

## Typical workflow

1. **Upload or import** an archive created by `sdb-report collect`.
2. **Keep anonymization enabled** unless identifiable values are required for the investigation.
3. **Wait for processing** to move from `uploading` to `processing` to `ready`.
4. **Review the health score** and the highest-priority findings.
5. **Inspect evidence** across Overview, Diagnostics, Nodes, Storage, Queries, Logs, Config, and Issues.
6. **Compare snapshots** when validating whether a remediation improved the cluster.
7. **Create a local Glean packet** only when an external handoff is appropriate.

### Health grades

| Grade | Score | Triage meaning |
|:---:|:---:|---|
| **A** | 90–100 | Healthy |
| **B** | 80–89 | Minor issues |
| **C** | 70–79 | Review findings |
| **D** | 60–69 | Investigate promptly |
| **F** | 0–59 | Prioritize Immediate findings |

The health score provides context. Always validate the underlying evidence and remediation.

## Architecture

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
│ /             report workspace                               │
│ /report/:id   diagnostic dashboard                           │
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
- A hard 10 GB archive limit.
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

Focused log-search tests:

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
| Invalid archive or extraction error | Confirm the input was produced by `sdb-report collect` and verify the file type. |
| Report remains in `processing` | Check backend logs for memory, decompression, or malformed-input errors. |
| Empty diagnostic panels | Use a complete multi-node report with infrastructure data included. |
| Backend unavailable | Activate the backend virtual environment and start uvicorn manually. |

## Documentation

| Document | Purpose |
|---|---|
| [`USER_MANUAL.md`](USER_MANUAL.md) | End-user walkthrough |
| [`DESIGN.md`](DESIGN.md) | Interface and visual-system guidance |
| [`AGENTS.md`](AGENTS.md) | Contributor architecture and conventions |
| [`PACKAGING.md`](PACKAGING.md) | Electron and PyInstaller packaging |
| [`INTEGRATION.md`](INTEGRATION.md) | Integration and handoff design |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Deployment notes |
| [`PREPROD_TEST_REPORT.md`](PREPROD_TEST_REPORT.md) | Pre-release validation |
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

## License

See [`LICENSE`](LICENSE).

---

<div align="center">

Built for fast, evidence-driven SingleStore incident triage.

</div>
