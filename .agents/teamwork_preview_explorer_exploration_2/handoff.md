# Handoff Report

## 1. Observation
I directly observed the following files, line numbers, and implementation details:
* **`backend/validators.py`**:
  * Lines 120-130: `validate_severity_filter` parses log severities from the set `valid_severities = {"debug", "info", "notice", "warning", "warn", "error", "fatal", "critical"}`.
  * Lines 260-301: `validate_report_structure` validates that top-level report structures contain `"report_name"`, `"parsed_at"`, and `"nodes"` keys, and that each node has `"hostname"` and `"role"`.
* **`backend/storage.py`**:
  * Lines 158-182: `_init_db` creates the SQLite schema for the `reports` table, containing specific fields like `health_score`, `recommendation_count`, and `cluster_risk_score`.
  * Lines 267-277: `update_report_fields` enforces a write allowlist (`allowed = { ... }`).
  * Lines 298-303: `get_report_fields` enforces a read allowlist (`allowed = [ ... ]`).
  * Lines 428-540: `query_report_logs` and `search_report_logs` filter and query log data from `logs.jsonl` files by comparing string values for severity and node prefix keys.
* **`backend/monitoring.py`**:
  * Lines 19-37: Defines `AlertSeverity` and `AlertCategory` enums for backend health alerts (e.g., failed parsing runs, rate limit breaches), decoupled from parsed report checks.
  * Lines 433-444: `record_parsing_duration` creates a parsing failure alert if the parsing job fails or crashes.
* **`backend/server.py`**:
  * Line 720-730: Recommendations are extracted from the parser. The severity is checked to count `critical` and `warning` counts to calculate `health_score`. The `cluster_risk_score` is computed by multiplying `risk_score` values by weights: `{"critical": 5, "warning": 3, "info": 1}`.
  * Line 791-802: Persists overall summary metadata to SQLite via `store.update_report_fields`.
  * Line 803-811: Persists the full schema-less JSON structure to `report.json` via `store.write_report_payload`.

---

## 2. Logic Chain
1. If check **severities** are modified in `superchecker.py` or `parsers.py` (e.g., adding a `"fatal"` severity level):
   * This directly alters the output list of recommendation objects.
   * `server.py` (lines 720-730) will fail to count the new severity towards `health_score` (defaulting to `"healthy"` if no other critical/warning exists).
   * `server.py` (line 728) will apply a default multiplier of `1` (via `.get(..., 1)`) instead of a high multiplier for the risk score weight, throwing off `cluster_risk_score` calculation.
   * The frontend mapping in `Recommendations.jsx` and `ClusterOverview.jsx` will fail to associate the badge styles, causing UI bugs.
2. If finding **keys** are modified (e.g., renaming `risk_score` to `risk` or `severity` to `level`):
   * `server.py` (line 727) reads `r.get("risk_score", 0)`. If renamed, it will fall back to `0`, making the aggregate `cluster_risk_score` always evaluate to `0` in SQLite.
3. If **parser output structures** are altered:
   * `validators.py` (`validate_report_structure`) will fail to find `"report_name"`, `"parsed_at"`, or `"nodes"`, and will reject the upload.
   * `server.py` (`update_doc` / `update_report_fields`) will fail to find keys (e.g., `nodes`, `deployment_signals`, `databases`) and will save empty values to SQL/JSON.
   * `storage.py` (log search) will fail to query log messages if hostname or severity keys inside log objects are renamed.
   * Any new metrics to be stored as first-class SQLite fields must update the 3-place allowlist in `storage.py` (`_init_db`, `update_report_fields`, `get_report_fields`).

---

## 3. Caveats
* This is a read-only investigation. No code was executed or modified in the backend files.
* Assumes that the SQLite database engine remains the active storage driver (no Postgres migrations active).
* The log severities (`debug`, `warning`, etc.) are treated differently from check severities. Changes in log severities only affect trace log filtering, not the recommendation logic.

---

## 4. Conclusion
While recommendation details are stored as schema-less JSON in `report.json` and are highly flexible, the metadata and score aggregations are closely integrated. Any change in check structure, severity, or keys requires updates across:
1. `server.py` (for calculating `health_score`, `cluster_risk_score`, and serializing deployment metrics).
2. `storage.py` (for SQLite columns, write/read allowlists, and log queries).
3. `validators.py` (for top-level schema validation).
4. `superchecker.py` (for clamping severities in the `_add` method).
5. The frontend React UI components (for icon and styling maps).

---

## 5. Verification Method
Verify that changes to the checker structures do not break integration by running the backend test suites:
```bash
# Run pytest from the backend directory
cd backend
.venv/bin/python -m pytest test_validators.py test_monitoring.py test_parsers.py test_superchecker.py -v
```
To invalidate these findings: if `server.py` or the frontend is updated to dynamically parse severities/weights or dynamically populate SQLite columns without static lists, this audit's modification checklist would be updated.
