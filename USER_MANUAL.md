# S2 Report Sniffer — Team User Guide

## Purpose

S2 Report Sniffer helps Support Engineers investigate SingleStore cluster issues by analyzing SingleStore Cluster Reports locally and producing:

- cluster and node overview dashboards
- prioritized findings with severity, risk score, confidence, evidence, and recommended actions
- workload, processlist, storage, and configuration summaries
- searchable tracelogs with context and pagination
- optional comparison and export workflows

The application is designed for offline and air-gapped environments. Cluster Report data stays on the machine unless the user explicitly exports or shares it.

## Generate a Cluster Report

For a full cluster, use SingleStore Toolbox:

```bash
sdb-report collect
```

For one host only:

```bash
sdb-report collect-local
```

Unless an output path is specified, `sdb-report` writes a compressed report archive in the current directory.

## Quick start

1. Launch the desktop application.
2. Upload a SingleStore Cluster Report (`.zip`, `.tar.gz`, `.tgz`, `.tar`, or `.gz`) or import an extracted report directory.
3. Keep anonymization enabled unless identifiable values are required for the investigation.
4. Wait for processing to complete.
5. Open the Cluster Report dashboard and review:
   - Overview
   - Issues and recommended actions
   - Diagnostics
   - Nodes
   - Storage
   - Disk Intelligence
   - Workload and Queries
   - Logs
   - Configuration

## How the desktop application works

The desktop application is a local-first stack:

- Electron starts a bundled FastAPI backend on `127.0.0.1`.
- The React interface is served from `/ui/`, so the interface and API share one local origin.
- Results are stored in SQLite and per-report files under `S2RS_DATA_DIR`.
- No hosted analysis service is required.

## What happens when a Cluster Report is added

### 1. Upload and validation

The backend streams the input to disk and validates:

- accepted archive format
- the 10 GB upload limit
- basic archive integrity
- safe paths and member types
- decompressed-size limits

If validation fails, the interface shows an error and no report workspace is created.

### 2. Safe extraction

The backend extracts the Cluster Report to a bounded local directory:

- path traversal is rejected
- unsafe links and special archive members are ignored or rejected
- total extracted size is capped to protect local disk space

### 3. Signal extraction

The parser reads the collectors available in the Cluster Report, including:

- SingleStore tracelogs such as `memsql.log`
- host information such as sysctl, memory, disk, ulimit, process, and dmesg output
- information-schema snapshots such as cluster status, variables, `PROCESSLIST`, `MV_PROCESSLIST`, backup history, partitions, and workload data
- cluster topology and node-role information

The application normalizes these inputs into compact investigation signals rather than loading every raw file into memory. Large datasets may be sampled or capped to keep the application responsive.

### 4. Findings and Cluster Health Score

The analysis engine evaluates the extracted signals and emits findings with:

- severity: `critical`, `warning`, or `info`
- risk score: `0–100`
- confidence
- evidence and affected nodes
- recommended action
- documentation grounding or a clearly identified heuristic basis

The **Cluster Health Score** and A–F grade are S2 Report Sniffer triage aids. They are not official SingleStore health verdicts. Always inspect the evidence behind the score.

### 5. Local persistence

The backend stores:

- Cluster Report metadata in SQLite
- normalized report data in `report.json`
- parsed tracelog entries in `logs.jsonl`
- a retained extracted report root when it is within the configured size limit

The interface requests only the data needed by each screen.

## Using the interface

### Overview

Start here to review:

- Cluster Health Score and grade
- node status and topology
- backup, workload, storage, and pressure indicators
- tracelog coverage by node
- the highest-priority findings

### Issues and recommended actions

Use this area to determine what to investigate first:

- prioritize Immediate and high-risk findings
- open a finding to inspect evidence, grounding, affected nodes, and recommended actions
- use **View in Logs** when the finding includes a valid tracelog search term
- distinguish documented criteria from Sniffer heuristics

### Workload and Queries

This area uses captured query and processlist data.

- **Long-Running Queries** are queries exceeding the Sniffer prioritization threshold of five minutes.
- **Queries Above the Sniffer Elapsed-Time Threshold** are queries in the 30-second to five-minute heuristic band.
- These thresholds are Sniffer investigation aids; SingleStore documentation does not prescribe one universal duration cutoff for every workload.
- Review blocking queries, open transactions, resource pools, workload management data, repeated query patterns, and queries with the highest captured memory use.
- `MV_PROCESSLIST` represents cluster-wide process information, while `information_schema.PROCESSLIST` is per node.

Stable internal API fields may still be named `runaway_queries`, `runaway_patterns`, or `slow_queries`; the interface maps them to the terminology above.

### Logs

Use the Logs area for tracelog investigation:

- search for actual message text or error patterns
- filter by node or hostname
- use context windows when raw extracted tracelogs are retained
- paginate rather than loading the entire tracelog set

SingleStore maintains the `memsql.log` tracelog in the configured tracelogs directory. The application may also display generic **logs** when a view combines tracelogs with other sources.

If the view has no entries, the Cluster Report may not contain the required tracelog collectors, or retained raw files may have exceeded the local size limit.

### Diagnostics

Diagnostics panels depend on collector availability. A complete multi-node Cluster Report generally provides more useful coverage than a sparse file upload or local-only report.

The interface indicates when a signal family is unavailable rather than displaying invented zero values.

### Storage and table storage types

The Storage area shows database disk usage, partitions, table statistics, and a table-level storage inventory when the required information-schema snapshot is available.

Table classification uses exact documented values from `information_schema.TABLES.STORAGE_TYPE`:

