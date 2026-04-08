# Changelog

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
