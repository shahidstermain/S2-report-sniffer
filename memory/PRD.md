# SDB Insight - SingleStore Diagnostics Dashboard

## Problem Statement
Internal web app that ingests SingleStore cluster diagnostics reports (tar.gz bundles from `sdb-report collect-and-check`), parses everything inside, and surfaces a troubleshooting dashboard for support engineers.

## Architecture
- **Backend**: FastAPI (Python) with MongoDB storage
- **Frontend**: React with Shadcn UI, Tailwind CSS
- **Data Flow**: Upload tar.gz → Extract → Walk directory tree → Parse all collectors → Store in MongoDB → Serve via REST API

## User Personas
- SingleStore support engineers diagnosing customer clusters
- Internal technical team comfortable with data-dense UIs

## Core Requirements
1. Accept .tar.gz cluster report upload
2. Parse: cluster topology, node metrics, storage, queries, logs, events, pipelines
3. Generate automated recommendations for common issues
4. Present data via dashboard pages: Overview, Nodes, Storage, Queries, Logs, Recommendations

## What's Been Implemented (2026-03-29)

### Backend
- `server.py`: FastAPI with 12 API endpoints (upload, list, status, overview, nodes, storage, queries, logs, pipelines, recommendations, delete)
- `parsers.py`: Comprehensive parser that handles:
  - System commands (free, df, top, uptime, dmesg)
  - SingleStore JSON data (MV_NODES, cluster topology, databases, queries, events, pipelines, blocked queries, WLM, replication status, table statistics, processlist)
  - Trace logs (memsql.log) with severity detection
  - Auto-generated recommendations engine (memory, disk, swap, OOM, offline nodes, errors, version mismatches)
- Background async parsing with status polling
- Log search with severity, node, and text filters + pagination

### Frontend
- `ReportList.jsx`: Upload dropzone + reports table with status polling
- `ReportDashboard.jsx`: Tab-based dashboard (Overview, Nodes, Storage, Queries, Logs, Recommendations)
- `ClusterOverview.jsx`: Metric cards, node map with health indicators, issues summary, events table, log summary
- `NodeHealth.jsx`: Per-node cards with memory/disk/swap bars, sorting by hostname/memory/disk
- `StorageDistribution.jsx`: Databases table, table statistics
- `WorkloadQueries.jsx`: Queries with pagination, processlist, blocked queries, WLM sub-tabs
- `LogExplorer.jsx`: grep-style search, severity filters, node filters, paginated log viewer
- `Recommendations.jsx`: Expandable findings grouped by category with evidence and remediation

### Design
- Swiss/High-Contrast "Control Room" theme (light)
- Fonts: Chivo (headings), IBM Plex Sans (body), JetBrains Mono (data/logs)
- Sharp borders, dense layout, status-colored badges

## Prioritized Backlog

### P0 (Next)
- Pipelines page (data parsed but UI not yet built)
- Report comparison (2 reports over time)

### P1
- LLM copilot for natural-language queries about reports
- Error timeline visualization (hourly error counts chart)
- Log context navigation (surrounding lines for a chosen event)

### P2
- Multi-tenant support
- Plugin architecture for new collectors
- Export/share report summaries
- Bookmarking specific findings
