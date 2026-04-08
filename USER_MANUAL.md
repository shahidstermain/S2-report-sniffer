# S2 Report Sniffer — User Manual (Offline Desktop)

## What This App Does

S2 Report Sniffer analyzes SingleStore support report archives locally and produces:

- cluster and node health summaries
- storage and workload analysis
- log exploration
- SuperChecker findings with risk scoring, confidence, and fix-first prioritization

No cloud hosting is required.

## Installation (Desktop)

Install the package for your platform:

- Windows: run the MSI installer
- macOS: open the DMG and drag the app to Applications
- Linux:
  - AppImage: make executable and run
  - DEB/RPM: install with your system package manager

## First Launch

When you open the app:

- the backend starts on a local loopback port
- the UI opens automatically
- data is stored locally

## Uploading a Report

1. Click Upload
2. Select the archive (`.zip`, `.tar.gz`, `.tgz`, `.tar`, `.gz`)
3. Wait for processing to complete
4. Open the report dashboard

## Viewing Findings

The Recommendations view shows:

- Severity: `critical`, `warning`, `info`
- Risk score: `0–100`
- Confidence: `0.05–1.00`
- Fix First: highlights the most urgent/root-cause findings
- Correlated Findings: relationships between findings for root-cause grouping

## Viewing Logs

Logs are stored locally per report and can be filtered by:

- severity
- hostname prefix
- search text
- page/page size

## Exporting

Exports are available via API endpoints:

- Slack summary
- HTML export payload

## Offline Updates

To update without internet:

1. Obtain a newer installer package from a trusted source
2. Copy to the machine
3. In the app: `File -> Install Update Package`
4. Run the installer that opens

User data persists in the local data directory across updates.

## Local Data Location

Default location:

- `~/.s2-report-sniffer`

Contents:

- `reports.sqlite` (metadata)
- `reports/<id>/report.json` (report payload)
- `reports/<id>/logs.jsonl` (logs)

## Troubleshooting

### App opens but shows blank UI

- Restart the app.
- Verify the backend is running by opening:
  - `/api/health` in the embedded browser session

### Upload fails immediately

- Verify archive extension is supported.
- Verify file size is below the configured max size.

### Logs view returns no entries

- Some reports may not include parsed logs.
- Re-run report collection or ensure tracelog collectors are included in the archive.

### Reset local data

Close the app and delete the local data directory:

- `~/.s2-report-sniffer`

## Support

Provide:

- the report ID
- screenshots of the failing screen
- application logs from the OS (if available)