- `COLUMNSTORE` is displayed as **Columnstore**.
- `INMEMORY_ROWSTORE` is displayed as **Rowstore**.
- Missing or unrecognized values are displayed as **Unknown** rather than inferred.

Views and system views are excluded from the inventory. Columnstore is also known as Universal Storage in current SingleStore terminology.

### Disk Intelligence

Disk Intelligence is a Sniffer storage-analysis view, not an official SingleStore health metric. It summarizes:

- total captured disk usage for SingleStore data directories
- bytes attributed to tables
- non-table disk overhead
- transaction logs, snapshots, tracelogs, plancache, audit logs, spill, cores, and other overhead buckets
- on-disk columnstore blob comparison when the required collector data is available

Estimate banners identify incomplete-node or HA-adjusted inputs. A measured-looking zero is not shown when the required signals are absent.

Reports analyzed by the refreshed v1.1.0 build persist the complete normalized Disk Intelligence payload. Compatible reports saved by an earlier v1.1.0 build are hydrated once from their existing `cluster_overhead` and `blobs_referenced_delta` signals. This repair does not rescan or require re-importing the original Cluster Report.

### Compare Cluster Reports

Select two ready Cluster Reports in chronological order to compare:

- new findings
- resolved findings
- worsened findings
- configuration changes
- metric changes

Use comparison when validating whether a remediation improved the cluster.

## Local data, privacy, and retention

### Local-first behavior

- Cluster Reports are processed on the local machine.
- No cloud upload is required.
- Optional usage analytics are allowlisted, opt-in, and stored locally.
- Glean handoff creates a local Markdown packet; nothing is sent until the user explicitly attaches it.

### Data location

Default:

```text
~/.s2-report-sniffer
```

Override with `S2RS_DATA_DIR` before launching the application.

Typical contents:

```text
reports.sqlite
reports/<report_id>/report.json
reports/<report_id>/logs.jsonl
reports/<report_id>/extracted/
```

### Retention guidance

- Treat Cluster Reports and generated investigation data as sensitive.
- Do not paste customer-identifiable tracelog content into public channels.
- Delete reports when the investigation is closed or according to internal retention policy.
- Prefer deleting an individual report from the report list rather than wiping the complete data directory.

## Offline updates

1. Obtain a newer installer from a trusted internal source.
2. Copy it to the offline machine.
3. Use the desktop update workflow or run the installer directly.
4. Existing data remains in `S2RS_DATA_DIR` unless it is explicitly removed.

## Troubleshooting

### Blank interface

Possible causes:

- the bundled backend failed to start
- UI assets failed to load
- port `8000` is already in use

Actions:

1. Quit and restart the application.
2. Terminate orphaned S2 Report Sniffer processes.
3. Confirm port `8000` is available.
4. In a development environment, verify that `/api/health` responds.

### Upload fails immediately

Possible causes:

- unsupported file type
- damaged or encrypted archive
- upload or decompression limit exceeded
- unsafe archive structure

Actions:

1. Confirm the input is a Cluster Report generated by `sdb-report collect` or `collect-local`.
2. Verify that the archive is `.zip`, `.tar.gz`, `.tgz`, `.tar`, or `.gz`.
3. Re-copy or regenerate the report.
4. Remove archive encryption before importing it.

### Processing is slow or appears stuck

Possible causes:

- very large Cluster Report or tracelog volume
- limited free disk space
- unusually large information-schema snapshots

Actions:

1. Review backend progress and logs.
2. Ensure adequate free disk space for extraction.
3. Close other memory-intensive applications.
4. Regenerate the Cluster Report with only the collectors required for the investigation when appropriate.

### Empty diagnostics

Possible causes:

- local-only or sparse report input
- missing `MV_EVENTS`, sysinfo, CPU, or network collectors
- report generated with a limited collector set

Action: generate and import a complete multi-node Cluster Report with the required collectors.

### Disk Intelligence is empty

1. Confirm the app was installed from the refreshed v1.1.0 release.
2. Reopen Disk Intelligence. Compatible saved v1.1.0 reports hydrate automatically from persisted normalized signals.
3. If the view still reports no data, review collector availability and confirm the Cluster Report contains host disk-usage signals.
4. Missing columnstore segment detail affects the blobs-versus-referenced comparison, but does not by itself prevent the disk-overhead summary from rendering.

### No tracelog entries

Possible causes:

- tracelog collectors were not included
- retained raw files exceeded the configured local limit
- parsed tracelog rows were capped

Actions:

1. Confirm the Cluster Report includes the `memsqlTracelogs` collector.
2. Regenerate the report with an appropriate tracelog time range or size.
3. Re-import the Cluster Report.

### Reset local data

Close the application and remove `~/.s2-report-sniffer`, or the directory configured by `S2RS_DATA_DIR`.

### Delete one report

Use the trash action on the report list. This removes the report metadata and its local report directory.

## FAQ

### Does S2 Report Sniffer upload Cluster Report data to the internet?

No. Processing occurs on `127.0.0.1` and results are stored locally. Sharing and export actions are explicit.

### What inputs are supported?

- full Cluster Reports generated by `sdb-report collect`
- local reports generated by `sdb-report collect-local`
- extracted Cluster Report directories
- sparse individual logs and configuration files for limited analysis

### What should be provided when escalating an application issue?

Provide:

- the report ID
- the exact symptom and processing stage
- screenshots of the failing screen
- desktop and backend logs
- whether the input was a full Cluster Report, local report, extracted directory, or sparse file

Do not include customer-identifiable Cluster Report contents in public issue trackers.
