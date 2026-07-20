# System Architecture: S2 Report Sniffer

## Overview
S2 Report Sniffer is architected as a **local-first, thick-client desktop application** tailored for processing highly sensitive SingleStore Cluster Report data in air-gapped environments.

## The 10 GB Ingestion Problem
SingleStore Cluster Reports can contain gigabytes of compressed tracelogs, information-schema snapshots, and OS statistics. Loading the complete input into memory can exhaust a standard workstation.

### Solution: Bounded Stream Processing
The backend (`backend/parsers.py`) implements a bounded-memory ingestion pipeline:
1. **Chunked Scratch Extraction:** Uploads and archive members are copied in bounded chunks into a private scratch directory. Current parsing walks that extracted tree; it does not claim zero-copy archive processing.
2. **Deterministic Caps:** Archive bytes, member count, per-member size, path depth, compression ratio, JSON rows, and retained logs are bounded through shared policy and parser limits.
3. **Time-Bucketed Aggregation:** Telemetry is downsampled on the fly. Raw timestamps are bucketed into hourly aggregates (e.g., `etimedout_per_hour`) before being handed to the scoring engine.

## Component Architecture

```mermaid
graph TD
    UI[React Frontend (Electron)] -->|REST API| API[FastAPI Backend]
    
    subgraph Core Engine
    API -->|1. Extract| Validator[Validation & Streamer]
    Validator -->|2. Parse| Parsers[Log & Metric Parsers]
    Parsers -->|3. Score| SuperChecker[SuperChecker Rules Engine]
    end
    
    SuperChecker -->|4. Persist| DB[(SQLite)]
    DB -->|5. Serve| API
```

### 1. Frontend (React / Vite)
- Serves the user interface for exploring diagnostic data.
- Employs data visualization (D3/SVG) to render cluster topology, heatmaps, and log severity distribution.

### 2. Backend (FastAPI)
- Handles the ingestion, parsing, and scoring of SingleStore Cluster Reports.
- Uses `uvicorn` as the ASGI server.
- Persists report metadata and leased analysis jobs in SQLite; interrupted jobs are reclaimable after their leases expire.

### Normalized analysis payloads

`backend/parsers.py` produces compact normalized analysis fields before `backend/server.py` persists `report.json`. API endpoints serve these saved fields and must not perform heavy Cluster Report rescans.

When adding a parser-owned payload, update the background persistence document in `_parse_report_background()` as part of the same change. Disk Intelligence depends on this invariant:

```text
resolve_disk_reclamation()
    → disk_intelligence
    → cluster_overhead
    → blobs_referenced_delta
    → report.json
    → /api/reports/{id}/disk-intelligence
```

The Disk Intelligence endpoint supports a one-time compatibility migration for earlier v1.1.0 reports. If `disk_intelligence` is absent but normalized `cluster_overhead` exists, it rebuilds the presentation payload from saved signals and persists it. It does not reopen or rescan the original Cluster Report.

### 3. SuperChecker Engine
The brain of the platform. It takes normalized parser outputs and maps them to operational risk.
- **Pattern Matching:** Identifies known anti-patterns (e.g., Transparent Huge Pages enabled, excessive swapped memory, uneven partition distribution).
- **Risk Scoring:** Assigns a deterministic risk score to prioritize engineer focus.
- **Remediation Mapping:** Links identified risks to direct mitigation strategies and documentation.

## Security Posture
Because this tool handles sensitive SingleStore Cluster Reports:
- **Zero Egress:** The core application has no cloud dependencies (Supabase and MongoDB were explicitly stripped out in favor of local SQLite).
- **Ephemeral Processing:** Uploaded `.tar.gz` files are staged in the OS temporary directory and aggressively cleaned up post-analysis.
