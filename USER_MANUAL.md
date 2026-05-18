# S2 Report Sniffer — Team User Guide (Offline Desktop)

## Purpose

S2 Report Sniffer helps Support Engineers troubleshoot SingleStore cluster issues faster by analyzing SingleStore support bundles locally and producing:

- cluster and node overview dashboards
- health findings (SuperChecker) with severity, score, confidence, and fix-first ordering
- workload and storage summaries
- searchable logs with pagination

This tool is designed for offline / air-gapped environments: report data stays on the machine unless you explicitly export/copy it.

## Quick Start

1. Launch the desktop app.
2. Upload a report bundle (`.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`).
3. Wait for parsing to complete.
4. Open the report dashboard and review:
   - Cluster Overview
   - Recommendations
   - Logs
   - Nodes / Storage / Workload

## How The Desktop App Works (High Level)

The desktop app is a local-first stack:

- Electron desktop shell starts a bundled FastAPI backend on `127.0.0.1` (localhost).
- The React UI is served from the backend under `/ui/` so UI and API share one local origin.
- Results are stored locally in SQLite + per-report JSON files.

## What Happens When You Upload A Report (Behind The Scenes)

### Stage 1: Upload and validation

When you select a bundle and click Upload:

- the UI uploads the file as multipart form data to `POST /api/reports/upload`
- the backend streams the upload to a temporary file on disk (not RAM)
- the backend validates:
  - extension/type (`.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`)
  - upload size (default max: 10 GB)
  - archive structure (basic integrity checks)
  - decompression bomb protection (expanded size is capped for safety; default cap: 50 GB)

If validation fails, the UI shows an error and no report is created.

### Stage 2: Extraction

If validation passes:

- the backend extracts the archive to a temporary directory
- unsafe archive paths are rejected
- symlinks / special tar members are ignored during extraction
- extraction is capped by a maximum total extracted size to prevent disk exhaustion

### Stage 3: Parsing (signal extraction)

The parser walks the extracted directory tree and reads key collectors:

- SingleStore logs (`memsql.log` / trace logs patterns, depending on bundle)
- OS metrics (sysctl, free, df, ulimit, dmesg, etc.)
- Info schema snapshots (cluster status, variables, processlist, backup history, partitions, workload tables)

The goal is not to store everything. It normalizes the bundle into compact “signals” that can be scored and rendered:

- log coverage per node (first/last timestamps)
- backup reliability summary (success/failure counts, latest duration)
- network/storage pressure indicators (time-bucketed event counts)
- memory pressure indicators (THP, swappiness, OOM events)
- cluster layout sanity (partition distribution by role/host)
- process snapshot (active queries, sleeping open transactions)

Large raw datasets may be sampled or capped to keep the app responsive.

### Stage 4: Scoring (SuperChecker)

After parsing, the SuperChecker engine evaluates rules and emits findings:

- Severity: `critical`, `warning`, `info`
- Risk score: `0–100` (higher is more urgent)
- Confidence: `0.05–1.00` (higher means stronger evidence)
- Fix First: highlights likely root-cause findings
- Correlated findings: groups issues that are likely related

### Stage 5: Persistence (local storage)

Finally, the backend persists results locally:

- Report metadata in SQLite
- Report payload as JSON
- Parsed logs in a line-delimited JSON file (paged by the API)

The UI only requests what it needs for each screen, so large logs are not loaded all at once.

## What You’ll See In The UI

### Cluster Overview

Use this as the first pass:

- cluster KPIs (backups, queries, pressure events)
- log coverage strip (per node) to understand whether the bundle includes the timeframe you care about
- node summaries to spot outliers (resource pressure, role distribution)

### Recommendations

Use this for “what should I do first?”:

- sort by severity and “Fix First”
- open correlated findings to identify root cause patterns
- use the finding text + evidence snippet to guide the next investigation step

### Logs

Use this for deep dives:

