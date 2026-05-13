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

## ⚡ Why This Exists

When troubleshooting distributed databases in **air-gapped** or high-security environments, support engineers rely on massive diagnostic bundles (`sdb-report`). These contain gigabytes of unstructured logs, OS metrics, and hardware telemetry across dozens of nodes.

**Manual `grep`-based triage is slow and error-prone.** S2 Report Sniffer automates this:

| Capability | What It Does |
|-----------|-------------|
| 📥 **Streaming Ingestion** | Parse 10GB+ archives without OOM crashes |
| 🔗 **Correlation** | Stitch together `memsql.log`, `dmesg`, OS metrics |
| 🎯 **SuperChecker** | Score findings by operational risk |
| 🤖 **Glean Integration** | Query enterprise knowledge bases |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    S2 Report Sniffer                        │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │   Electron   │◀──│   FastAPI    │◀──│   Parsers    │  │
│  │  Desktop UI  │   │   Backend    │   │   Engine     │  │
│  └──────────────┘   └──────────────┘   └──────────────┘  │
│         │                  │                   │            │
│         ▼                  ▼                   ▼            │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │   SQLite     │   │  Diagnostic  │   │  SuperChecker│  │
│  │  (Local DB)  │   │   Bundles    │   │   Scoring    │  │
│  └──────────────┘   └──────────────┘   └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 Key Features

### Diagnostic Capabilities
- **Log Timeframe Detection** — Exact telemetry coverage per node
- **Backup Reliability** — Silent failures, duration drift detection
- **Hardware Pressure** — IOPS stalls, network drops, memory pressure
- **Topology Sanity** — Partition distribution validation
- **Process Health** — Active queries & sleeping transactions

### Engineering Highlights
- 🔒 **Local-First** — Zero data leaves your machine
- 💾 **Bounded Memory** — Fixed footprint with generators
- 🎯 **Risk Scoring** — Prioritized "Fix-First" dashboard
- 🤖 **AI-Powered** — Glean integration for context search

---

## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- Node.js 18+

### Backend Setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

### Desktop Build
```bash
./dev-setup.sh build:mac
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

## 🔒 Security

This tool processes sensitive database telemetry. It's architected for **offline operation**:

- ❌ No telemetry leaves your local machine
- ❌ No remote crash reporting
- ✅ Secrets encrypted in local SQLite

---

<p align="center">
  <img src="https://komarev.com/ghpvc/?repo=S2-report-sniffer&label=Clones&color=aa00ff&style=flat" />
</p>

<div align="center">
  Built for Database Reliability Engineering & Advanced Support Operations 🔧
</div>
