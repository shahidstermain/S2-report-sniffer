# Air-Gapped Test Protocol

This protocol verifies the application functions without internet connectivity and without remote services.

## Preconditions

- Machine has no outbound network connectivity (disable Wi-Fi and unplug Ethernet).
- Installer media is copied locally.

## Installation Verification

1. Install the application using the platform installer.
2. Launch the application.
3. Confirm the UI loads.
4. Confirm the backend responds:
   - open `/api/health` inside the app context and verify status is healthy or degraded with storage OK.

## Core Workflow Validation

### Upload and Parse

1. Upload a sample SingleStore report archive.
2. Wait for status to reach `ready`.
3. Open the report dashboard:
   - Overview
   - Nodes
   - Storage
   - Queries
   - Logs
   - Pipelines
   - Recommendations
   - Config

Acceptance criteria:

- All views load without network calls to external hosts.
- Recommendations contain `risk_score`, `confidence`, and `fix_first` fields.

### Persistence Across Restart

1. Close the application.
2. Re-open the application.
3. Confirm the report is still listed and dashboards can be opened.

## Offline Update Verification

1. Copy a newer installer package to the machine.
2. In the app, choose `File -> Install Update Package`.
3. Run the installer.
4. Re-open the app and confirm:
   - version changed
   - existing reports still present

## Evidence Capture

- Screenshots of all views
- A copy of the local data directory:
  - `~/.s2-report-sniffer` (or configured `S2RS_DATA_DIR`)
- A copy of `/api/health` JSON output

## Fail Criteria

Any of the following is an immediate fail:

- UI requires internet to load
- backend cannot start without internet
- data does not persist locally
- report parsing requires external services

