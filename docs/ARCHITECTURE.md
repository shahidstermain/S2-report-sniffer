# System Architecture: S2 Report Sniffer

## Overview
S2 Report Sniffer is architected as a **local-first, thick-client desktop application** tailored for processing highly sensitive database telemetry in air-gapped environments. 

## The 10GB Ingestion Problem
SingleStore `sdb-report` diagnostic bundles routinely exceed 5GB-10GB of compressed data containing distributed system logs, system tables, and OS statistics. Loading this into memory for analysis will immediately crash a standard web backend with an OOM error.

### Solution: Bounded Stream Processing
The backend (`backend/parsers.py`) implements a bounded-memory ingestion pipeline:
1. **Generator-based Traversal:** Archives are read sequentially using Python's `tarfile` and `zipfile` streaming APIs. The files are not fully decompressed to disk unless necessary.
2. **Deterministic Caps:** Accumulators cap memory usage (e.g., `MAX_RAW_LOGS = 50000`). Once the statistical significance threshold of a log pattern is reached, further occurrences increment counters rather than allocating memory.
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
- Handles the ingestion, parsing, and scoring of bundles.
- Uses `uvicorn` as the ASGI server.
- Completely stateless between requests, relying on SQLite for persistence.

### 3. SuperChecker Engine
The brain of the platform. It takes normalized parser outputs and maps them to operational risk.
- **Pattern Matching:** Identifies known anti-patterns (e.g., Transparent Huge Pages enabled, excessive swapped memory, uneven partition distribution).
- **Risk Scoring:** Assigns a deterministic risk score to prioritize engineer focus.
- **Remediation Mapping:** Links identified risks to direct mitigation strategies and documentation.

## Security Posture
Because this tool handles enterprise diagnostic bundles:
- **Zero Egress:** The core application has no cloud dependencies (Supabase and MongoDB were explicitly stripped out in favor of local SQLite).
- **Ephemeral Processing:** Uploaded `.tar.gz` files are staged in the OS temporary directory and aggressively cleaned up post-analysis. 