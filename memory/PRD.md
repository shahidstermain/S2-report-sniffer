# SDB Insight - SingleStore Diagnostics Dashboard

## Problem Statement
Internal web app that ingests SingleStore cluster diagnostics reports (tar.gz bundles from `sdb-report collect-and-check`), parses everything inside, and surfaces a powerful, opinionated troubleshooting dashboard with schema-grounded recommendations.

## Architecture
- **Backend**: FastAPI (Python) with MongoDB storage
- **Frontend**: React with Shadcn UI, Tailwind CSS
- **Data Flow**: Upload tar.gz → Extract → Walk directory tree → Parse 50+ collector types → Auto-detect patterns → Generate doc-linked recommendations → Store in MongoDB → Serve via REST API

## What's Been Implemented (2026-03-29)

### Backend - parsers.py
- **System commands**: free, df (disk+inode), top, uptime (load averages), dmesg (classified events)
- **OS health checks**: THP, sysctl (vm.max_map_count, swappiness, somaxconn, overcommit), process limits (nofile), NUMA
- **SingleStore data**: MV_NODES, cluster topology, cluster status, databases extended, MV_QUERIES, MV_EVENTS, pipelines, blocked queries, WLM, replication status, table statistics, processlist, MV_PROCESSLIST, resource pools, database disk usage, partitions (SHOW PARTITIONS), backup history, version history, availability groups, users, show variables, sync variables, license metadata, MV_SYSINFO
- **Trace logs**: memsql.log parsing with severity detection, critical pattern auto-detection (OOM, disk full, replication errors, crashes, lock timeouts, merge errors)
- **Dmesg classification**: OOM kills, storage faults, network issues, CPU lockups, THP warnings
- **Config health builder**: THP check, sysctl checks, process limits, variable consistency across nodes, license expiry
- **Recommendations engine**: 17 rule types with severity, doc_link, evidence, remediation, related_views

### Backend - server.py
- 15 API endpoints: upload, list, status, overview, nodes, storage, queries, logs (search/filter/paginate), pipelines, recommendations, config, delete

### Frontend - 7 Dashboard Tabs
1. **Overview**: Metric cards (nodes, topology, memory%, disk%, CPUs, version), issues summary with doc links, cluster topology map with AG groups, database disk usage chart, detected log patterns, MV_EVENTS table, log summary per node, dmesg critical events
2. **Nodes**: Per-node health cards with memory/disk/swap bars, filesystem breakdown, sort by hostname/memory/disk, role badges (MA/CA/LEAF), online/offline indicators
3. **Storage**: 4 sub-tabs - Databases (SHOW DATABASES EXTENDED), Disk Usage (treemap + bar chart), Partitions (per-host distribution with skew detection), Tables
4. **Queries**: 5 sub-tabs - Queries (paginated MV_QUERIES), Processlist, Blocked Queries, Resource Pools (pool cards with concurrency/queue), WLM
5. **Logs**: grep-style search, 5 severity filters, node dropdown filter, paginated log viewer with color-coded severity
6. **Config**: 5 sub-tabs - OS Tuning (pass/fail checklist), Variables (consistency check with MISMATCH flags), License (type/capacity/expiry/days remaining), Backups (per-DB breakdown), Users (146 users)
7. **Issues**: Grouped by category, expandable with evidence/remediation/doc links, severity filter, expand/collapse all

### Design
- Swiss/High-Contrast "Control Room" theme (light)
- Fonts: Chivo (headings), IBM Plex Sans (body), JetBrains Mono (data/logs/metrics)
- Sharp borders, dense layout, status-colored badges, no shadows/gradients

## Architecture Decision (2026-04-12)

After comparing this repo against `shahidster1711/singlestore-cluster-intelligence` (see `COMPARISON.md`), **S2 Report Sniffer is the codebase to develop further**.

Key factors:
- SuperChecker engine (2,090 lines) and parsers.py (1,582 lines) cannot be replicated quickly in any other language/stack.
- 15+ test files give a safety net for continued development.
- The cluster-intelligence repo uses Motoko (ICP blockchain backend) — a fundamental mismatch for enterprise support-bundle tooling.
- Adopt from cluster-intelligence: dark-theme OKLCH design system, TypeScript/Vite frontend migration, Web Worker streaming parser for large files, shadcn/ui components.

## Prioritized Backlog

### P0
- Error timeline heatmap (hourly error counts per node, data exists in log_summary.hourly)
- Replication lag indicator (MV_REPLICATION_STATUS with lag color coding)
- Partition health matrix (partition state visualization from SHOW CLUSTER STATUS)

### P1
- LLM copilot for natural-language queries
- Report comparison (2 reports over time)
- Backtrace explorer (memsqlBacktraces)
- Cross-referencing drill-down (click metric → jump to related logs/events)

### P2
- sar/iostat parsing (disk latency/bandwidth widgets)
- Columnstore merge health (MV_COLUMNSTORE_MERGE_STATUS)
- Pipeline error breakdown by error code
- Export/share investigation summaries
