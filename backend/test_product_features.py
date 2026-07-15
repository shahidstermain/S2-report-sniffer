import json
from pathlib import Path

from parsers import parse_sparse_report_file
from product_features import (
    anonymize_report,
    build_capabilities,
    build_markdown_export,
    build_portable_html,
    compare_reports,
    TelemetryStore,
)


def sample_payload():
    return {
        "id": "report-1",
        "report_name": "customer-prod.zip",
        "cluster_overview": {"version": "8.7.12", "total_nodes": 2},
        "nodes": [
            {
                "hostname": "db-prod-01.example.com",
                "version": "8.7.12",
                "show_variables": {"bind_address": "10.2.3.4", "password": "secret-value"},
            }
        ],
        "databases": [{"DATABASE_NAME": "customer_orders"}],
        "queries": [{"QUERY_TEXT": "select * from customer_orders where token='abc123'"}],
        "logs": [{"hostname": "db-prod-01.example.com", "message": "connect 10.2.3.4 password=hunter2"}],
        "recommendations": [
            {
                "checker_id": "diskUsage",
                "severity": "critical",
                "risk_score": 90,
                "confidence": 0.9,
                "title": "Disk usage high",
                "description": "Disk on db-prod-01.example.com is high",
                "remediation": "Free disk space",
                "evidence": "10.2.3.4 / customer_orders",
            }
        ],
        "storage": [{"DATABASE_NAME": "customer_orders", "SIZE_MB": 100}],
        "config_health": {"issues": 1},
        "log_count": 1,
    }


def test_build_capabilities_is_version_aware_and_marks_partial_data():
    payload = sample_payload()
    payload["queries"] = []
    capabilities = build_capabilities(payload)
    assert capabilities["engine_version"] == "8.7.12"
    assert capabilities["version_support"] == "supported"
    assert capabilities["mode"] == "bundle"
    assert capabilities["features"]["overview"]["available"] is True
    assert capabilities["features"]["queries"]["available"] is False
    assert "query" in capabilities["features"]["queries"]["reason"].lower()


def test_anonymize_report_masks_sensitive_values_consistently():
    payload = sample_payload()
    cleaned, manifest = anonymize_report(payload)
    blob = json.dumps(cleaned)
    assert "db-prod-01.example.com" not in blob
    assert "10.2.3.4" not in blob
    assert "customer_orders" not in blob
    assert "hunter2" not in blob
    assert "secret-value" not in blob
    assert cleaned["nodes"][0]["hostname"] == cleaned["logs"][0]["hostname"]
    assert cleaned["nodes"][0]["hostname"].startswith("NODE_")
    assert manifest["enabled"] is True
    assert manifest["replacements"] >= 4


def test_anonymize_report_masks_compound_credential_field_names():
    payload = {
        "config_health": {
            "admin_password": "admin-secret",
            "aws_secret_access_key": "aws-secret",
            "oauth_client_secret": "oauth-secret",
            "database_credentials": "database-secret",
            "jwt_signing_key": "jwt-secret",
            "refreshToken": "refresh-secret",
        }
    }
    cleaned, manifest = anonymize_report(payload)
    assert set(cleaned["config_health"].values()) == {"[REDACTED]"}
    assert manifest["replacements"] == 6


def test_anonymize_report_masks_sensitive_dictionary_keys():
    payload = {
        "nodes": [{"hostname": "prod-db-01"}],
        "per_node": {
            "prod-db-01": {"connections_by_ip": {"10.2.3.4": 7}},
        },
        "config_health": {
            "variable_consistency": {
                "maximum_memory": {
                    "values": {"prod-db-01": "1024"},
                }
            }
        },
    }

    cleaned, _manifest = anonymize_report(payload)
    blob = json.dumps(cleaned)

    assert "prod-db-01" not in blob
    assert "10.2.3.4" not in blob
    assert "NODE_1" in cleaned["per_node"]
    assert "IP_1" in cleaned["per_node"]["NODE_1"]["connections_by_ip"]
    assert (
        cleaned["config_health"]["variable_consistency"]["maximum_memory"]["values"]
        == {"NODE_1": "1024"}
    )


def test_anonymize_report_does_not_rewrite_schema_keys_on_alias_collision():
    payload = {
        "node": "node",
        "node_count": 1,
        "nodes": [{"hostname": "node"}],
        "per_node": {"node": {"status": "online"}},
    }

    cleaned, _manifest = anonymize_report(payload)

    assert cleaned["node"] == "NODE_1"
    assert cleaned["node_count"] == 1
    assert cleaned["nodes"][0]["hostname"] == "NODE_1"
    assert cleaned["per_node"]["NODE_1"]["status"] == "online"


def test_compare_reports_includes_configuration_and_metric_deltas():
    before = sample_payload()
    after = sample_payload()
    before["cluster_overview"]["total_nodes"] = 2
    after["cluster_overview"]["total_nodes"] = 3
    before["nodes"][0]["show_variables"]["maximum_memory"] = "100"
    after["nodes"][0]["show_variables"]["maximum_memory"] = "200"
    after["recommendations"].append({
        "checker_id": "replicationLag", "severity": "warning", "risk_score": 70,
        "title": "Replication lag", "confidence": 0.8,
    })
    result = compare_reports(before, after)
    assert result["summary"]["new_findings"] == 1
    assert result["metrics"]["total_nodes"]["before"] == 2
    assert result["metrics"]["total_nodes"]["after"] == 3
    assert any(row["key"] == "maximum_memory" for row in result["configuration_changes"])


def test_exports_are_customer_facing_and_escape_untrusted_content():
    payload = sample_payload()
    payload["recommendations"][0]["title"] = "Disk <script>alert(1)</script>"
    markdown = build_markdown_export(payload)
    html_doc = build_portable_html(payload)
    assert "## Recommended actions" in markdown
    assert "Free disk space" in markdown
    assert "<!doctype html>" in html_doc.lower()
    assert "<script>alert(1)</script>" not in html_doc
    assert "&lt;script&gt;" in html_doc
    assert "https://" not in html_doc


def test_sparse_log_file_creates_log_capability_without_fake_topology(tmp_path: Path):
    log_file = tmp_path / "memsql.log"
    log_file.write_text("2026-07-12 10:20:30.123 ERROR Out of memory on 10.2.3.4\n")
    result = parse_sparse_report_file(str(log_file))
    assert result["input_mode"] == "sparse"
    assert result["raw_node_count"] == 0
    assert result["logs"]
    assert result["capabilities"]["features"]["logs"]["available"] is True
    assert result["capabilities"]["features"]["storage"]["available"] is False


def test_telemetry_store_is_disabled_by_default_and_records_only_allowlisted_fields(tmp_path: Path):
    store = TelemetryStore(tmp_path)
    assert store.get_settings()["enabled"] is False
    assert store.record("parse_complete", {"duration_ms": 1200, "checker_ids": ["diskUsage"], "hostname": "secret"}) is False
    store.update_settings(enabled=True)
    assert store.record("parse_complete", {"duration_ms": 1200, "checker_ids": ["diskUsage"], "hostname": "secret"}) is True
    events = store.read_events()
    assert events[0]["duration_ms"] == 1200
    assert events[0]["checker_ids"] == ["diskUsage"]
    assert "hostname" not in events[0]
    assert store.get_settings()["external_delivery"] is False
