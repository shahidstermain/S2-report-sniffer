<div align="center">
  <img src="https://img.shields.io/badge/SingleStore-AA00FF?style=for-the-badge&logo=singlestore&logoColor=white" />
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB" />
  <img src="https://img.shields.io/badge/Electron-47848F?style=for-the-badge&logo=electron&logoColor=white" />
  
  <h1>S2 Report Sniffer</h1>
  <p><strong>Offline Diagnostic Intelligence for SingleStore Clusters</strong></p>
</div>

S2 Report Sniffer is a high-performance, local-first diagnostic platform built for **Database Support Engineers**. It ingests massive offline SingleStore diagnostic bundles (`.tar.gz`, `.zip` — up to 10GB), parses raw cluster telemetry, and surfaces actionable remediation steps via an AI-powered diagnostic engine.

---

## ⚡ Why This Exists

When troubleshooting distributed databases in air-gapped or high-security environments, support engineers rely on massive diagnostic bundles (`sdb-report`). These bundles contain gigabytes of unstructured logs, OS metrics, and hardware telemetry scattered across dozens of nodes. 

Manual `grep`-based triage is slow and error-prone. **S2 Report Sniffer** automates this by:
1. **Streaming & Parsing:** Ingesting 10GB+ archives locally without triggering Out-Of-Memory (OOM) crashes.
2. **Correlation:** Stitching together `memsql.log` events, `dmesg` OOM-killer invocations, and OS metric drift.
3. **SuperChecker Engine:** Scoring findings based on operational risk and surfacing a prioritized "Fix-First" dashboard.

---

## 🏗️ Architecture & Engineering Highlights

*See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for a deep dive into the system design.*

* **Local-First Electron/FastAPI Desktop App:** Designed for air-gapped environments. Uses SQLite for persistence, a bundled Uvicorn/FastAPI backend, and a React frontend compiled into a native macOS/Windows application.
* **Bounded-Memory Stream Processing:** Uses bounded accumulators (`MAX_RAW_LOGS = 50000`) and generator-based traversal (`tarfile`, `zipfile`) to parse multi-gigabyte archives within a fixed memory footprint.
* **SuperChecker Diagnostics:** A deterministic scoring engine that translates raw cluster counters (e.g., `fsync` stalls, `ETIMEDOUT` frequencies) into categorized risk severities with direct remediation runbooks.
* **Glean Integration:** Contextual AI search that queries enterprise knowledge bases (Jira, Confluence) using exact error signatures extracted from the parsed logs.

---

## 🚀 Getting Started (Development)

### Prerequisites
- Python 3.9+
- Node.js 18+
- SingleStore `sdb-report` bundle for testing

### 1. Backend Setup (FastAPI)
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

### 2. Frontend Setup (React)
```bash
cd frontend
npm install
npm run dev
```

### 3. Desktop Build (Electron/PyInstaller)
```bash
./dev-setup.sh build:mac
```

---

## 📊 Core Diagnostic Capabilities

- **Log Timeframe Detection:** Calculates exact telemetry coverage windows per node.
- **Backup Reliability:** Identifies duration drift and silent failures in cluster backups.
- **Hardware Pressure Detection:** Tracks storage IOPS stalls (`fsync is behind`), network drops (`ETIMEDOUT`), and memory pressure (`vm.swappiness`, Transparent Huge Pages).
- **Topology Sanity:** Validates partition distribution across Aggregator and Leaf nodes.
- **Process Health:** Snapshots active query load and sleeping open transactions at the time the bundle was generated.

---

## 🔒 Security & Privacy

This tool processes sensitive database telemetry. It is explicitly architected to operate **offline**. 
- No telemetry leaves the local machine.
- Analytics and remote crash reporting are disabled.
- Secrets (if configured for external integrations like Glean) are stored locally in SQLite and encrypted.

---
*Built for Database Reliability Engineering and Advanced Support operations.*