# Check Integration and Schema Validation Audit

## Executive Summary
This audit outlines how checker outputs, recommendations, and parsed data structures from `backend/superchecker.py` and `backend/parsers.py` integrate with the rest of the application. It highlights the dependencies, validation checks, persistence patterns, and failure paths, providing a step-by-step checklist of files and sections that must be modified if checker keys, structures, or severities are changed.

---

## 1. Component Analysis & Integration Points

### A. `backend/validators.py`
`validators.py` acts as the first line of defense for external user inputs and parsed payloads.

* **Top-Level Parsed Schema Validation (`validate_report_structure`)**:
  * Asserts that incoming parsed report payloads are dictionaries containing at least `"report_name"`, `"parsed_at"`, and `"nodes"`.
  * Verifies each entry in the `"nodes"` list is a dictionary containing `"hostname"` and `"role"`.
  * If the parser or check outputs rename these primary keys, validation will fail with `MISSING_FIELD` or `MISSING_NODE_FIELD` validation errors, aborting the import.
* **Log Severity Filter (`validate_severity_filter`)**:
  * Defines a strict set of accepted trace log severities: `{"debug", "info", "notice", "warning", "warn", "error", "fatal", "critical"}`.
  * If a log parser introduces a custom severity level, it will be stripped out during log search query parsing unless explicitly registered here.
* **Input Sanitization (`sanitize_dict` & `validate_parsed_report_safe`)**:
  * Recursively sweeps all dictionary keys and values to prevent XSS (escaping `<script>`, `onerror`, etc.).
  * Does not validate recommendation fields or keys individually. It handles the list of recommendations as generic, schema-less JSON objects, ensuring that any modifications to check fields do not trigger validation rejections as long as they do not contain injection patterns.

---

### B. `backend/storage.py`
`storage.py` handles the persistence of report summaries in SQLite and full details in JSON files on disk.

* **Database Columns vs. Document Payload**:
  * The database schema (`reports` table) stores specific aggregated metrics from the parser and superchecker:
    * `health_score` (aggregated status: "healthy", "warning", or "critical")
    * `recommendation_count` (total findings count)
    * `cluster_risk_score` (aggregated cluster risk)
  * The rest of the parsed recommendations list, query patterns, and database details are stored as a raw JSON blob (`report.json`) using `write_report_payload`.
* **The "3-Place Allowlist" Constraint**:
  * If a new column is added to the SQLite database (e.g. to elevate a checker metric into a first-class report metadata field), it **must be registered in all three places** in `backend/storage.py`:
    1. **Schema Initialization (`_init_db`)**: `ALTER TABLE reports ADD COLUMN <column_name> <TYPE>`
    2. **Write Allowlist (`update_report_fields`)**: Add `<column_name>` to the `allowed` set.
    3. **Read Allowlist (`get_report_fields`)**: Add `<column_name>` to the `allowed` list.
  * Failing to update all three places will cause the field to be silently dropped during reads or writes.
* **Log Queries (`query_report_logs` & `search_report_logs`)**:
  * Scans `logs.jsonl` files and performs filtering based on exact string matches of the `severity` and `hostname` keys.
  * If `parsers.py` changes the schema of log lines (e.g., renaming `hostname` to `host` or `severity` to `level`), log search and filtering will silently return zero results.

---

### C. `backend/monitoring.py`
`monitoring.py` tracks the health of the sniffer system itself (parsing times, metrics, system alerts, and rate limits) rather than report database metrics.

* **Decoupled Alert Severities**:
  * Defines its own `AlertSeverity` enum (`debug`, `info`, `warning`, `error`, `critical`) and `AlertCategory` enum (`parsing`, `validation`, `security`, `performance`, `storage`, `replication`, `availability`, `system`, `upload`).
  * While names are similar to `superchecker.py`, these are used for internal server monitoring (e.g., logging an alert when a database operation fails or when upload rate limits are hit).
* **Fault Tolerance & System Alerts**:
  * If an unhandled exception occurs inside a checker or parser, the server catches it in a fallback wrapper in `parsers.py` (`generate_recommendations` catches exceptions from `superchecker.run_superchecker` and falls back to a basic rule set).
  * If the parser itself crashes completely, `server.py` logs a system alert with severity `AlertSeverity.ERROR` in the `AlertManager`.

---

### D. The Orchestrator: `backend/server.py` (Crucial Glue layer)
Although not explicitly under review, `server.py` coordinates the parser, storage, and checker outputs, making it the most critical dependency point.

* **Health Score Computation**:
  * Server maps check severities directly to a global health state:
    ```python
    critical = sum(1 for r in recs if r.get("severity") == "critical")
    warnings = sum(1 for r in recs if r.get("severity") == "warning")
    health_score = "critical" if critical > 0 else ("warning" if warnings > 0 else "healthy")
    ```
* **Risk Score Weighting**:
  * Maps severity strings to integer multiplier weights to compute a composite cluster risk score:
    ```python
    severity_weight = {"critical": 5, "warning": 3, "info": 1}
    for r in recs[:100]:
        rs = int(r.get("risk_score", 0))
        w = severity_weight.get(r.get("severity", "info"), 1)
        cluster_risk_score += min(100, rs) * w
    ```
* **Deployment Field Mapping**:
  * Extracts deployment fields and sanitizes list outputs into comma-separated strings before updating DB columns:
    ```python
    "deployment_signals": ",".join(deployment_signals) if isinstance(deployment_signals, list) else ...
    ```

---

## 2. Modification Impact Checklist

If you modify checkers, keys, or severities in `superchecker.py` or `parsers.py`, you **must** update the following components:

### 1. If Adding or Renaming Severity Levels
* [ ] **`backend/superchecker.py` (`_add` method)**:
  * Update the validation check at line 137:
    `severity = severity if severity in ("critical", "warning", "info", "<NEW_SEVERITY>") else "info"`
  * Add the new severity to `SEVERITY_WEIGHT` constant at the top of the file to compute `risk_score`.
* [ ] **`backend/server.py` (`parse_background_task` / health calculation)**:
  * Update the severity counting logic (lines 721-723) to incorporate the new severity in `health_score`.
  * Add the new severity and its weight to the `severity_weight` lookup dictionary (line 724).
* [ ] **`frontend/src/components/` (specifically `Recommendations.jsx` and `ClusterOverview.jsx`)**:
  * Update React badge components, colors, and severity filters to support the new styling and icons.

### 2. If Renaming/Modifying Finding Schema Keys (e.g. `risk_score`, `severity`)
* [ ] **`backend/server.py`**:
  * Update calculations for health scores and risk scores to reference the new keys.
* [ ] **`frontend/src/lib/api.js` & React Components**:
  * Review all UI references to findings and recommendation payloads (e.g., search functions, table headers, sorting) to ensure key names match.

### 3. If Changing Parser Output Structures (e.g., `nodes`, `dmesg_events`, `replication_status`)
* [ ] **`backend/validators.py` (`validate_report_structure`)**:
  * Adjust structural validators if the key name or type changes (e.g. changing `nodes` from list to dictionary).
* [ ] **`backend/server.py`**:
  * Update `update_doc` dictionary construction (lines 747-789) to extract new/renamed keys from parsed payload.
* [ ] **`backend/storage.py`**:
  * If a new top-level SQL field is introduced to display summary data in the report list, implement the **3-place allowlist changes** (`_init_db()`, `update_report_fields()`, `get_report_fields()`).
