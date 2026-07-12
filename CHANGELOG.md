# Changelog

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
