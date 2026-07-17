# SingleStore Terminology Guide

This document is the vocabulary source of truth for S2 Report Sniffer.

Use current SingleStore documentation terminology in all user-facing text, generated findings, recommended actions, help text, documentation, screenshots, and release notes. Preserve stable internal identifiers, API fields, database columns, serialized payload keys, and test fixtures when renaming them would break compatibility.

## Core vocabulary

| Preferred terminology | Avoid in user-facing text | Notes |
|---|---|---|
| **SingleStore Cluster Report** or **Cluster Report** | diagnostic bundle, support bundle, diagnostic archive, report bundle | A Cluster Report is generated with `sdb-report collect`. Use **local report** only for output from `sdb-report collect-local`. |
| **Generate a Cluster Report** | collect a bundle, export a support bundle | Use the exact command name when useful: `sdb-report collect`. |
| **Long-Running Query / Long-Running Queries** | runaway query, runaway queries | Internal identifiers such as `runawayQueries` and JSON keys such as `runaway_queries` remain stable compatibility fields. |
| **Queries Above the Sniffer Elapsed-Time Threshold** | slow queries, suspicious queries | Use this label for the product's 30-second to 5-minute heuristic band. Do not imply that SingleStore defines a universal slow-query threshold. |
| **Active Queries** | running-query monitor | Use for the SingleStore Helios portal feature. |
| **processlist**, **SHOW PROCESSLIST**, `information_schema.PROCESSLIST`, or `MV_PROCESSLIST` | process list | Select the exact term that matches the source collector or SQL object. `MV_PROCESSLIST` contains cluster-wide process information; `PROCESSLIST` is per node. |
| **tracelog** | trace log, application log, engine log | SingleStore maintains the `memsql.log` tracelog. Use **logs** only when referring to a mixed or generic collection that includes non-tracelog sources. |
| **tracelogs directory** | logs folder | The engine variable is `tracelogsdir`. |
| **cluster system database** | metadata DB, cluster metadata database | Use the literal database name as code: `cluster`. |
| **master partition** and **replica partition** | primary partition, secondary partition | Preserve raw source-field names if an API or collector uses different labels. |
| **Leaf node**, **Master Aggregator**, **Child Aggregator** | leaf server, master node, child master | Use **Aggregator node** only when the distinction between Master and Child Aggregators is unimportant. |
| **availability group** | AG group, replication group | `AG` is acceptable in compact visualizations after the full term has been introduced. |
| **Workload Management** | WLM in prose | `WLM` is acceptable in compact tabs or code identifiers. |
| **resource pool** | workload pool | Match `RESOURCE_POOL` when referring to processlist data. |
| **recommended action** | fix, recommendation | Use **remediation** for the overall process or a technical remediation procedure. |
| **Cluster Health Score** | health score when ambiguous | The score is a Report Sniffer triage signal, not an official SingleStore health verdict. |
| **Cluster Report comparison** | snapshot comparison when the inputs are reports | Use **snapshot** only for a collector or information-schema snapshot inside a Cluster Report. |

## Product-specific heuristics

S2 Report Sniffer applies heuristics that are not universal SingleStore product thresholds. Label these clearly.

- **Long-Running Queries (>5 min)** is a Sniffer prioritization threshold applied to captured processlist rows. SingleStore documentation uses the term *long running queries* but does not define one universal duration cutoff for every workload.
- **Queries Above the Sniffer Elapsed-Time Threshold (30s–5 min)** is a product-defined investigation band. Do not label it simply **Slow Queries**.
- **Cluster Health Score** and grades A–F are Report Sniffer triage constructs. Describe them as context, not a product verdict.
- Any threshold derived from operational experience rather than documentation must be marked as **heuristic** in grounding metadata and supporting text.

## Compatibility rules

Do not rename these solely for terminology cleanup:

- checker IDs such as `runawayQueries` and `slowQueries`
- API and JSON fields such as `runaway_queries`, `runaway_patterns`, `slow_queries`, `processlist`, and `log_summary`
- database columns, migration names, serialized report payloads, and route paths
- collector names and physical source paths such as `memsqlTracelogs`, `memsql.log`, and `informationSchemaMvProcesslist.json`

Map legacy identifiers to documentation-aligned display labels at the presentation boundary.

## Capitalization and style

- Capitalize **SingleStore**, **Cluster Report**, and named product features.
- Use sentence case for headings and labels unless an existing component intentionally uses title case.
- Hyphenate **long-running**, **local-first**, **cross-node**, and **high-memory** when used as modifiers.
- Write **synchronous-to-asynchronous transition**, not `synchronous→asynchronous`, in prose. Symbols remain acceptable in compact diagrams.
- Use backticks for commands, variables, SQL objects, source files, API fields, and stable identifiers.

## Documentation references

Use current pages where possible and verify links before adding them to grounding metadata.

- Generating a Cluster Report: https://docs.singlestore.com/db/v9.0/reference/troubleshooting-reference/generating-a-cluster-report/
- `sdb-report collect`: https://docs.singlestore.com/db/v9.0/reference/singlestore-tools-reference/sdb-report-commands/collect/
- Trace Log Location and Management: https://docs.singlestore.com/db/v9.0/reference/troubleshooting-reference/trace-log/location-and-management/
- `MV_PROCESSLIST`: https://docs.singlestore.com/db/v9.0/reference/information-schema-reference/query-performance-workload-management-and-statistics/mv-processlist/
- `SHOW PROCESSLIST`: https://docs.singlestore.com/db/v9.0/reference/sql-reference/show-commands/show-processlist/
- Query Errors — Long Running Queries: https://docs.singlestore.com/db/v9.0/reference/troubleshooting-reference/query-errors/

## Review checklist

Before merging user-facing copy:

1. Search for legacy phrases such as `diagnostic bundle`, `support bundle`, and `runaway quer`.
2. Confirm the wording matches this guide and current SingleStore documentation.
3. Confirm stable API fields and identifiers remain backward compatible.
4. Update tests that assert user-visible text.
5. Check capitalization, hyphenation, and whether a threshold is clearly identified as a Sniffer heuristic.