- search text (supports partial matches)
- filter by node/host prefix
- paginate rather than loading everything

If a report contains no parsed logs, that usually means the bundle didn’t include the relevant tracelog collectors.

## Local Data, Privacy, and Retention

### Local-only by design

- The desktop app runs entirely on your machine.
- Reports are stored locally.
- No cloud upload is required.

### Where data is stored

Default location:

- `~/.s2-report-sniffer`

Override:

- set `S2RS_DATA_DIR` before launching the app to store data in a different location (useful for external drives or per-case isolation)

Contents:

- `reports.sqlite` (metadata index)
- `reports/<report_id>/report.json` (parsed/scored payload)
- `reports/<report_id>/logs.jsonl` (paged logs)

### Retention guidance (team policy)

- Treat uploaded bundles and generated reports as sensitive.
- Do not paste raw logs with customer identifiers into public channels.
- Delete old reports from `~/.s2-report-sniffer` when a case is closed or per your internal retention policy.
- Prefer deleting individual reports from the Report List first; only wipe the entire directory when you intend to reset everything.

## Offline Updates

To update without internet:

1. Obtain a newer installer package from a trusted source.
2. Copy it to the offline machine.
3. In the app: `File -> Install Update Package`.
4. Run the installer that opens.

User data persists in the local data directory across updates.

## Troubleshooting / Runbook

### Symptom: App opens but shows a blank UI

Likely causes:

- backend failed to start
- UI assets failed to load

Steps:

1. Restart the app.
2. If it still shows a blank UI, collect desktop app logs and escalate.
3. If you have a dev environment available, run the backend locally and verify `/api/health` responds (this helps distinguish UI vs backend failure).

### Symptom: Upload fails immediately

Likely causes:

- unsupported file type
- corrupted archive
- encrypted zip
- decompression protection triggered

Steps:

1. Confirm the bundle is one of: `.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`.
2. Re-download / re-copy the bundle and retry.
3. If the bundle is encrypted, re-export it without encryption.
4. If you suspect archive expansion is too large, regenerate a slimmer bundle (or split collectors).

### Symptom: Parsing is stuck or extremely slow

Likely causes:

- unusually large bundles (many nodes, huge log volume)
- disk pressure on the local machine

Steps:

1. Wait a few minutes and watch progress messages.
2. Ensure enough free disk space (bundle extraction is disk-heavy).
3. Close other memory-heavy apps.
4. If it repeatedly stalls on the same stage, try re-running with a fresh bundle.

### Symptom: Dashboard loads but feels “stuck” or very slow

Likely causes:

- extremely large payload sections (partitions/events/workload tables)
- very large log volume (searching can be CPU-heavy)

Steps:

1. Start with Cluster Overview and Recommendations before opening heavy tabs.
2. Use narrow log filters (node prefix + targeted search text).
3. If it’s consistently slow for a specific report, treat it as an outlier bundle and regenerate with fewer collectors.

### Symptom: Logs view returns no entries

Likely causes:

- bundle didn’t include trace logs / required collectors
- logs were capped/sampled

Steps:

1. Confirm the support bundle includes tracelog collectors for the node(s) you care about.
2. Regenerate the bundle with logs enabled and re-upload.

### Reset local data

Close the app and delete the local data directory:

- `~/.s2-report-sniffer`

### Delete a single report

From the Report List, click the trash icon on the report row to delete it. This removes:

- the report’s metadata from `reports.sqlite`
- the report payload directory `reports/<report_id>/`

## FAQ

### Does this upload anything to the internet?

No. The desktop app runs locally on `127.0.0.1` and stores results on disk. Exports are explicit actions.

### What report types are supported?

- SingleStore support bundles as `.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`.

### What should I share when escalating an issue with the app?

Provide:

- report ID
- the exact symptom and the stage where it fails (upload, extraction, parsing, dashboard view)
- screenshots of the failing screen
- desktop app logs (OS + Electron logs if available)
