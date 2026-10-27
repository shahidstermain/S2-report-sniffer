# Changelog

All notable user-facing changes are documented here. Release packages, checksums, and generated notes are available on the [GitHub Releases page](https://github.com/shahidstermain/S2-report-sniffer/releases).

## [1.2.8](docs/releases/v1.2.8.md) — 2026-10-28

### Analysis resilience & grounding
- Grounded `cpuGovernor` and `cpuIowait` in `backend/grounding.py` and added regression testing ensuring 100% of SuperChecker checker IDs have documented groundings.
- Hardened SuperChecker initialization and capacity checks against `None` or malformed node records, missing metrics, and non-numeric strings across 29 potential crash paths.
- Fixed Evidence Coverage calculation in report overview to reflect actual diagnostic data sources (`mv_nodes`, `cluster_status`, `show_variables`, `processlist`, and `tracelogs`) rather than solely checking `dmesg`.

### Storage UI enhancements
- Added interactive click-to-expand breakdown for **Cluster Overhead** and its subcategories in Storage Distribution and Disk Intelligence views, explaining mount filesystem metadata, OS temporary files, and memsqld binary allocations.

## [1.2.7](docs/releases/v1.2.7.md) — 2026-10-27

### Analysis correctness
- Aligned table skew analytics with SingleStore's *Detecting and Resolving Data Skew* guidance: compute skew over the full `TABLE_STATISTICS` census (200k-row re-read) instead of the 5,000-row UI display cap, exclude noisy tables with `<= 10,000` rows (`HAVING SUM(ROWS) > 10000`), and use the documented `10%` CV threshold (`HIGH_SKEW_CV_PCT = 10`) instead of `50%`.
- Hardened the streaming JSON row extractor against object-boundary chunk stalls and duplicate `"rows"` array re-parsing.
- Fixed false critical `userDatabaseRedundancy` on healthy HA Cluster Reports by reading official `SHOW CLUSTER STATUS` / `MV_CLUSTER_STATUS` column `STATE` (`DATABASE_NAME`) and treating `replicating` as healthy.
- Fixed false critical `unmappedMasterPartitions` and `duplicatePartitionDatabase` on official `SHOW PARTITIONS` rows (`Ordinal`, `Host`, `Role`).
- Fixed false critical `severeLockContention` when 10+ unrelated `MV_BLOCKED_QUERIES` rows use the documented `BLOCKING_ID` column.
- Fixed false critical `transparentHugepage` when a Cluster Report omits the `transparentHugepage` / `thp` host collector (`status=unknown`).

### Privacy and UI
- Fixed report anonymization to alias FQDNs stored only in `cluster_overview.nodes_detail[].ip_addr` (`MV_NODES.Host`) as `NODE_*` while keeping IP literals on `IP_*`.
- Preserved `unknown` health metrics across backend normalization and frontend display helpers (`RecentActivity` and `ReportList`), and normalized Electron window zoom to 100%.
- Fixed bundled macOS desktop backend startup health check reliability.

### Removed
- Removed the synthetic demo workspace, its backend provisioning endpoint, and all demo-specific dashboard controls.
- Existing synthetic demo reports are deleted automatically when an older local data directory is opened.

## [1.2.6](docs/releases/v1.2.6.md) — 2026-08-24

### Guided demo mode
- Added a local synthetic incident/remediation workspace, contextual explanations, metric glossary, and capability-aware dashboard tours.
- Aligned demo findings, health scoring, metadata, chronology, and feature capabilities with production report contracts.
- Added race-safe workspace provisioning and regression coverage for concurrent launches.
- Made guided tours keyboard-modal, Escape-dismissible, and safe when browser storage or report tabs are unavailable.
- Kept Guided Help fully visible in compact app windows with a viewport-bounded, scrollable modal.
- Added production-shaped synthetic disk capacity, overhead, blob-delta, table-storage, partition, and remediation evidence for presentations.

### macOS distribution
- Focused official desktop packages on macOS Apple Silicon and Intel.
- Removed Windows and Linux jobs from the release workflow.
- Added deterministic merging of native architecture updater manifests and a combined macOS checksum manifest.

## [1.2.5](docs/releases/v1.2.5.md) — 2026-08-23

### Release manifests
- Replaced the Unix-only `shasum` pipeline with a deterministic cross-platform Python checksum generator.
- Added regression coverage for manifest ordering and SHA-256 output format.
- Windows installer creation was already successful before the old checksum command failed; this correction makes artifact publication portable across every release runner.

## [1.2.4](docs/releases/v1.2.4.md) — 2026-08-23

### Windows packaging
- Regenerated the Windows application icon as a standards-compliant six-frame ICO containing sizes from 16×16 through 256×256.
- Fixed the icon generator to use its largest frame as Pillow's ICO source; the previous implementation silently emitted only the 16×16 frame.
- Added a binary-format regression test requiring a 256px Windows icon frame.

## [1.2.3](docs/releases/v1.2.3.md) — 2026-08-23

### Cross-platform packaging
- Added the homepage metadata required by Linux DEB packaging.
- Made the unified desktop build script understand Windows virtual environments and `.exe` backend artifacts.
- Made the `afterPack` backend-permission hook work with macOS app bundles, Linux unpacked apps, and Windows resources.
- Added regression coverage for Windows venv/interpreter and backend executable paths.

## [1.2.2](docs/releases/v1.2.2.md) — 2026-08-23

### Release reliability
- Corrected Windows CI to use the Python interpreter installed by `actions/setup-python`.
- Removed a legacy electron-builder Windows signing option that invalidated the shared configuration on every platform after the secure toolchain upgrade.
- Verified the complete macOS Apple Silicon package locally, including backend bundle, DMG, ZIP, ad-hoc sealed signature, and signature validation.

## [1.2.1](docs/releases/v1.2.1.md) — 2026-08-23

### Distribution and documentation
- Rebuilt the repository front page around download-first onboarding, accurate feature descriptions, privacy guarantees, and transparent Finding Severity Index semantics.
- Consolidated source, issues, documentation, and binary downloads in this canonical repository.
- Corrected the desktop release workflow to build unsigned community packages without unavailable certificate or cross-repository token secrets.
- Replaced the retired macOS 13 Intel runner with `macos-15-intel`.
- Corrected Windows packaging so unsigned NSIS builds are allowed and update metadata targets this repository.
- Updated packaging, user-manual, terminology, and long-form overview documentation to match the current product and release process.

## [1.2.0] — 2026-08-23

### Analysis correctness
- Query analysis now treats `MV_PROCESSLIST.TIME` as age in the current process state rather than guaranteed end-to-end runtime, and excludes sleeping/system sessions from active-query findings.
- Query tracing no longer treats a processlist client `HOST` as a cluster node, carries documented blocker identities, uses `REASON_FOR_QUEUEING`, and distinguishes query-scoped log evidence from node-level time-window evidence.
- Replication analysis separates measured elapsed lag from LSN/volume backlog, catch-up estimates, connectivity failures, paused links, async transitions, and throttling.
- CPU and network counters are labeled as cumulative since boot; loopback traffic is excluded.
- Cluster layout parsing handles documented synchronous/asynchronous replica roles and marks incomplete counts as lower bounds.
- The improved table-skew analyzer is retained with exact population CV, correct MiB conversion, and guarded idle-leaf detection.

### Explainability
- Added the backend Guided/Demo explainer catalog for KPI definitions and per-checker grounding.
- Added `GET /api/explainers` and `GET /api/explainers/{id}`.
- Exported reports now identify Sniffer-owned severity and risk metrics explicitly.

### Security and dependencies
- Updated `aiohttp`, `cryptography`, and `pyasn1` to patched versions.
- Cleared production frontend advisories in `fast-uri`, `nanoid`, `postcss`, and React Router.

### Distribution
- Release packages are built for macOS Apple Silicon, macOS Intel, Windows x64, and Linux x64.
- Current community packages are unsigned; every platform build includes a SHA-256 checksum manifest.
- Releases are published in this repository so the README, source, issues, and downloads remain in one canonical location.

### Validation
- Full backend suite: 766 passed, 1 skipped.
- Frontend tests and production build passed.
- Backend and frontend dependency audit gates passed.

## 2026-06-30

### Fixed
- Upload error response bodies now include the correct `filename` — three error paths were referencing the legacy `file` variable instead of `active_file` after the multipart field-alias change, causing `null` filenames in validation/security events.
- Replaced deprecated `asyncio.get_event_loop()` with `asyncio.get_running_loop()` inside the background report-parse task — eliminates the Python 3.12+ DeprecationWarning.
- Alert history in `AlertManager` is now bounded by `max_history` (default 500) using `deque(maxlen=N)`, preventing unbounded memory growth on long-running instances.
- Rate-limit table (`_upload_counts`) now evicts stale IPs (entries with empty timestamp lists) on each upload request, preventing unbounded dict growth under high client-IP churn.

### Changed
- Moved `json` and `aiofiles` to module-level imports in `server.py`, replacing seven `__import__('json')` inline calls and a per-request `import aiofiles` inside the upload handler.
- Frontend vendor JS is now split into separate `react`, `ui`, `chart`, and `form` chunks via Vite `manualChunks`, reducing initial bundle parse time.

### Infrastructure
- Added gstack skill-routing section to `CLAUDE.md` and `AGENTS.md` for AI-assisted development workflows.
- Added `pre-push` credential-blocking hook (`.githooks/pre-push`) that rejects pushes containing AWS keys, GitHub PATs, Slack tokens, and SSH/PGP private keys.

## 2026-04-08
- Added explicit network root-cause detection in [superchecker.py](file:///Users/shahidmoosa/cr-sniffer/S2-report-sniffer/backend/superchecker.py):
  - New checker `firewallPortBlocking` identifies suspected blocked inter-node ports from rebalance sync failures.
  - Extracts source/target host:port pairs and surfaces actionable remediation for firewall/ACL validation.
  - Correlation engine now suppresses secondary `disconnectedReplicationSlaves` alerts when `firewallPortBlocking` is present.
- Extended parser coverage in [parsers.py](file:///Users/shahidmoosa/cr-sniffer/S2-report-sniffer/backend/parsers.py):
  - Added `parse_rebalance_status()` to ingest rebalance artifacts from common collector filenames.
  - Exposed normalized rebalance data under `cluster_overview.rebalance_status`.
- Added regression tests:
  - [test_superchecker.py](file:///Users/shahidmoosa/cr-sniffer/S2-report-sniffer/backend/test_superchecker.py): firewall-port detection and root-cause suppression behavior.
  - [test_parsers.py](file:///Users/shahidmoosa/cr-sniffer/S2-report-sniffer/backend/test_parsers.py): rebalance parser candidate-file ingestion.
- Backward compatibility:
  - No API contract removal; recommendations endpoint shape remains unchanged.
  - New finding is additive and only appears when matching evidence exists.
